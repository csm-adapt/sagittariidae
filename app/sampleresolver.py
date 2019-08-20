
import threading

from sqlalchemy.orm import aliased

from . import models
from . import app    as sagittariidae
from functools import reduce

class _HashableSample_(object):
    """
    A hashable wrapper for Samples.  Hashing on the instance value makes it
    possible to exploit Python's `set` functions to ultimately find only those
    Samples that match all of the specified search tokens.

    Note that this hashing functionality is intentionally not folded into the
    model.  As a resource, a Sample has neither an `id` nor an `obfuscated_id`
    until it is written to the table.  Thus this mechanism for computing a hash
    doesn't return a consistent value for an instance in all circumstances.

    Therefore it is relegated to this wrapper where we can guarantee that the
    Samples that we're working with will have these values defined.
    """

    def __init__(self, sample):
        self.sample = sample

    def __key__(self):
        return (self.sample.id,
                self.sample.obfuscated_id,
                self.sample._project_id)

    def __hash__(self):
        return hash(self.__key__())

    def __eq__(self, o):
        return self.__key__() == o.__key__()

    def __repr__(self):
        return self.sample.__repr__()


class _Resolver_(threading.Thread):

    project = None
    token   = None
    results = None

    def resolve(self):
        raise NotImplementedError()

    def run(self):
        self.results = set()
        try:
            for sample in self.resolve(self.token, self.project.id):
                self.results.add(_HashableSample_(sample))
        except Exception as e:
            sagittariidae.app.logger.error('Unhandled exception in Resolver %s', self, exc_info=e)


class _StageAnnotationResolver_(_Resolver_):

    def resolve(self, token, project_id):
        q = models.db.session.query(models.SampleStage).\
            join(models.Sample.sample_stages).\
            filter(models.Sample._project_id == project_id).\
            filter(models.SampleStage.annotation.ilike(token))
        return [s.sample for s in q.all()]


class _SampleNameResolver_(_Resolver_):

    def resolve(self, token, project_id):
        q = models.db.session.query(models.Sample).\
            filter(models.Sample._project_id == project_id).\
            filter(models.Sample.name.ilike(token))
        return q.all()


class _StageMethodResolver_(_Resolver_):

    def resolve(self, token, project_id):
        sample_stage_1 = aliased(models.SampleStage)
        q = models.db.session.query(models.SampleStage).\
            join(models.Sample.sample_stages).\
            join(sample_stage_1, models.Method.sample_stages).\
            filter(models.SampleStage.id == sample_stage_1.id).\
            filter(models.Sample._project_id == project_id).\
            filter(models.Method.name.ilike(token))
        return [s.sample for s in q.all()]


_RESOLVER_TYPES_ = [_SampleNameResolver_,
                    _StageMethodResolver_,
                    _StageAnnotationResolver_]


class SampleTokenResolver():

    def __init__(self, project):
        self.project = project

    def resolve(self, token):

        def make_resolver(cls, token, project):
            results          = set()
            resolver         = cls()
            resolver.project = project
            resolver.token   = '%%%s%%' % token
            return resolver

        resolvers = [make_resolver(t, token, self.project) for t in _RESOLVER_TYPES_]

        # FIXME!
        #
        # SQLite doesn't allow objects created in one thread to be used in
        # another, and it looks like SQLAlchemy models maintain references to
        # implementation objects.  Since models are the way that we communicate
        # between the persistence and presentation layers, we unfortunately for
        # now must query using Flask worker thread that is handling the
        # request.
        #
        # One way of working around this is to have resolver threads return
        # only the sample ID, and then have the presentation layer fetch all
        # those samples in its own thread.
        #
        # For now though, to meet a looming demo deadline, I'm leaving this as
        # is, and we can explore solutions after the demo.

        # for resolver in resolvers:
        #     resolver.start()
        # for resolver in resolvers:
        #     resolver.join()

        for resolver in resolvers:
            resolver.run()

        candidate_results = [r.results for r in resolvers]
        return reduce(lambda union, s: union | s, candidate_results, set())


class SampleResolver():

    def resolve(self, tokens, project_id):
        project = models.get_project(obfuscated_id=project_id)
        candidate_results = [s for s in [SampleTokenResolver(project).resolve(t) for t in tokens] if len(s) > 0]

        # `reduce` won't reduce with an empty collection without an inital
        # value.  We don't provide an initial value because the only thing that
        # we possibly could provide is an empty set, which would break our
        # selection of the intersection of the results from the resolvers.
        if len(candidate_results) > 0:
            return [hashable.sample for hashable in reduce(lambda intersection, s: intersection & s,
                              candidate_results)]
        else:
            return []
