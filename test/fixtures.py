
import os
import pytest
import shutil
import tempfile

import app         as sagittariidae
import app.models  as models
import app.views   as views


@pytest.fixture(scope='function')
def ws(request):
    flask_app = sagittariidae.app.app
    # Yuck!  Reeeally have to fix the app name!

    fd, fn = tempfile.mkstemp()
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + fn
    flask_app.config['TESTING'] = True
    client = flask_app.test_client()
    with flask_app.app_context():
        models.db.create_all()
        # pass

    yield client

    os.close(fd)
    os.unlink(fn)

    # def fin():
    #     os.close(fd)
    #     os.unlink(fn)
    # request.addfinalizer(fin)
    # return inst


@pytest.fixture(scope='function')
def sample(ws):
    project = models.add_project(name='Manhattan', sample_mask='man-###')
    sample = models.add_sample(project_id='PqrX9', name='sample 1')
    method = models.add_method(name='X-ray tomography', description='Placeholder description.')
    return {'app'     : ws,
            'project' : project,
            'sample'  : sample,
            'method'  : method}


@pytest.fixture(scope='module')
def json_encoder(request):
    return views.DBModelJSONEncoder()


@pytest.fixture(scope='function')
def sample_with_stages(sample):
    hashid = models._sample_stage_token_hashid()
    token1 = hashid.encode(0)
    stage1 = models.add_sample_stage(sample_id=sample['sample'].obfuscated_id,
                                     method_id=sample['method'].obfuscated_id,
                                     annotation='Annotation 0',
                                     token=token1)
    token2 = hashid.encode(1)
    stage2 = models.add_sample_stage(sample_id=sample['sample'].obfuscated_id,
                                     method_id=sample['method'].obfuscated_id,
                                     annotation='Annotation 1',
                                     token=token2)
    sample.update({'stages': [stage1, stage2]})
    return sample


@pytest.fixture(scope='function')
def tmpdir(request):
    dirname = tempfile.mkdtemp()

    def teardown():
        shutil.rmtree(dirname)
    request.addfinalizer(teardown)

    return dirname


@pytest.fixture(scope='function')
def storepath(request, tmpdir):
    config = sagittariidae.app.app.config
    configured_store_dir = config['STORE_PATH']
    configured_upload_dir = config['UPLOAD_PATH']

    def teardown():
        config['STORE_PATH'] = configured_store_dir
        config['UPLOAD_PATH'] = configured_upload_dir
    request.addfinalizer(teardown)

    config['STORE_PATH'] = tmpdir
    config['UPLOAD_PATH'] = os.path.join(tmpdir, 'upload')
    return tmpdir
