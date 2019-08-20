
import hashlib

from . import file
from . import http


DIGESTERS = {'sha256': lambda: hashlib.sha256() }


class ChecksumError(Exception):
    status_code = http.HTTP_422_UNPROCESSABLE_ENTITY


class UnsupportedChecksumMethod(ChecksumError):
    def __init__(self, method):
        self.method  = method
        self.message = 'The checksum method "%s" is not supported; use one of: %s' % (method, list(DIGESTERS.keys()))
    def __str__(self):
        return self.message


class ChecksumMismatch(ChecksumError):
    def __init__(self, f, method, received, computed):
        self.file     = f
        self.method   = method
        self.received = received
        self.computed = computed
        self.message  = 'Checksum mismatch for %s using method %s; received=%s, computed=%s' % (f, method, received, computed)
    def __str__(self):
        return self.message


def get_digester(method):
    """
    Retrieve a digester that implements the checksum `method`.  Returns an
    instance of a hashlib digester.
    """
    digesterfn = DIGESTERS.get(method, None)
    if digesterfn is None:
        raise UnsupportedChecksumMethod(method)
    else:
        return digesterfn()


def generate_checksum(f, method):
    """
    A convenience function to produce a checksum for an entire file.
    Returns the digest as a hex-encoded string.
    """
    digester = get_digester(method)
    file.FileProcessor(f, lambda data: digester.update(data)).process()
    return digester.hexdigest()


def validate_checksum(f, method, received):
    """
    A convenience method to generate and validate a checksum for an entire
    file. Raises a `ChecksumMismatch` exception if the `received` and generated
    checksums do not match.
    Always returns `None`.
    """
    computed = generate_checksum(f, method)
    if computed != received:
        raise ChecksumMismatch(f, method, received, computed)
