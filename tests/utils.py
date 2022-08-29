# Anymail test utils
import re
import sys
import uuid
import warnings
from base64 import b64decode
from contextlib import contextmanager
from io import BytesIO, StringIO
from pathlib import Path
from unittest import TestCase
from unittest.util import safe_repr

import django.test.client


def decode_att(att):
    """Returns the original data from base64-encoded attachment content"""
    return b64decode(att.encode('ascii'))


def rfc822_unfold(text):
    # "Unfolding is accomplished by simply removing any CRLF that is immediately followed by WSP"
    # (WSP is space or tab, and per email.parser semantics, we allow CRLF, CR, or LF endings)
    return re.sub(r'(\r\n|\r|\n)(?=[ \t])', "", text)


#
# Sample files for testing (in ./test_files subdir)
#

TEST_FILES_DIR = Path(__file__).parent.joinpath("test_files").resolve()

SAMPLE_IMAGE_FILENAME = "sample_image.png"
SAMPLE_EMAIL_FILENAME = "sample_email.txt"


def test_file_path(filename):
    """Returns path to a test file"""
    return TEST_FILES_DIR.joinpath(filename)


def test_file_content(filename):
    """Returns contents (bytes) of a test file"""
    return TEST_FILES_DIR.joinpath(filename).read_bytes()


def sample_image_path(filename=SAMPLE_IMAGE_FILENAME):
    """Returns path to an actual image file in the tests directory"""
    return test_file_path(filename)


def sample_image_content(filename=SAMPLE_IMAGE_FILENAME):
    """Returns contents of an actual image file from the tests directory"""
    return test_file_content(filename)


def sample_email_path(filename=SAMPLE_EMAIL_FILENAME):
    """Returns path to an email file (e.g., for forwarding as an attachment)"""
    return test_file_path(filename)


def sample_email_content(filename=SAMPLE_EMAIL_FILENAME):
    """Returns bytes contents of an email file (e.g., for forwarding as an attachment)"""
    return test_file_content(filename)


#
# TestCase helpers
#

class AnymailTestMixin(TestCase):
    """Helpful additional methods for Anymail tests"""

    def assertDictMatches(self, expected, actual, msg=None):
        """
        Tests that dict `expected` is a subset of `actual`. (That expected
        is *in* actual. Note the args are in the same needle, haystack
        order as assertIn.)
        """
        # This is just assertDictContainsSubset, and the code is copied in from there.
        # (That was deprecated because apparently the arg order was confusing given the
        # name. The "matches" terminology is borrowed from several JS expect packages.)
        missing = []
        mismatched = []
        for key, value in expected.items():
            if key not in actual:
                missing.append(key)
            elif value != actual[key]:
                mismatched.append('%s, expected: %s, actual: %s' %
                                  (safe_repr(key), safe_repr(value),
                                   safe_repr(actual[key])))

        if not (missing or mismatched):
            return

        standardMsg = ''
        if missing:
            standardMsg = 'Missing: %s' % ','.join(safe_repr(m) for m in missing)
        if mismatched:
            if standardMsg:
                standardMsg += '; '
            standardMsg += 'Mismatched values: %s' % ','.join(mismatched)

        self.fail(self._formatMessage(msg, standardMsg))

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

    def assertEqualIgnoringHeaderFolding(self, first, second, msg=None):
        # Unfold (per RFC-8222) all text first and second, then compare result.
        # Useful for message/rfc822 attachment tests, where various Python email
        # versions handled folding slightly differently.
        # (Technically, this is unfolding both headers and (incorrectly) bodies,
        # but that doesn't really affect the tests.)
        if isinstance(first, bytes) and isinstance(second, bytes):
            first = first.decode('utf-8')
            second = second.decode('utf-8')
        first = rfc822_unfold(first)
        second = rfc822_unfold(second)
        self.assertEqual(first, second, msg)

    def assertUUIDIsValid(self, uuid_str, msg=None, version=4):
        """Assert the uuid_str evaluates to a valid UUID"""
        try:
            uuid.UUID(uuid_str, version=version)
        except (ValueError, AttributeError, TypeError):
            raise self.failureException(
                msg or "%r is not a valid UUID" % uuid_str)

    @contextmanager
    def assertPrints(self, expected, match="contain", msg=None):
        """Use as a context manager; checks that code writes `expected` to stdout.

        `match` can be "contain", "equal", "start", "end", or the name of any str
        method that takes one str argument and returns a boolean, or None to simply
        capture stdout without checking it. Default is "contain".

        Returns StringIO buffer; the output text is available as cm.getvalue().

        >>> with self.assertPrints("foo") as cm:
        ...     print("foo")
        >>> self.assertNotIn("bar", cm.getvalue())
        """
        matchfn = {
            "contain": "__contains__",
            "equal": "__eq__",
            "start": "startswith",
            "end": "endswith",
        }.get(match, match)
        old_stdout = sys.stdout
        buffer = StringIO()
        try:
            sys.stdout = buffer
            yield buffer
            if matchfn:
                actual = buffer.getvalue()
                bound_matchfn = getattr(actual, matchfn)
                if not bound_matchfn(expected):
                    raise self.failureException(
                        msg or "Stdout {actual!r} does not {match} {expected!r}".format(
                            actual=actual, match=match, expected=expected))
        finally:
            sys.stdout = old_stdout


