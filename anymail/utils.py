import mimetypes
from base64 import b64encode
from datetime import datetime
from email.mime.base import MIMEBase
from email.utils import formatdate, getaddresses, unquote
from time import mktime

import six
from django.conf import settings
from django.core.mail.message import sanitize_address, DEFAULT_ATTACHMENT_MIME_TYPE
from django.utils.encoding import force_text
from django.utils.functional import Promise
from django.utils.timezone import utc

from .exceptions import AnymailConfigurationError, AnymailInvalidAddress

UNSET = object()  # Used as non-None default value


def combine(*args):
    """
    Combines all non-UNSET args, by shallow merging mappings and concatenating sequences

    >>> combine({'a': 1, 'b': 2}, UNSET, {'b': 3, 'c': 4}, UNSET)
    {'a': 1, 'b': 3, 'c': 4}
    >>> combine([1, 2], UNSET, [3, 4], UNSET)
    [1, 2, 3, 4]
    >>> combine({'a': 1}, None, {'b': 2})  # None suppresses earlier args
    {'b': 2}
    >>> combine()
    UNSET

    """
    result = UNSET
    for value in args:
        if value is None:
            # None is a request to suppress any earlier values
            result = UNSET
        elif value is not UNSET:
            if result is UNSET:
                try:
                    result = value.copy()  # will shallow merge if dict-like
                except AttributeError:
                    result = value  # will concatenate if sequence-like
            else:
                try:
                    result.update(value)  # shallow merge if dict-like
                except AttributeError:
                    result = result + value  # concatenate if sequence-like
    return result


def last(*args):
    """Returns the last of its args which is not UNSET.

    (Essentially `combine` without the merge behavior)

    >>> last(1, 2, UNSET, 3, UNSET, UNSET)
    3
    >>> last(1, 2, None, UNSET)  # None suppresses earlier args
    UNSET
    >>> last()
    UNSET

    """
    for value in reversed(args):
        if value is None:
            # None is a request to suppress any earlier values
            return UNSET
        elif value is not UNSET:
            return value
    return UNSET


def getfirst(dct, keys, default=UNSET):
    """Returns the value of the first of keys found in dict dct.

    >>> getfirst({'a': 1, 'b': 2}, ['c', 'a'])
    1
    >>> getfirst({'a': 1, 'b': 2}, ['b', 'a'])
    2
    >>> getfirst({'a': 1, 'b': 2}, ['c'])
    KeyError
    >>> getfirst({'a': 1, 'b': 2}, ['c'], None)
    None
    """
    for key in keys:
        try:
            return dct[key]
        except KeyError:
            pass
    if default is UNSET:
        raise KeyError("None of %s found in dict" % ', '.join(keys))
    else:
        return default


def parse_one_addr(address):
    # This is email.utils.parseaddr, but without silently returning
    # partial content if there are commas or parens in the string:
    addresses = getaddresses([address])
    if len(addresses) > 1:
        raise ValueError("Multiple email addresses (parses as %r)" % addresses)
    elif len(addresses) == 0:
        return ('', '')
    return addresses[0]


class ParsedEmail(object):
    """A sanitized, full email address with separate name and email properties."""

    def __init__(self, address, encoding):
        if address is None:
            self.name = self.email = self.address = None
            return
        try:
            self.name, self.email = parse_one_addr(force_text(address))
            if self.email == '':
                # normalize sanitize_address py2/3 behavior:
                raise ValueError('No email found')
            # Django's sanitize_address is like email.utils.formataddr, but also
            # escapes as needed for use in email message headers:
            self.address = sanitize_address((self.name, self.email), encoding)
        except (IndexError, TypeError, ValueError) as err:
            raise AnymailInvalidAddress("Invalid email address format %r: %s"
                                        % (address, str(err)))

    def __str__(self):
        return self.address


class Attachment(object):
    """A normalized EmailMessage.attachments item with additional functionality

    Normalized to have these properties:
    name: attachment filename; may be None
    content: bytestream
    mimetype: the content type; guessed if not explicit
    inline: bool, True if attachment has a Content-ID header
    content_id: for inline, the Content-ID (*with* <>); may be None
    cid: for inline, the Content-ID *without* <>; may be empty string
    """

    def __init__(self, attachment, encoding):
        # Note that an attachment can be either a tuple of (filename, content, mimetype)
        # or a MIMEBase object. (Also, both filename and mimetype may be missing.)
        self._attachment = attachment
        self.encoding = encoding  # should we be checking attachment["Content-Encoding"] ???
        self.inline = False
        self.content_id = None
        self.cid = ""

        if isinstance(attachment, MIMEBase):
            self.name = attachment.get_filename()
            self.content = attachment.get_payload(decode=True)
            self.mimetype = attachment.get_content_type()

            if get_content_disposition(attachment) == 'inline':
                self.inline = True
                self.content_id = attachment["Content-ID"]  # probably including the <...>
                if self.content_id is not None:
                    self.cid = unquote(self.content_id)  # without the <, >
        else:
            (self.name, self.content, self.mimetype) = attachment

        self.name = force_non_lazy(self.name)
        self.content = force_non_lazy(self.content)

        # Guess missing mimetype from filename, borrowed from
        # django.core.mail.EmailMessage._create_attachment()
        if self.mimetype is None and self.name is not None:
            self.mimetype, _ = mimetypes.guess_type(self.name)
        if self.mimetype is None:
            self.mimetype = DEFAULT_ATTACHMENT_MIME_TYPE

    @property
    def b64content(self):
        """Content encoded as a base64 ascii string"""
        content = self.content
        if isinstance(content, six.text_type):
            content = content.encode(self.encoding)
        return b64encode(content).decode("ascii")


