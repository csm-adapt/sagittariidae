
"""
This module contains the definitions of Sagittariidae's sweeper processes.
These are asynchronous processes that designed to drive the current state of
the world to a desired final state.

The sweepers are run as processes separate from the webservice.  They may be
invoked by name by executing this module, typically from a scheduler such as
`cron`.
"""

import os
import shutil
import sys

from . import app as sagittariidae
from . import models


logger = sagittariidae.app.logger

class Sweeper(object):

    def run(self):
        raise NotImplementedError()

    def sweep(self):
        try:
            self.run()
        except Exception as e:
            logger.error('Unhandled exception in sweeper %s', self, exc_info=e)


class ArchivedFileDirSweeper(Sweeper):

    def _clean_(self, ssf, logger):
        config   = sagittariidae.app.config
        src_path = os.path.join(config['UPLOAD_PATH'], ssf.relative_source_path)
        src_dir  = os.path.dirname(src_path)
        if os.path.exists(src_dir):
            logger.info('Removing upload directory: %s' % src_dir)
            shutil.rmtree(src_dir)
        else:
            logger.warning('Upload directory doesn\'t exist: %s' % src_dir)
        # FIXIT: Handle the OperationalError that may result if the database is
        # locked.  It's not a critical failure, but spurious ERROR messages in
        # the log is never nice.
        ssf.mark_cleaned()

    def run(self):
        logger = sagittariidae.app.logger

        files = models.get_files(
            sample_stage_id=None,
            status=models.FileStatus.archived)
        logger.info('Found upload director{y,ies} for %d files(s) that are ready to be cleaned: %s', len(files), files)
        for f in files:
            try:
                self._clean_(f, logger)
            except Exception as e:
                logger.error('Error cleaning upload directory for file %s', f, exc_info=e)


class StagedFileSweeper(Sweeper):

    def _complete_(self, ssf):
        config   = sagittariidae.app.config
        src_path = os.path.join(config['UPLOAD_PATH'], ssf.relative_source_path)
        tgt_path = os.path.join(config['STORE_PATH'], ssf.relative_target_path)
        tgt_dir  = os.path.dirname(tgt_path)
        if not os.path.isdir(tgt_dir):
            os.makedirs(tgt_dir)
        shutil.copy(src_path, tgt_path)
        logger.info('Copied file: %s -> %s', src_path, tgt_path)
        ssf.mark_archived()

    def run(self):
        logger = sagittariidae.app.logger

        files = models.get_files(
            sample_stage_id=None,
            status=models.FileStatus.staged)
        logger.info('Found %d file(s) that are ready to be moved into place: %s', len(files), files)
        for f in files:
            try:
                self._complete_(f)
            except Exception as e:
                logger.error('Error moving file %s', f, exc_info=e)


def make_sweeper(c):
    try:
        if c == Sweeper:
            raise Exception('Not a sweeper impl %s' % c)
        i = c()
        if not isinstance(i, Sweeper):
            raise Exception('%s is not an implementation of %s' % (c, Sweeper))
        else:
            return i
    except Exception as e:
        logger.error('Invalid sweeper class %s', sys.argv[1], exc_info=e)
        raise e


if __name__ == '__main__':
    make_sweeper(globals().get(sys.argv[1])).sweep()
