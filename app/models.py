
import enum
import hashids
import json
import os
import re
import string

from flask                     import abort
from sqlalchemy                import Enum, ForeignKey, Column, String, TIMESTAMP, Text, Integer
from sqlalchemy                import event
from sqlalchemy.exc            import OperationalError, IntegrityError
from sqlalchemy.ext.hybrid     import hybrid_property
from sqlalchemy.orm            import Session
from sqlalchemy.orm            import relationship
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.exc        import NoResultFound, MultipleResultsFound
from sqlalchemy.sql.expression import func
from urllib.parse                    import quote

from . import http

from .app import app, db


BAD_URI_PAT  = re.compile("%.{2}|\/|_")
COLLAPSE_PAT = re.compile("-{2,}")


@event.listens_for(Session, 'after_flush_postexec')
def inject_obfuscated_id_after_flush_postexec(session, flush_context):
    def inject_obfuscated_id(m):
        if m.obfuscated_id is None:
            m.obfuscated_id = m.__hashidgen__.encode(m.id)
        return m
    return [inject_obfuscated_id(m) for m in list(session.identity_map.values())]


def with_transaction(session, f):
    """
    Execute `f` in a DB transaction.  If `f` completes successfully, the
    transaction is committed, otherwise an error is raised and the transaction
    is rolled back.

    `f` must accept a single argument: the database session instance.
    """
    try:
        f(session)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e


class HashIds(hashids.Hashids):
    """
    HashID generator for our resources.  Database-assigned IDs are
    hashed/obfuscated to avoid leaking implementation details and creating
    unintentional expectations around resource identification.q
    cf. http://hashids.org
    """
    def __init__(self, salt, min_length=5):
        super(HashIds, self).__init__(
            salt=';'.join(['sagittarius', salt]),
            min_length=min_length)


class Representable:
    """
    A base class for Models that generically generates a String representation
    of the model and its properties.
    """
    def __repr__(self):
        def repr_attr(k):
            return '%s=%s' % (k, getattr(self, k))
        reprified_attrs = [repr_attr(k) for k in iter(sorted(self.__dict__.keys()))
                           if not k.startswith('_')]
        if len(reprified_attrs) == 0:
            attrs_repr = '<no instance attributes>'
        else:
            attrs_repr = ', '.join(reprified_attrs)
        return '<%s: %s>' % (self.__class__.__name__, attrs_repr)


class ResourceMetaClass(type(db.Model)):
    """
    A metaclass that injects the identifier fields that should be present on
    all Models.
    """
    def __new__(metacls, clsname,  parents, attrs):
        attrs['id'] = Column(Integer, primary_key=True)
        attrs['obfuscated_id'] = Column(String(15), unique=True)
        return super(ResourceMetaClass, metacls).__new__(
            metacls, clsname, (Representable,) + parents, attrs)


def get_resource(q, abort_not_found=True):
    """
    Retrieve a single resource using the model using a Flask-SQLAlchemy query.
    A `MultipleResultsFound` error will be raised if more than one result is
    returned by the query. In most cases it is sufficient to allow this to
    bubble up and be captured as a `500` ServerInternalError as - given a
    rigidly-defined API that doesn't allow the client to specify query
    parameters directly - it is more likely that the query has been incorrectly
    constructed from the request parameters than it is that the user has
    constructed a bad query.
    """
    r = q.one_or_none()
    # Note the use of `one_or_none` and not `first_or_none`; the latter won't
    # complain if multiple resources are returned.  In almost all cases we

    # Retrieve the resource and make sure that we're getting exactly one.
    # Because we're allowing an arbitrary filter, it's possible that a buggy
    # call could result in multiple resources being returned, which is almost
    # always the wrong thing to do when *a* resource is sought.  It's worth
    # being paranoid about this because simply returning the first of many
    # resources could result in mutating changes being applied to the wrong
    # resource.
    #
    # Note, therefore, that we're NOT using Flask-SQLAlchemy's `first_or_404`,
    # which won't complain if multiple results are returned.

    if r is None and abort_not_found:
        abort(http.HTTP_404_NOT_FOUND)
    else:
        return r


class Project(db.Model, metaclass=ResourceMetaClass):
    __tablename__ = 'project'
    __hashidgen__ = HashIds('Project')

    name = Column(String(80), unique=True)
    sample_mask = Column(String(64), unique=False)
    # objects forward-related to project
    samples = relationship(
        'Sample', backref='project', lazy='dynamic')


