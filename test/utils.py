
from io import StringIO
import json


def decode_json_string(s):
    return json.load(StringIO(s.decode('utf-8')))
