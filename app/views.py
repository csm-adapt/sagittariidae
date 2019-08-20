
import io
import glob
import hashlib
import json
import math
import os
import re

from flask          import abort, jsonify, redirect, request
from werkzeug.utils import secure_filename
from urllib.parse         import quote

from . import checksum
from . import file
from . import http

from .app            import app, db, models
from .sampleresolver import SampleResolver


PART_EXT = "part"
CHECKSUM_EXT = "checksum"

# ------------------------------------------------------------ api routes --- #

@app.route('/')
def index():
    return redirect('/index.html', http.HTTP_302_FOUND)


@app.route('/projects', methods=['GET'])
def get_projects():
    return jsonize(models.get_projects())


@app.route('/projects/<project>', methods=['GET'])
def get_project(project):
    return jsonize(models.get_project(obfuscated_id=as_id(project)))


@app.route('/projects/<project>/samples', methods=['GET'])
def get_project_samples(project):
    # Allow clients to search for a sample rather than having to retrieve all
    # of the samples for a project (even if the latter is arguably the more
    # RESTful approach).  This enables a URL of the form:
    #
    #   http://.../projects/qwErt/samples?q=P001-B009-...
    #
    # In the absence of the query parameter we simply return the entire
    # collection.
    # FIXME: This should support pagination!
    search_terms = request.args.get('q')
    project_id   = as_id(project)
    if search_terms is not None:
        return jsonize(
            SampleResolver().resolve(search_terms.split(' '), project_id))
    else:
        return jsonize(
            models.get_samples(obfuscated_id=as_id(project_id)))


@app.route('/projects/<project>/samples/<sample>', methods=['GET'])
def get_project_sample(project, sample):
    return jsonize(
        models.get_project_sample(
            {'obfuscated_id': as_id(project)},
            {'obfuscated_id': as_id(sample)}))


@app.route('/projects/<_>/samples/<sample>/stages', methods=['GET'])
def get_project_sample_stages(_, sample):
    (stages, token) = models.get_sample_stages(as_id(sample))
    return jsonize({'sample' : sample,
                    'stages' : stages,
                    'token'  : token})


@app.route('/projects/<_>/samples/<sample>/stages/<stage>', methods=['GET'])
def get_project_sample_stage(_, sample, stage):
    return jsonize(models.get_sample_stages(as_id(sample), as_id(stage)))


@app.route('/projects/<project>/samples/<sample>/stages/<stage>', methods=['PUT'])
def put_project_sample_stage(project, sample, stage):
    method = models.get_method(obfuscated_id=as_id(request.json['method']))
    annotation = request.json['annotation']
    token = stage
    rsp = jsonize(
        models.add_sample_stage(
            as_id(sample), as_id(method.obfuscated_id), annotation, token))
    return (rsp, http.HTTP_201_CREATED)


@app.route('/projects/<project>/samples/<sample>/stages/<stage>/files', methods=['GET'])
def get_sample_stage_files(project, sample, stage):
    return jsonize({'stage-id' : stage,
                    'files'    : models.get_files(sample_stage_id=as_id(stage), status=None)})


@app.route('/methods', methods=['GET'])
def get_methods():
    return jsonize(models.get_methods())


@app.route('/methods/<method>', methods=['GET'])
def get_method(method):
    return jsonize(models.get_method(obfuscated_id=as_id(method)))


@app.route('/prepare-multipart-upload', methods=['POST'])
def prepare_file_upload():
    pass


@app.route('/upload-part', methods=['POST'])
def upload_file():
    part = request.files['file']

    # part_number = request.form['part-number']
    part_number = request.form['resumableChunkNumber']
    # total_number_parts = request.form['total-parts']
    total_number_parts = request.form['resumableTotalChunks']

    # file_identifier = request.form['upload-id']
    file_identifier = request.form['resumableIdentifier']
    part_upload_dir = upload_dir(file_identifier)
    mkdirp(part_upload_dir)

    # Save the part into a file with a name of the form 00.part.  The number of
    # leading zeroes depends on the number of parts.
    fmtstr = "%%0%dd" % len(total_number_parts)
    part_filename = '.'.join([(fmtstr % int(part_number)), PART_EXT])
    part_filepath = os.path.join(part_upload_dir, part_filename)
    part.save(part_filepath)

    return json.dumps(
        {'identifier': file_identifier,
         'part': part_number,
         'total_parts': total_number_parts})


