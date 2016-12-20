# Sagittariidae development

## Setup

It is good Python development practice to set up a virtual environment.  This
will allow you to manage Sagittariidae's dependencies independently of other
Python projcts and so avoid versioning conflicts.  We recommend [Conda], but
[virtualenv] is also a popular option.

Having set up and activated a virtual environment for Sagittariidae, install
the required packages:
```
$ pip install -r requirements.txt
```

## Testing
Configure the application for local development and testing:

```
$ export FLASK_APP=app/app.py # Tell Flask what the main application file is
$ export FLASK_TESTING=1 # Configure local log and DB.
```

To run the tests and get a nice report:

```
$ py.test
```

Or, to get more helpful output during development:

```
$ py.test --quiet --capture=no --tb=short
```
where:

* `--quiet`: less verbose/pretty reporting
* `--capture=no`: do not capture STDOUT and STDERR
* `--tb=short`: don't overwhelm me with exception traces

`py.test -h` for more details.

Please extend test coverage to any new functionality that you add and make sure
that the tests are all green before checking in changes.

## Development server

[Flask] (the micro-webservice upon which Sagittariidae is built) provides a
script to launch a development server and reload code as changes are made.
Some [simple configuration][devserver] is required:

```
$ export FLASK_APP=app/app.py
$ export FLASK_DEBUG=1
$ flask run
```

[Conda]: http://conda.pydata.org/docs/index.html#
[virtualenv]: http://docs.python-guide.org/en/latest/dev/virtualenvs/
[Flask]: http://flask.pocoo.org/docs/0.11/
[devserver]: http://flask.pocoo.org/docs/0.11/server/#server