def get_projects():
    """
    Returns a list of dicts, where each contains summary information about a
    project.
    """
    return Project.query.all()


def get_project(abort_not_found=True, **project_filters):
    """
    Retrieve summary information (as a dict) for a single project. The fields
    by which the project is to be identified must be specified as
    `project_filters`,
    ```
    get_project(id="5QMVv")
    ```
    If `abort_not_found` is `True`, processing will be short-circuited with a
    404 if the project can not be found.
    """
    return get_resource(
        Project.query.filter_by(**project_filters), abort_not_found)


def add_project(name, sample_mask):
    """
    Adds a new project.
    """
    try:
        _ = Project.query.first()
    except OperationalError:
        db.create_all()
    p = Project(name=name, sample_mask=sample_mask)
    with_transaction(db.session, lambda session: session.add(p))
    return Project.query.filter_by(id=p.id).one()


class Sample(db.Model, metaclass=ResourceMetaClass):
    __tablename__ = 'sample'
    __hashidgen__ = HashIds('Sample')

    name = Column(String(80), unique=True)
    _created_ts = Column("created_ts", TIMESTAMP, server_default=func.now())
    # to what project does this sample belong
    _project_id = Column('project_id', Integer, ForeignKey('project.id'))

    # objects forward-related to sample
    sample_stages = relationship(
        'SampleStage', backref='sample', lazy='dynamic')

    @property
    def project_id(self):
        return self.project.obfuscated_id


def get_sample(sample_filters, abort_not_found=True):
    return get_resource(
        Sample.query.filter_by(**sample_filters),
        abort_not_found=abort_not_found)


def get_samples(**project_filters):
    """
    Returns a list of dicts where each represents summary data of a sample.
    """
    p = get_project(**project_filters)
    return Sample.query.filter_by(_project_id=p.id).all()


def get_project_sample(project_filters, sample_filters, abort_not_found=True):
    # Retrieve the project that is supposed to contain the sample, signalling a
    # 404 if it does not exist.  Although our obfuscated sample IDs are in fact
    # globally unique, we don't want to leak that fact into the API, since it
    # isn't something that clients should assume as guaranteed behaviour.
    # Samples are only valid in the context of a project, and the API should
    # reflect that, even if we model it differently.
    p = get_project(abort_not_found=abort_not_found, **project_filters)
    sample_filters['_project_id'] = p.id
    return get_resource(
        Sample.query.filter_by(**sample_filters),
        abort_not_found=abort_not_found)


def add_sample(project_id, name):
    """
    Adds a new sample.
    """
    p = get_project(obfuscated_id=project_id)
    s = Sample(name=name, project=p)
    with_transaction(db.session, lambda session: session.add(s))
    return Sample.query.filter_by(id=s.id).one()


class Method(db.Model, metaclass=ResourceMetaClass):
    __tablename__ = 'method'
    __hashidgen__ = HashIds('Method')

    name = Column(String(80), unique=True)
    description = Column(String(80), unique=False)

    # objects forward-related to method
    sample_stages = relationship(
        'SampleStage', backref='method', lazy='dynamic')


def get_methods():
    """
    Returns a list of dicts, where each contains summary information about a
    method.
    """
    try:
        methods = Method.query.all()
    except OperationalError:
        return ''
    return methods


def get_method(abort_not_found=True, **filters):
    return get_resource(Method.query.filter_by(**filters), abort_not_found)


def add_method(name, description):
    """Adds a new method."""
    try:
        _ = Method.query.first()
    except OperationalError:
        db.create_all()
    m = Method(name=name, description=description)
    with_transaction(db.session, lambda session: session.add(m))
    return Method.query.filter_by(id=m.id).one()


class SampleStage(db.Model, metaclass=ResourceMetaClass):
    __tablename__ = 'sample_stage'
    __hashidgen__ = HashIds('SampleStage')

    _created_ts = Column("created_ts", TIMESTAMP, server_default=func.now())
    annotation = Column(Text, unique=False)
    alt_id = Column(Integer, unique=False)
    # relationships
    _sample_id = Column('sample_id', Integer, ForeignKey('sample.id'))
    _method_id = Column('method_id', Integer, ForeignKey('method.id'))
    # objects forward-related to sample stage
    sample_stage_files = relationship(
        'SampleStageFile', backref='sample_stage', lazy='dynamic')

    @property
    def sample_id(self):
        return self.sample.obfuscated_id

    @property
    def method_id(self):
        return self.method.obfuscated_id