class ClientWithCsrfChecks(django.test.Client):
    """Django test Client that enforces CSRF checks

    https://docs.djangoproject.com/en/stable/ref/csrf/#testing
    """

    def __init__(self, **defaults):
        super().__init__(enforce_csrf_checks=True, **defaults)


# dedent for bytestrs
# https://stackoverflow.com/a/39841195/647002
_whitespace_only_re = re.compile(b'^[ \t]+$', re.MULTILINE)
_leading_whitespace_re = re.compile(b'(^[ \t]*)(?:[^ \t\n])', re.MULTILINE)


def dedent_bytes(text):
    """textwrap.dedent, but for bytes"""
    # Look for the longest leading string of spaces and tabs common to
    # all lines.
    margin = None
    text = _whitespace_only_re.sub(b'', text)
    indents = _leading_whitespace_re.findall(text)
    for indent in indents:
        if margin is None:
            margin = indent

        # Current line more deeply indented than previous winner:
        # no change (previous winner is still on top).
        elif indent.startswith(margin):
            pass

        # Current line consistent with and no deeper than previous winner:
        # it's the new winner.
        elif margin.startswith(indent):
            margin = indent

        # Find the largest common whitespace between current line
        # and previous winner.
        else:
            for i, (x, y) in enumerate(zip(margin, indent)):
                if x != y:
                    margin = margin[:i]
                    break
            else:
                margin = margin[:len(indent)]

    if margin:
        text = re.sub(b'(?m)^' + margin, b'', text)
    return text


def make_fileobj(content, filename=None, content_type=None, encoding=None):
    """
    Returns a file-like object that can be used in Django test Client
    post data to simulate an uploaded file.
    """
    # The logic that unpacks this is in django.test.client.encode_file.
    if isinstance(content, str):
        content = content.encode(encoding or 'utf-8')
    fileobj = BytesIO(content)
    if filename is not None:
        fileobj.name = filename
    if content_type is not None:
        fileobj.content_type = content_type
    return fileobj


def encode_multipart(boundary, data):
    """
    Version of :func:`django.test.client.encode_multipart` that allows
    empty filenames. (The original function substitutes the field's
    name if a file has an empty name.)
    """
    # For simplicity, encode with the original function, and then
    # replace any 'filename="<key>"' with 'filename=""'. This isn't
    # entirely robust, but is sufficient for testing use.
    encoded = django.test.client.encode_multipart(boundary, data)
    re_keys = r"|".join(re.escape(key) for key in data.keys())
    return re.sub(
        rb'filename="(%s)"' % re_keys.encode("ascii"),
        b'filename=""', encoded)
