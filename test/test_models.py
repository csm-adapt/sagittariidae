
import os
import pytest
import werkzeug

import app
import app.models as models

from app.file import touch
from .fixtures import *


def test_add_project(ws):
    m = models.add_project('Manhattan', 'man-###')
    assert 1 == m.id
    assert 'PqrX9' == m.obfuscated_id
    assert 'Manhattan' == m.name
    assert 'man-###' == m.sample_mask


def test_add_method(ws):
    m = models.add_method(name='X-ray tomography',
                          description='Placeholder description.')
    assert 1 == m.id
    assert 'XZOQ0' == m.obfuscated_id
    assert 'X-ray tomography' == m.name
    assert 'Placeholder description.' == m.description


def test_add_sample(ws):
    models.add_project(name='Manhattan', sample_mask='man-###')
    m = models.add_sample(project_id='PqrX9', name='sample 1')
    assert 1 == m.id
    assert 'OQn6Q' == m.obfuscated_id
    assert 'sample 1' == m.name
    assert 1 == m._project_id
    assert 'PqrX9' == m.project_id


def test_add_sample_stage(ws):
    models.add_project(name='Manhattan', sample_mask='man-###')
    models.add_sample(project_id='PqrX9', name='sample 1')
    models.add_method(name='X-ray tomography', description='Placeholder description.')
    t = models._sample_stage_token_hashid().encode(0)
    m = models.add_sample_stage(
        sample_id='OQn6Q', method_id='XZOQ0', token=t, annotation='Annotation')
    assert 1 == m.id
    assert 'Drn1Q' == m.obfuscated_id
    assert None == m.alt_id
    assert 'Annotation' == m.annotation
    assert 1 == m._sample_id
    assert 'OQn6Q' == m.sample_id
    assert 1 == m._method_id
    assert 'XZOQ0' == m.method_id


def test_get_no_sample_stages(sample):
    s = sample['sample']
    (stages, token) = models.get_sample_stages(s.obfuscated_id)
    assert 0 == len(stages)
    assert models._sample_stage_token_hashid().encode(0) == token


def test_add_new_stage(sample_with_stages):
    s = sample_with_stages['sample']
    m = sample_with_stages['method']
    h = models._sample_stage_token_hashid()

    # Pre-validate that we have the expected number of stages to start with.
    (stages, token) = models.get_sample_stages(s.obfuscated_id)
    assert 2 == len(stages)
    assert h.encode(2) == token

    # Now add the new stage, using the correct ID.
    models.add_sample_stage(s.obfuscated_id, m.obfuscated_id, None, token)

    # Validate that the record has been added to the DB.
    (stages, token) = models.get_sample_stages(s.obfuscated_id)
    assert 2+1 == len(stages)
    assert h.encode(2+1) == token


def test_add_stage_too_far_ahead(sample_with_stages):
    s = sample_with_stages['sample']
    m = sample_with_stages['method']
    h = models._sample_stage_token_hashid()

    # Pre-validate that we have the expected number of stages to start with.
    (stages, token) = models.get_sample_stages(s.obfuscated_id)
    assert 2 == len(stages)
    assert h.encode(2) == token

    # Now add the new stage, using the existing ID and incorrect token
    t = h.encode(999)
    with pytest.raises(werkzeug.exceptions.Conflict) as conflict:
        models.add_sample_stage(s.obfuscated_id, m.obfuscated_id, None, t)

    # Validate that NO record has been added to the DB.
    (stages, token) = models.get_sample_stages(s.obfuscated_id)
    assert 2 == len(stages)
    assert h.encode(2) == token


def test_inject_filename_counter():
    assert 'fname-00003' == \
        models.inject_filename_counter('fname', 3)
    assert 'weird.filename-00003' == \
        models.inject_filename_counter('weird.filename', 3)
    assert 'filename-00003.ext' == \
        models.inject_filename_counter('filename.ext', 3)
    assert 'this.is.a.file.of.type-00003.txt' == \
        models.inject_filename_counter('this.is.a.file.of.type.txt', 3)
    assert 'samplename-00003.container-contentlabel' == \
        models.inject_filename_counter('samplename.container-contentlabel', 3)


def test_create_first_stage_file(storepath, sample_with_stages):
    stage = sample_with_stages['stages'][0]
    ssf = models.SampleStageFile('source-file', stage)
    assert '/'.join(['project-PqrX9',
                     'sample-OQn6Q',
                     'stage-Drn1Q.method-XZOQ0',
                     'source-file-00000']) == ssf.relative_target_path


def test_create_stage_file_for_second_stage(storepath, sample_with_stages):
    stage = sample_with_stages['stages'][1]
    ssf = models.SampleStageFile('source-file', stage)
    assert '/'.join(['project-PqrX9',
                     'sample-OQn6Q',
                     'stage-bQ8bm.method-XZOQ0',
                     'source-file-00000']) == ssf.relative_target_path


def test_create_next_stage_file(storepath, sample_with_stages):
    stage = sample_with_stages['stages'][0]
    ssf1 = models.SampleStageFile('source-file', stage)
    fn1 = os.path.join(storepath, ssf1.relative_target_path)
    touch(fn1)
    ssf2 = models.SampleStageFile('source-file', stage)
    assert '/'.join(['project-PqrX9',
                     'sample-OQn6Q',
                     'stage-Drn1Q.method-XZOQ0',
                     'source-file-00001']) == ssf2.relative_target_path


def test_add_file(storepath, sample_with_stages):
    ssf = models.add_file('source-file', sample_with_stages['stages'][0].obfuscated_id)
    assert 1 == ssf.id
    assert 'w4Kbn' == ssf.obfuscated_id
    assert models.FileStatus.staged == ssf.status
    assert models.FileStatus.staged.value == ssf._status
    assert sample_with_stages['stages'][0].id == ssf._sample_stage_id


def test_complete_file(sample_with_stages):
    ssf = models.add_file('source-file', sample_with_stages['stages'][0].obfuscated_id)
    assert models.FileStatus.staged == ssf.status