def _sample_stage_token_hashid():
    return hashids.Hashids(salt='SampleStageToken', min_length=5)


def get_sample_stages(sample_id):
    """
    Returns stages for the designated sample.
    """
    s = get_resource(Sample.query.filter_by(obfuscated_id=sample_id))
    # The order of the stages is significant, since they represent a sequence
    # of events for a sample.  Results should naturally be ordered by the
    # primary key, but it doesn't hurt to make sure.
    stages = SampleStage\
             .query\
             .filter_by(_sample_id=s.id)\
             .order_by(SampleStage.id)\
             .all()
    hashid = _sample_stage_token_hashid()
    if len(stages) == 0:
        token = hashid.encode(0)
    else:
        token = hashid.encode(stages[-1].id)
    return stages, token


def get_sample_stage(sample_id, stage_id):
    """
    Returns a particular stage for a particular sample.
    """
    s = get_resource(Sample.query.filter_by(obfuscated_id=sample_id))
    return get_resource(SampleStage.query.filter_by(_sample_id=s.id))


def add_sample_stage(sample_id, method_id, annotation, token, alt_id=None):
    """
    Adds a new sample stage.  Clients are required to echo the token returned
    by `get_sample_stages()` in order to make requests idempotent and avoid
    adding spurious entries to the DB because of retries, etc.
    """
    s = get_resource(Sample.query.filter_by(obfuscated_id=sample_id))
    m = get_resource(Method.query.filter_by(obfuscated_id=method_id))
    i = _sample_stage_token_hashid().decode(token)[0]

    # Make sure that we have a transaction open.  We need to retrieve the list
    # of stages and insert the new stage in a single transaction for the insert
    # token to be valid.  Without this it is possible for accidental duplicates
    # to be inserted because of race conditions or timeouts.
    db.session.begin(subtransactions=True)

    last_stage = SampleStage\
                 .query\
                 .filter_by(_sample_id=s.id)\
                 .order_by(SampleStage.id.desc()).first()
    if last_stage is None:
        last_stage_id = 0
    else:
        last_stage_id = last_stage.id

    if last_stage_id != i:
        abort(409)
    else:
        ss = SampleStage(annotation=annotation,
                         sample=s,
                         method=m,
                         alt_id=alt_id)
        try:
            with_transaction(db.session, lambda session: session.add(ss))
            db.session.commit()
        except:
            db.session.rollback()
            raise
        return SampleStage.query.filter_by(id=ss.id).one()


class FileStatus(enum.Enum):
    prepared = 'prepared' # An upload directory and ID has been allocated for
                          # the file
    staged   = 'staged'   # Upload processing complete; ready to be moved into
                          # place.
    archived = 'archived' # In correct location, ready to be used/downloaded,
                          # etc.  Upload directory can be cleaned.
    cleaned  = 'cleaned'  # All temporary resources (such as the upload
                          # directory) associated with upload have been
                          # removed.
    complete = 'complete' # No further action is needed for the file.