@app.route('/complete-multipart-upload', methods=['POST'])
def complete_file_upload():
    request_data    = json.loads(request.data)
    file_identifier = request_data['upload-id']
    file_name       = secure_filename(request_data['file-name'])
    project         = request_data['project']
    sample          = request_data['sample']
    sample_stage    = as_id(request_data['sample-stage'])

    req_checksum_value  = request_data['checksum-value']
    req_checksum_method = request_data['checksum-method']

    part_upload_dir = upload_dir(file_identifier)
    reconstituted_file_name = os.path.join(part_upload_dir, file_name)
    parts = sorted(glob.glob(os.path.join(part_upload_dir, '*.part')))

    part_digester = checksum.get_digester(req_checksum_method)
    with open(reconstituted_file_name, 'w') as target:
        def consume_part(data):
            target.write(data)
            part_digester.update(data)
        for part_name in parts:
            file.FileProcessor(part_name, consume_part).process()
    computed_checksum_value = part_digester.hexdigest()
    if computed_checksum_value != req_checksum_value:
        raise checksum.ChecksumMismatch(
            reconstituted_file_name,
            req_checksum_method,
            req_checksum_value,
            computed_checksum_value)

    with open('.'.join([reconstituted_file_name, CHECKSUM_EXT]), 'w') as cf:
        json.dump({'method': req_checksum_method,
                   'value' : req_checksum_value},
                  cf)

    logmsg = 'Successfully reconsitituted file: %s (%s=%s)' \
             % (reconstituted_file_name, req_checksum_method, req_checksum_value)
    app.logger.info(logmsg)
    models.add_file(
        os.path.relpath(
            reconstituted_file_name, app.config['UPLOAD_PATH']),
        sample_stage)

    return (json.dumps({'identifier' : file_identifier,
                        'file-name'  : file_name}),
            http.HTTP_202_ACCEPTED)

# -------------------------------------------------------- error handlers --- #

@app.errorhandler(checksum.ChecksumError)
def handle_unsupported_checksum_method(e):
    app.logger.error('Checksum error: %s' % e, exc_info=e)
    return (json.dumps({'status_code': e.status_code,
                        'message'    : e.message}),
            e.status_code)


@app.errorhandler(Exception)
def handle_unhandled_exception(e):
    app.logger.error('Unhandled exception: %s' % e, exc_info=e)
    raise e

# ------------------------------------------------------ data marshalling --- #

def as_id(resource_name):
    return resource_name.split('-')[0]