def get_content_disposition(mimeobj):
    """Return the message's content-disposition if it exists, or None.

    Backport of py3.5 :func:`~email.message.Message.get_content_disposition`
    """
    value = mimeobj.get('content-disposition')
    if value is None:
        return None
    # _splitparam(value)[0].lower() :
    return str(value).partition(';')[0].strip().lower()


def get_anymail_setting(name, default=UNSET, esp_name=None, kwargs=None, allow_bare=False):
    """Returns an Anymail option from kwargs or Django settings.

    Returns first of:
    - kwargs[name] -- e.g., kwargs['api_key'] -- and name key will be popped from kwargs
    - settings.ANYMAIL['<ESP_NAME>_<NAME>'] -- e.g., settings.ANYMAIL['MAILGUN_API_KEY']
    - settings.ANYMAIL_<ESP_NAME>_<NAME> -- e.g., settings.ANYMAIL_MAILGUN_API_KEY
    - settings.<ESP_NAME>_<NAME> (only if allow_bare) -- e.g., settings.MAILGUN_API_KEY
    - default if provided; else raises AnymailConfigurationError

    If allow_bare, allows settings.<ESP_NAME>_<NAME> without the ANYMAIL_ prefix:
    ANYMAIL = { "MAILGUN_API_KEY": "xyz", ... }
    ANYMAIL_MAILGUN_API_KEY = "xyz"
    MAILGUN_API_KEY = "xyz"
    """

    try:
        value = kwargs.pop(name)
        if name in ['username', 'password']:
            # Work around a problem in django.core.mail.send_mail, which calls
            # get_connection(... username=None, password=None) by default.
            # We need to ignore those None defaults (else settings like
            # 'SENDGRID_USERNAME' get unintentionally overridden from kwargs).
            if value is not None:
                return value
        else:
            return value
    except (AttributeError, KeyError):
        pass

    if esp_name is not None:
        setting = "{}_{}".format(esp_name.upper(), name.upper())
    else:
        setting = name.upper()
    anymail_setting = "ANYMAIL_%s" % setting

    try:
        return settings.ANYMAIL[setting]
    except (AttributeError, KeyError):
        try:
            return getattr(settings, anymail_setting)
        except AttributeError:
            if allow_bare:
                try:
                    return getattr(settings, setting)
                except AttributeError:
                    pass
            if default is UNSET:
                message = "You must set %s or ANYMAIL = {'%s': ...}" % (anymail_setting, setting)
                if allow_bare:
                    message += " or %s" % setting
                message += " in your Django settings"
                raise AnymailConfigurationError(message)
            else:
                return default


def collect_all_methods(cls, method_name):
    """Return list of all `method_name` methods for cls and its superclass chain.

    List is in MRO order, with no duplicates. Methods are unbound.

    (This is used to simplify mixins and subclasses that contribute to a method set,
    without requiring superclass chaining, and without requiring cooperating
    superclasses.)
    """
    methods = []
    for ancestor in cls.__mro__:
        try:
            validator = getattr(ancestor, method_name)
        except AttributeError:
            pass
        else:
            if validator not in methods:
                methods.append(validator)
    return methods


EPOCH = datetime(1970, 1, 1, tzinfo=utc)


def timestamp(dt):
    """Return the unix timestamp (seconds past the epoch) for datetime dt"""
    # This is the equivalent of Python 3.3's datetime.timestamp
    try:
        return dt.timestamp()
    except AttributeError:
        if dt.tzinfo is None:
            return mktime(dt.timetuple())
        else:
            return (dt - EPOCH).total_seconds()


def rfc2822date(dt):
    """Turn a datetime into a date string as specified in RFC 2822."""
    # This is almost the equivalent of Python 3.3's email.utils.format_datetime,
    # but treats naive datetimes as local rather than "UTC with no information ..."
    timeval = timestamp(dt)
    return formatdate(timeval, usegmt=True)


def is_lazy(obj):
    """Return True if obj is a Django lazy object."""
    # See django.utils.functional.lazy. (This appears to be preferred
    # to checking for `not isinstance(obj, six.text_type)`.)
    return isinstance(obj, Promise)


def force_non_lazy(obj):
    """If obj is a Django lazy object, return it coerced to text; otherwise return it unchanged.

    (Similar to django.utils.encoding.force_text, but doesn't alter non-text objects.)
    """
    if is_lazy(obj):
        return six.text_type(obj)

    return obj


def force_non_lazy_list(obj):
    """Return a (shallow) copy of sequence obj, with all values forced non-lazy."""
    try:
        return [force_non_lazy(item) for item in obj]
    except (AttributeError, TypeError):
        return force_non_lazy(obj)


def force_non_lazy_dict(obj):
    """Return a (deep) copy of dict obj, with all values forced non-lazy."""
    try:
        return {key: force_non_lazy_dict(value) for key, value in obj.items()}
    except (AttributeError, TypeError):
        return force_non_lazy(obj)