class SampleStageFile(db.Model, metaclass=ResourceMetaClass):
    __tablename__ = 'sample_stage_file'
    __hashidgen__ = HashIds('SampleStageFile')

    relative_source_path = Column(Text, unique=True)
    relative_target_path = Column(Text, unique=True)
    _status = Column('status', Enum(*list(FileStatus.__members__.keys())))
    # PORTABILITY WARNING: SQLite renders `now` in UTC, which is what we want.
    # This behaviour may not be true for all stores and so may need custom type
    # handling to ensure that timestamps are consistently handled in UTC.
    _created_ts = Column('created_ts', TIMESTAMP, server_default=func.now())
    modified_ts = Column(
        TIMESTAMP,
        server_default=func.now(),
        onupdate=func.current_timestamp())

    # relationships
    _sample_stage_id = Column(
        'sample_stage_id', Integer, ForeignKey('sample_stage.id'))

    @property
    def sample_stage_id(self):
        return self.sample_stage.obfuscated_id

    @hybrid_property
    def status(self):
        return FileStatus(self._status)

    @status.setter
    def status(self, s):
        self._status = s.value

    @status.expression
    def status(cls):
        return cls._status

    # create a sample stage file object
    def __init__(self, relative_upload_name, sample_stage, status=FileStatus.prepared):

        self.sample_stage = sample_stage

        # construct the file path based on project, sample, and method
        method  = sample_stage.method
        sample  = sample_stage.sample
        project = sample.project
        relpath, counter = create_archive_filename(
            app.config['STORE_PATH'],
            ['project-{project_id}'.format(project_id=project.obfuscated_id),
             'sample-{sample_id}'.format(sample_id=sample.obfuscated_id),
             'stage-{stage_id}.method-{method_id}'.format(
                 stage_id=sample_stage.obfuscated_id, method_id=method.obfuscated_id)],
            os.path.basename(relative_upload_name))

        self.relative_source_path = relative_upload_name
        self.relative_target_path = relpath
        self.status = status

    def _file_repr_(self):
        stageid = self.sample_stage.id
        sample  = self.sample_stage.sample
        project = sample.project
        return '{project:}/{sample:}/{stage:}/{fname:}'.format(
            stage=stageid,
            project=project.name,
            sample=sample.name,
            fname=os.path.basename(self.relative_target_path))

    def __repr__(self):
        return '<Sample Stage File {id:}: ' \
               '{file:} ({relpath:}), status={stat:}>'.format(
                   id=self.id,
                   file=self._file_repr_(),
                   relpath=self.relative_target_path,
                   stat=self.status)

    def mark_archived(self):
        self.status = FileStatus.archived
        return with_transaction(db.session, lambda session: session.add(self))

    def mark_cleaned(self):
        # Today, cleaning is the last step in the proces, so we jump straight
        # to `complete`.
        self.status = FileStatus.complete
        return with_transaction(db.session, lambda session: session.add(self))

def inject_filename_counter(fname, counterval, maxextlen=6):
    """
    This function injects this counter value into the filename while attempting
    to preserve its extension (as broken a mechanism as that is for managing
    file types).  Extensions are assumed to start with a period and be no
    longer than 6 characters (a somewhat arbitrarily selected value).
    """
    cvstr = '%05d' % counterval
    parts = fname.split('.')
    def isext(part):
        return (len(part) <= maxextlen) or (part.startswith('container-'))
    if (len(parts) == 1) or (not isext(parts[-1])):
        return '%s-%s' % (fname, cvstr)
    else:
        return '%s-%s.%s' % ('.'.join(parts[:-1]), cvstr, parts[-1])


def create_archive_filename(root, pathels, fname):
    """
    To maintain the immutability of the archive fileset, we don't allow
    datafiles to be overwritten.  We assume that if a file is uploaded with the
    same name as one already present, that it is a new version of that file.
    This function attempts to generate a unique, versioned, name for the file.
    """
    counter = 0
    partialpath = os.path.join(*pathels)
    while True:
        basename = inject_filename_counter(fname, counter)
        relpath = os.path.join(partialpath, basename)
        if os.path.exists(os.path.join(root, relpath)):
            counter += 1
        else:
            return (relpath, counter)


def get_files(sample_stage_id=None, status=FileStatus.complete):

    """
    Returns a list of dicts where each represents a file that belongs to a
    sample stage.
    """
    stage_file_q = SampleStageFile.query
    filters = {}
    if sample_stage_id is not None:
        sample_stage = get_resource(SampleStage.query.filter_by(obfuscated_id=sample_stage_id))
        filters['_sample_stage_id'] = sample_stage.id
    if status is not None:
        filters['status'] = status.value
    return stage_file_q.filter_by(**filters).all()


def add_file(source_fname, sample_stage_id):
    """
    Adds a new file to the sample stage.
    """
    ssq = SampleStage.query.filter_by(obfuscated_id=sample_stage_id)
    ss  = get_resource(ssq)

    # Note that we intentionally add the file as incomplete.  We leave the
    # completion of this process to a sweeper.
    ssf = SampleStageFile(source_fname, ss, status=FileStatus.staged)
    with_transaction(db.session, lambda session: session.add(ssf))

    return get_resource(SampleStageFile.query.filter_by(id=ssf.id))