class DBModelJSONEncoder(json.JSONEncoder):

    BAD_URI_PAT  = re.compile("%.{2}|\/|_")
    COLLAPSE_PAT = re.compile("-{2,}")

    def __init__(self, **kw):
        super(DBModelJSONEncoder, self).__init__(**kw)

        # This is a terrible hack to make it possible to add context to the
        # stages IDs.  The relative ordering of stages is important, and from
        # this we infer the ordinal position values.  Note this that assumes
        # that a new encoder instance is used for each JSON document; do not
        # cache encoders!
        self.sample_stage_count = 0

    def _uri_name(self, obfuscated_id, name):
        """
        Convert the name of a resource (like a project or sample) into a
        URI-friendly form.  This function has strong opinions about what a
        "good" URI ID is, and will complain if the ID cannot be rendered in
        an acceptable form.  In particular, it should not contain any
        characters that need to be escaped; cf. `urllib.quote()`.
        """
        assert obfuscated_id is not None
        assert name is not None
        # URI-escape special characters
        new_name = quote(name.lower().replace(" ", "-"))
        # Convert escapes into underscores; i.e. foo%20bar -> foo-bar
        new_name = re.sub(self.BAD_URI_PAT, '-', new_name)
        # Collapse multiple consecutive hyphens; i.e. foo---bar -> foo-bar
        new_name = re.sub(self.COLLAPSE_PAT, '-', new_name)
        # concat with the ID and return
        return '-'.join([obfuscated_id, new_name])

    def _dictify(self, model, exclude={}):
        """
        Return a model as a dictionary. 'Private' attributes are removed and
        underscores are replaced with more hyphens in attribute names, making
        for more aesthetically pleasing HTTP data maps.
        """
        def tr(kv):
            return (kv[0].replace('_', '-'), kv[1])
        return dict(tr(kv) for kv in iter(list(model.__dict__.items()))
                    if (not (kv[0].startswith('_') or (kv[0] in exclude))))

    def strip_private_fields(self, d):
        del d['obfuscated-id']
        return d

    def _encodeProject(self, p):
        d = self._dictify(p)
        d['id'] = self._uri_name(d['obfuscated-id'], d['name'])
        return self.strip_private_fields(d)

    def _encodeMethod(self, m):
        d = self._dictify(m)
        d['id'] = self._uri_name(d['obfuscated-id'], d['name'])
        return self.strip_private_fields(d)

    def _encodeSample(self, s):
        d = self._dictify(s, {'project'})
        d['id'] = self._uri_name(d['obfuscated-id'], d['name'])
        d['project'] = self._uri_name(s.project.obfuscated_id, s.project.name)
        return self.strip_private_fields(d)

    def _encodeSampleStage(self, ss):
        d = self._dictify(ss, {'sample', 'method'})
        self.sample_stage_count += 1
        d['id'] = self._uri_name(d['obfuscated-id'], str(self.sample_stage_count))
        d['sample'] = self._uri_name(ss.sample.obfuscated_id, ss.sample.name)
        d['method'] = self._uri_name(ss.method.obfuscated_id, ss.method.name)
        return self.strip_private_fields(d)

    def _encodeSampleStageFile(self, ssf):
        def isready(ssf):
            return ssf.status in [models.FileStatus.archived,
                                  models.FileStatus.cleaned,
                                  models.FileStatus.complete]
        if isready(ssf):
            status = 'ready'
        else:
            status = 'processing'
        fname = os.path.basename(ssf.relative_target_path)
        return {'id'           : ssf.obfuscated_id + '-' + fname,
                'file'         : fname,
                'status'       : status,
                'mtime'        : ssf.modified_ts.isoformat(),
                'uri' : '/dl/' + ssf.relative_target_path}

    def _encodeModel(self, m):
        return self.strip_private_fields(self._dictify(m))

    def default(self, thing):
        if isinstance(thing, models.Project):
            return self._encodeProject(thing)
        if isinstance(thing, models.Method):
            return self._encodeMethod(thing)
        if isinstance(thing, models.Sample):
            return self._encodeSample(thing)
        if isinstance(thing, models.SampleStage):
            return self._encodeSampleStage(thing)
        if isinstance(thing, models.SampleStageFile):
            return self._encodeSampleStageFile(thing)
        if isinstance(thing, db.Model):
            return self._encodeModel(thing)


def jsonize(x):
    return json.dumps(x, cls=DBModelJSONEncoder)

# ----------------------------------------------------------- utility fns --- #

def mkdirp(p):
    if os.path.exists(p) and os.path.isdir(p):
        return False
    else:
        os.makedirs(p)
        return True


def upload_dir(p):
    if isinstance(p, str):
        add_path = (p,) # Turn the single element into a tuple that can be
                        # joined into a full path
    elif isinstance(p, (list, tuple)):
        add_path = p
    else:
        msg = 'I Don\'t know how to create an upload directory path from "%s", %s' \
              % (p, type(p))
        raise Exception(msg)
    full_path = (app.config['UPLOAD_PATH'],) + add_path
    return os.path.join(*full_path)


def hashfile(fn, hasher, blocksize=65536):
    with open(fn, 'rb') as afile:
        buf = afile.read(blocksize)
        while len(buf) > 0:
            hasher.update(buf)
            buf = afile.read(blocksize)
    return hasher.hexdigest()


def hashstring(s, hasher):
    hasher.update(s)
    return hasher.hexdigest()
