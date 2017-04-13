# Anymail test utils
import sys
from distutils.util import strtobool

import os
import re
import warnings
from base64 import b64decode
from contextlib import contextmanager

from django.test import Client


def envbool(var, default=False):
    """Returns value of environment variable var as a bool, or default if not set.

    Converts `'true'` to `True`, and `'false'` to `False`.
    See :func:`~distutils.util.strtobool` for full list of allowable values.
    """
    val = os.getenv(var, None)
    if val is None:
        return default
    else:
        return strtobool(val)


# RUN_LIVE_TESTS: whether to run live API integration tests.
# True by default, except in CONTINUOUS_INTEGRATION job.
# (See comments and overrides in .travis.yml.)
RUN_LIVE_TESTS = envbool('RUN_LIVE_TESTS', default=not envbool('CONTINUOUS_INTEGRATION'))


def decode_att(att):
    """Returns the original data from base64-encoded attachment content"""
    return b64decode(att.encode('ascii'))


SAMPLE_IMAGE_FILENAME = "sample_image.png"


def sample_image_path(filename=SAMPLE_IMAGE_FILENAME):
    """Returns path to an actual image file in the tests directory"""
    test_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(test_dir, filename)
    return path


def sample_image_content(filename=SAMPLE_IMAGE_FILENAME):
    """Returns contents of an actual image file from the tests directory"""
    filename = sample_image_path(filename)
    with open(filename, "rb") as f:
        return f.read()


SAMPLE_FORWARDED_EMAIL = b'Received: by luna.mailgun.net with SMTP mgrt 8734663311733; Fri, 03 May 2013\n 18:26:27 +0000\nContent-Type: multipart/alternative; boundary="eb663d73ae0a4d6c9153cc0aec8b7520"\nMime-Version: 1.0\nSubject: Test email\nFrom: Someone <someone@example.com>\nTo: someoneelse@example.com\nReply-To: reply.to@example.com\nMessage-Id: <20130503182626.18666.16540@example.com>\nList-Unsubscribe: <mailto:u+na6tmy3ege4tgnldmyytqojqmfsdembyme3tmy3cha4wcndbgaydqyrgoi6wszdpovrhi5dinfzw63tfmv4gs43uomstimdhnvqws3bomnxw2jtuhusteqjgmq6tm@example.com>\nX-Mailgun-Sid: WyIwNzI5MCIsICJhbGljZUBleGFtcGxlLmNvbSIsICI2Il0=\nX-Mailgun-Variables: {"my_var_1": "Mailgun Variable #1", "my-var-2": "awesome"}\nDate: Fri, 03 May 2013 18:26:27 +0000\nSender: someone@example.com\n\n--eb663d73ae0a4d6c9153cc0aec8b7520\nMime-Version: 1.0\nContent-Type: text/plain; charset="ascii"\nContent-Transfer-Encoding: 7bit\n\nHi Bob, This is a message. Thanks!\n\n--eb663d73ae0a4d6c9153cc0aec8b7520\nMime-Version: 1.0\nContent-Type: text/html; charset="ascii"\nContent-Transfer-Encoding: 7bit\n\n<html>\n                            <body>Hi Bob, This is a message. Thanks!\n                            <br>\n</body></html>\n--eb663d73ae0a4d6c9153cc0aec8b7520--\n'


# noinspection PyUnresolvedReferences
class AnymailTestMixin:
    """Helpful additional methods for Anymail tests"""

    def assertWarns(self, expected_warning, msg=None):
        # We only support the context-manager version
        try:
            return super(AnymailTestMixin, self).assertWarns(expected_warning, msg=msg)
        except TypeError:
            # Python 2.x: use our backported assertWarns
            return _AssertWarnsContext(expected_warning, self, msg=msg)

    def assertWarnsRegex(self, expected_warning, expected_regex, msg=None):
        # We only support the context-manager version
        try:
            return super(AnymailTestMixin, self).assertWarnsRegex(expected_warning, expected_regex, msg=msg)
        except TypeError:
            # Python 2.x: use our backported assertWarns
            return _AssertWarnsContext(expected_warning, self, expected_regex=expected_regex, msg=msg)

    @contextmanager
    def assertDoesNotWarn(self, disallowed_warning=Warning):
        """Makes test error (rather than fail) if disallowed_warning occurs.

        Note: you probably want to be more specific than the default
        disallowed_warning=Warning, which errors for any warning
        (including DeprecationWarnings).
        """
        try:
            warnings.simplefilter("error", disallowed_warning)
            yield
        finally:
            warnings.resetwarnings()

    def assertCountEqual(self, *args, **kwargs):
        try:
            return super(AnymailTestMixin, self).assertCountEqual(*args, **kwargs)
        except TypeError:
            return self.assertItemsEqual(*args, **kwargs)  # Python 2

    def assertRaisesRegex(self, *args, **kwargs):
        try:
            return super(AnymailTestMixin, self).assertRaisesRegex(*args, **kwargs)
        except TypeError:
            return self.assertRaisesRegexp(*args, **kwargs)  # Python 2

    def assertRegex(self, *args, **kwargs):
        try:
            return super(AnymailTestMixin, self).assertRegex(*args, **kwargs)
        except TypeError:
            return self.assertRegexpMatches(*args, **kwargs)  # Python 2


# Backported from python 3.5
class _AssertWarnsContext(object):
    """A context manager used to implement TestCase.assertWarns* methods."""

    def __init__(self, expected, test_case, expected_regex=None, msg=None):
        self.test_case = test_case
        self.expected = expected
        self.test_case = test_case
        if expected_regex is not None:
            expected_regex = re.compile(expected_regex)
        self.expected_regex = expected_regex
        self.msg = msg

    def _raiseFailure(self, standardMsg):
        # msg = self.test_case._formatMessage(self.msg, standardMsg)
        msg = self.msg or standardMsg
        raise self.test_case.failureException(msg)

    def __enter__(self):
        # The __warningregistry__'s need to be in a pristine state for tests
        # to work properly.
        for v in sys.modules.values():
            if getattr(v, '__warningregistry__', None):
                v.__warningregistry__ = {}
        self.warnings_manager = warnings.catch_warnings(record=True)
        self.warnings = self.warnings_manager.__enter__()
        warnings.simplefilter("always", self.expected)
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.warnings_manager.__exit__(exc_type, exc_value, tb)
        if exc_type is not None:
            # let unexpected exceptions pass through
            return
        try:
            exc_name = self.expected.__name__
        except AttributeError:
            exc_name = str(self.expected)
        first_matching = None
        for m in self.warnings:
            w = m.message
            if not isinstance(w, self.expected):
                continue
            if first_matching is None:
                first_matching = w
            if (self.expected_regex is not None and
                not self.expected_regex.search(str(w))):
                continue
            # store warning for later retrieval
            self.warning = w
            self.filename = m.filename
            self.lineno = m.lineno
            return
        # Now we simply try to choose a helpful failure message
        if first_matching is not None:
            self._raiseFailure('"{}" does not match "{}"'.format(
                     self.expected_regex.pattern, str(first_matching)))
        self._raiseFailure("{} not triggered".format(exc_name))


class ClientWithCsrfChecks(Client):
    """Django test Client that enforces CSRF checks

    https://docs.djangoproject.com/en/1.9/ref/csrf/#testing
    """

    def __init__(self, **defaults):
        super(ClientWithCsrfChecks, self).__init__(
            enforce_csrf_checks=True, **defaults)
