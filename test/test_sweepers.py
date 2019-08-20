
import os
import pytest
import random

import app          as sagittariidae
import app.models   as models
import app.sweepers as sweepers

from app.file import touch
from .fixtures import *


@pytest.fixture(scope='function')
def stage_file(storepath, sample_with_stages):
    parts_dir = ''.join([random.choice('0123456789ABCDEF') for i in range(3)])
    ssf = models.add_file(
        os.path.join(parts_dir, 'uploaded-file'),
        sample_with_stages['stages'][0].obfuscated_id)
    src_fname = os.path.join(
        sagittariidae.app.app.config['UPLOAD_PATH'],
        ssf.relative_source_path)
    tgt_fname = os.path.join(
        sagittariidae.app.app.config['STORE_PATH'], ssf.relative_target_path)
    return {'model'  : ssf,
            'source' : src_fname,
            'target' : tgt_fname}


def test_StagedFileSweeper_move_file(sample_with_stages, stage_file):
    touch(stage_file['source'])
    stage = sample_with_stages['stages'][0]

    # Sanity checks to make sure that the world is in a valid starting, and not
    # accidentally already the state into which we want it set.
    assert os.path.isfile(stage_file['source']), "Source file is missing."
    assert not os.path.isfile(stage_file['target']), "Target file found; unexpected."
    exp_status = models.FileStatus.staged
    act_status = models.get_files(
        sample_stage_id=stage.obfuscated_id, status=exp_status)[0].status
    assert exp_status == act_status

    # Be the change you want to see.
    sweepers.make_sweeper(sweepers.StagedFileSweeper).sweep()

    # Validate the world has become a better place.  (If only it were that easy
    # IRL.)
    assert os.path.isfile(stage_file['target']), "Target file not created."
    exp_status = models.FileStatus.archived
    act_status = models.get_files(
        sample_stage_id=stage.obfuscated_id, status=exp_status)[0].status
    assert exp_status == act_status


def test_ArchivedFileDirSweeper_delete_dirs(sample_with_stages, stage_file):
    filepath = stage_file['source']
    dirpath = os.path.dirname(filepath)
    touch(filepath)
    os.remove(filepath)

    stage_file['model'].mark_archived()
    stage = sample_with_stages['stages'][0]

    # Sanity checks to make sure that the world is in a valid starting, and not
    # accidentally already the state into which we want it set.
    assert (not os.path.isfile(filepath)), "Source file is present."
    assert os.path.isdir(dirpath), "Source parent dir is not present"
    exp_status = models.FileStatus.archived
    act_status  = models.get_files(
        sample_stage_id=stage.obfuscated_id, status=exp_status)[0].status
    assert exp_status == act_status

    sweepers.make_sweeper(sweepers.ArchivedFileDirSweeper).sweep()
    assert (not os.path.exists(dirpath)), "Upload directory not removed"

    exp_status = models.FileStatus.complete
    act_status  = models.get_files(
        sample_stage_id=stage.obfuscated_id, status=exp_status)[0].status
    assert exp_status == act_status
    assert os.path.exists(os.path.dirname(dirpath)), "Parent of upload directory removed; this is a Bad Thing (tm)!"
