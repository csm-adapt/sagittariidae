
import logging
import time

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.shared_data import SharedDataMiddleware

from config import STATIC_ROOT, STORE_PATH

app = Flask(__name__)
db = SQLAlchemy(app)

app.config.from_object('config')
isdevmode = app.config['TESTING'] or app.config['DEBUG']

app.wsgi_app = SharedDataMiddleware(
    app.wsgi_app,
    {'/'   : STATIC_ROOT,
     '/dl' : STORE_PATH})

# Please use a sane timezone for log entries so that we don't have to jump
# through daylight savings hoops.
logging.Formatter.converter = time.gmtime
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(threadName)s,%(module)s,l%(lineno)d : %(message)s')

# Set up the level at which we want to log
if isdevmode:
    loglevel = logging.DEBUG
else:
    loglevel = logging.INFO

loggers = {app.logger                      : None,
           logging.getLogger('werkzeug')   : logging.INFO,
           logging.getLogger('sqlalchemy') : logging.WARN}
handlers = []

# Set up the log handlers.
if isdevmode:
    log_file = 'sagittariidae.log'
    cons_log = logging.StreamHandler()
    handlers.append(cons_log)
else:
    # When in production, log to a file in the system log dir.
    # TODO: Add a `logrotate` cron job to manage the log file.
    log_file = '/var/log/sagittariidae.log'

file_log = logging.FileHandler(log_file)
handlers.append(file_log)

# Assign handlers to loggers and set them all at the appropriate level
for handler in handlers:
    handler.setLevel(loglevel)
    handler.setFormatter(formatter)

    for logger, defined_level in loggers.items():
        if defined_level is None:
            logger.setLevel(loglevel)
        else:
            logger.setLevel(defined_level)
        logger.addHandler(handler)

try:
    logger.info('Sagittariidae is starting ...')

    # Load "leaf" modules.  These may depend only on `app.app` which has now
    # been initialised
    from . import models

    # Lead "middleware" modules.  These may depend on both leaf modules and on
    # `app.app`.
    from . import sampleresolver
    from . import views

    # And we're done
    logger.info('Sagittariidae is ready to serve.')
except Exception as e:
    logger.error('Startup error', exc_info=e)
    import sys
    sys.exit(1)
