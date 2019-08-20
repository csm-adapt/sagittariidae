
import sys
import werkzeug.http

def _define_status_code_constants():
    """
    Neither Flask nor Werkzeug provide constants for HTTP status codes, but
    Werkzeug does have a map of status codes to descriptions.  We use this to
    dynamically generate constants of our own that we can, making our own code
    more readable and self-documenting.
    """
    # cf. https://github.com/pallets/werkzeug/blob/06972c37170af14b7e88c7c325b3dec01efefa04/werkzeug/http.py#L84
    for k,v in werkzeug.http.HTTP_STATUS_CODES.items():
        status_code = k
        status_string = '_'.join(['HTTP',
                                  str(status_code),
                                  v.upper().replace(' ', '_')])
        setattr(sys.modules[__name__], status_string, status_code)

_define_status_code_constants()
