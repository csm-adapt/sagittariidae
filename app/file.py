import os

def exists(name):
    return os.access(name, os.F_OK)

def isfile(name):
    return os.path.isfile(name)

def isdir(name):
    return os.path.isdir(name)

def isreadable(name):
    if isdir(name):
        return os.access(name, os.R_OK & os.X_OK)
    else:
        return exists(name) and os.access(name, os.R_OK)

def iswritable(name):
    # why? if NAME is a filename in the current directory,
    # then os.path.split(name) returns ('', NAME). This way
    # iswritable(os.path.split(filename)[0]) will always work.
    name = '.' if name == '' else name
    if isdir(name):
        # is the directory accessible and writable?
        return os.access(name, os.W_OK & os.X_OK)
    elif isfile(name):
        # if name is a file, is it writable?
        return os.access(name, os.W_OK)
    else:
        # if not, would name create a new file in
        # an accessible directory?
        return iswritable(os.path.split(name)[0])

def touch(name, dirmode=0o777):
    os.makedirs(os.path.dirname(name), dirmode)
    open(name, 'wa').close()

class FileProcessor(object):
    DEFAULT_READ_BLOCKSIZE = 65536

    def __init__(self, fpath, fn, read_blocksize=DEFAULT_READ_BLOCKSIZE):
        self.fpath = fpath
        self.fn = fn
        self.blocksize = read_blocksize

    def process(self):
        with open(self.fpath, 'r') as f:
            buf = f.read(self.blocksize)
            while len(buf) > 0:
                self.fn(buf)
                buf = f.read(self.blocksize)
