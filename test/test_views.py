
import pytest

from sqlalchemy import Column, Integer

from app.models import Method, Project, Sample, SampleStage
from app.models import db
from app.views  import jsonize
from .utils      import decode_json_string

from .fixtures   import json_encoder


def test_dictify(json_encoder):
    p = Project(id=1, obfuscated_id='5QMVv', name='project', sample_mask='###')
    assert {'id'            : 1,
            'obfuscated-id' : '5QMVv',
            'name'          : 'project',
            'sample-mask'   : '###'} \
            == json_encoder._dictify(p)


def test_dictify_exclusions(json_encoder):
    p = Project(id=1, obfuscated_id='5QMVv', name='project', sample_mask='###')
    assert {'obfuscated-id' : '5QMVv',
            'sample-mask'   : '###'} \
            == json_encoder._dictify(p, {'id', 'name'})


def test_uri_name(json_encoder):
    spec = {'foobar'    : 'foobar',
            'fooBar'    : 'foobar',
            'foo bar'   : 'foo-bar',
            'f o o'     : 'f-o-o',
            'foo   bar' : 'foo-bar',
            'foo ~ bar' : 'foo-bar'}
    for kv in iter(list(spec.items())):
        assert kv[1] == json_encoder._uri_name('FoOby', kv[0]).split('-', 1)[1]
