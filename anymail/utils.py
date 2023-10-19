import base64
import mimetypes
from base64 import b64encode
from collections.abc import Mapping, MutableMapping
from copy import copy, deepcopy
from email.mime.base import MIMEBase
from email.utils import formatdate, getaddresses, parsedate_to_datetime, unquote
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.mail.message import DEFAULT_ATTACHMENT_MIME_TYPE, sanitize_address
from django.utils.encoding import force_str
from django.utils.functional import Promise
from requests.structures import CaseInsensitiveDict

from .exceptions import AnymailConfigurationError, AnymailInvalidAddress

BASIC_NUMERIC_TYPES = (int, float)


UNSET = type("UNSET", (object,), {})  # Used as non-None default value


def concat_lists(*args):
    """
    Combines all non-UNSET args, by concatenating lists (or sequence-like types).
    Does not modify any args.

    >>> concat_lists([1, 2], UNSET, [3, 4], UNSET)
    [1, 2, 3, 4]
    >>> concat_lists([1, 2], None, [3, 4])  # None suppresses earlier args
    [3, 4]
    >>> concat_lists()
    UNSET

    """
    result = UNSET
    for value in args:
        if value is None:
            # None is a request to suppress any earlier values
            result = UNSET
        elif value is not UNSET:
            if result is UNSET:
                result = list(value)
            else:
                result = result + list(value)  # concatenate sequence-like
    return result


def merge_dicts_shallow(*args):
    """
    Shallow-merges all non-UNSET args.
    Does not modify any args.

    >>> merge_dicts_shallow({'a': 1, 'b': 2}, UNSET, {'b': 3, 'c': 4}, UNSET)
    {'a': 1, 'b': 3, 'c': 4}
    >>> merge_dicts_shallow({'a': {'a1': 1, 'a2': 2}}, {'a': {'a1': 11, 'a3': 33}})
    {'a': {'a1': 11, 'a3': 33}}
    >>> merge_dicts_shallow({'a': 1}, None, {'b': 2})  # None suppresses earlier args
    {'b': 2}
    >>> merge_dicts_shallow()
    UNSET

    """
    result = UNSET
    for value in args:
        if value is None:
            # None is a request to suppress any earlier values
            result = UNSET
        elif value is not UNSET:
            if result is UNSET:
                result = copy(value)
            else:
                result.update(value)
    return result


def merge_dicts_deep(*args):
    """
    Deep-merges all non-UNSET args.
    Does not modify any args.

    >>> merge_dicts_deep({'a': 1, 'b': 2}, UNSET, {'b': 3, 'c': 4}, UNSET)
    {'a': 1, 'b': 3, 'c': 4}
    >>> merge_dicts_deep({'a': {'a1': 1, 'a2': 2}}, {'a': {'a1': 11, 'a3': 33}})
    {'a': {'a1': 11, 'a2': 2, 'a3': 33}}
    >>> merge_dicts_deep({'a': 1}, None, {'b': 2})  # None suppresses earlier args
    {'b': 2}
    >>> merge_dicts_deep()
    UNSET

    """
    result = UNSET
    for value in args:
        if value is None:
            # None is a request to suppress any earlier values
            result = UNSET
        elif value is not UNSET:
            if result is UNSET:
                result = deepcopy(value)
            else:
                update_deep(result, value)
    return result


def merge_dicts_one_level(*args):
    """
    Mixture of merge_dicts_deep and merge_dicts_shallow:
    Deep merges first level, shallow merges second level.
    Does not modify any args.

    (Useful for {"email": {options...}, ...} style dicts,
    like merge_data: shallow merges the options for each email.)
    """
    result = UNSET
    for value in args:
        if value is None:
            # None is a request to suppress any earlier values
            result = UNSET
        elif value is not UNSET:
            if result is UNSET:
                result = {}
            for k, v in value.items():
                result.setdefault(k, {}).update(v)
    return result


def last(*args):
    """Returns the last of its args which is not UNSET.

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
        raise KeyError("None of %s found in dict" % ", ".join(keys))
    else:
        return default


def update_deep(dct, other):
    """Merge (recursively) keys and values from dict other into dict dct

    Works with dict-like objects: dct (and descendants) can be any MutableMapping,
    and other can be any Mapping
    """
    for key, value in other.items():
        if (
            key in dct
            and isinstance(dct[key], MutableMapping)
            and isinstance(value, Mapping)
        ):
            update_deep(dct[key], value)
        else:
            dct[key] = value
    # (like dict.update(), no return value)


def parse_address_list(address_list, field=None):
    """Returns a list of EmailAddress objects from strings in address_list.

    Essentially wraps :func:`email.utils.getaddresses` with better error
    messaging and more-useful output objects

    Note that the returned list might be longer than the address_list param,
    if any individual string contains multiple comma-separated addresses.

    :param list[str]|str|None|list[None] address_list:
        the address or addresses to parse
    :param str|None field:
        optional description of the source of these addresses, for error message
    :return list[:class:`EmailAddress`]:
    :raises :exc:`AnymailInvalidAddress`:
    """
    if isinstance(address_list, str) or is_lazy(address_list):
        address_list = [address_list]

    if address_list is None or address_list == [None]:
        return []

    # For consistency with Django's SMTP backend behavior, extract all addresses
    # from the list -- which may split comma-seperated strings into multiple addresses.
    # (See django.core.mail.message: EmailMessage.message to/cc/bcc/reply_to handling;
    # also logic for ADDRESS_HEADERS in forbid_multi_line_headers.)

    # resolve lazy strings:
    address_list_strings = [force_str(address) for address in address_list]
    name_email_pairs = getaddresses(address_list_strings)
    if name_email_pairs == [] and address_list_strings == [""]:
        name_email_pairs = [("", "")]  # getaddresses ignores a single empty string
    parsed = [
        EmailAddress(display_name=name, addr_spec=email)
        for (name, email) in name_email_pairs
    ]

    # Sanity-check, and raise useful errors
    for address in parsed:
        if address.username == "" or address.domain == "":
            # Django SMTP allows username-only emails,
            # but they're not meaningful with an ESP
            errmsg = (
                "Invalid email address '{problem}'" " parsed from '{source}'{where}."
            ).format(
                problem=address.addr_spec,
                source=", ".join(address_list_strings),
                where=" in `%s`" % field if field else "",
            )
            if len(parsed) > len(address_list):
                errmsg += " (Maybe missing quotes around a display-name?)"
            raise AnymailInvalidAddress(errmsg)

    return parsed


def parse_single_address(address, field=None):
    """Parses a single EmailAddress from str address, or raises AnymailInvalidAddress

    :param str address: the fully-formatted email str to parse
    :param str|None field:
        optional description of the source of this address, for error message
    :return :class:`EmailAddress`: if address contains a single email
    :raises :exc:`AnymailInvalidAddress`: if address contains no or multiple emails
    """
    parsed = parse_address_list([address], field=field)
    count = len(parsed)
    if count > 1:
        raise AnymailInvalidAddress(
            "Only one email address is allowed;"
            " found {count} in '{address}'{where}.".format(
                count=count, address=address, where=" in `%s`" % field if field else ""
            )
        )
    else:
        return parsed[0]


class EmailAddress:
    """A sanitized, complete email address with easy access
    to display-name, addr-spec (email), etc.

    Similar to Python 3.6+ email.headerregistry.Address

    Instance properties, all read-only:
    :ivar str display_name:
        the address's display-name portion (unqouted, unescaped),
        e.g., 'Display Name, Inc.'
    :ivar str addr_spec:
        the address's addr-spec portion (unquoted, unescaped),
        e.g., 'user@example.com'
    :ivar str username:
        the local part (before the '@') of the addr-spec,
        e.g., 'user'
    :ivar str domain:
        the domain part (after the '@') of the addr-spec,
        e.g., 'example.com'

    :ivar str address:
        the fully-formatted address, with any necessary quoting and escaping,
        e.g., '"Display Name, Inc." <user@example.com>'
        (also available as `str(EmailAddress)`)
    """

    def __init__(self, display_name="", addr_spec=None):
        self._address = None  # lazy formatted address
        if addr_spec is None:
            try:
                display_name, addr_spec = display_name  # unpack (name,addr) tuple
            except ValueError:
                pass

        # ESPs should clean or reject addresses containing newlines, but some
        # extra protection can't hurt (and it seems to be a common oversight)
        if "\n" in display_name or "\r" in display_name:
            raise ValueError("EmailAddress display_name cannot contain newlines")
        if "\n" in addr_spec or "\r" in addr_spec:
            raise ValueError("EmailAddress addr_spec cannot contain newlines")

        self.display_name = display_name
        self.addr_spec = addr_spec
        try:
            self.username, self.domain = addr_spec.split("@", 1)
            # do we need to unquote username?
        except ValueError:
            self.username = addr_spec
            self.domain = ""

    def __repr__(self):
        return "EmailAddress({display_name!r}, {addr_spec!r})".format(
            display_name=self.display_name, addr_spec=self.addr_spec
        )

    @property
    def address(self):
        if self._address is None:
            # (you might be tempted to use `encoding=settings.DEFAULT_CHARSET` here,
            # but that always forces the display-name to quoted-printable/base64,
            # even when simple ascii would work fine--and be more readable)
            self._address = self.formataddr()
        return self._address

    def formataddr(self, encoding=None):
        """Return a fully-formatted email address, using encoding.

        This is essentially the same as :func:`email.utils.formataddr`
        on the EmailAddress's name and email properties, but uses
        Django's :func:`~django.core.mail.message.sanitize_address`
        for consistent handling of encoding (a.k.a. charset) and
        proper handling of IDN domain portions.

        :param str|None encoding:
            the charset to use for the display-name portion;
            default None uses ascii if possible, else 'utf-8'
            (quoted-printable utf-8/base64)
        """
        return sanitize_address((self.display_name, self.addr_spec), encoding)

    def __str__(self):
        return self.address


class Attachment:
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
        self.encoding = encoding  # or check attachment["Content-Encoding"] ???
        self.inline = False
        self.content_id = None
        self.cid = ""

        if isinstance(attachment, MIMEBase):
            self.name = attachment.get_filename()
            self.content = attachment.get_payload(decode=True)
            if self.content is None:
                self.content = attachment.as_bytes()
            self.mimetype = attachment.get_content_type()
            # Content-Type includes charset if provided
            self.content_type = attachment["Content-Type"]

            content_disposition = attachment.get_content_disposition()
            if content_disposition == "inline" or (
                not content_disposition and "Content-ID" in attachment
            ):
                self.inline = True
                self.content_id = attachment["Content-ID"]  # probably including <...>
                if self.content_id is not None:
                    self.cid = unquote(self.content_id)  # without the <, >
        else:
            (self.name, self.content, self.mimetype) = attachment
            self.content_type = self.mimetype

        self.name = force_non_lazy(self.name)
        self.content = force_non_lazy(self.content)

        # Guess missing mimetype from filename, borrowed from
        # django.core.mail.EmailMessage._create_attachment()
        if self.mimetype is None and self.name is not None:
            self.mimetype, _ = mimetypes.guess_type(self.name)
        if self.mimetype is None:
            self.mimetype = DEFAULT_ATTACHMENT_MIME_TYPE
        if self.content_type is None:
            self.content_type = self.mimetype

    def __repr__(self):
        details = [
            self.mimetype,
            "len={length}".format(length=len(self.content)),
        ]
        if self.name:
            details.append("name={name!r}".format(name=self.name))
        if self.inline:
            details.insert(0, "inline")
            details.append(
                "content_id={content_id!r}".format(content_id=self.content_id)
            )
        return "Attachment<{details}>".format(details=", ".join(details))

    @property
    def b64content(self):
        """Content encoded as a base64 ascii string"""
        content = self.content
        if isinstance(content, str):
            content = content.encode(self.encoding)
        return b64encode(content).decode("ascii")


def get_anymail_setting(
    name, default=UNSET, esp_name=None, kwargs=None, allow_bare=False
):
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
        if name in ["username", "password"]:
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
        setting = "{}_{}".format(esp_name.upper().replace(" ", "_"), name.upper())
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
                message = "You must set %s or ANYMAIL = {'%s': ...}" % (
                    anymail_setting,
                    setting,
                )
                if allow_bare:
                    message += " or %s" % setting
                message += " in your Django settings"
                raise AnymailConfigurationError(message) from None
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


def querydict_getfirst(qdict, field, default=UNSET):
    """
    Like :func:`django.http.QueryDict.get`,
    but returns *first* value of multi-valued field.

    >>> from django.http import QueryDict
    >>> q = QueryDict('a=1&a=2&a=3')
    >>> querydict_getfirst(q, 'a')
    '1'
    >>> q.get('a')
    '3'
    >>> q['a']
    '3'

    You can bind this to a QueryDict instance using the "descriptor protocol":
    >>> q.getfirst = querydict_getfirst.__get__(q)
    >>> q.getfirst('a')
    '1'
    """
    # (Why not instead define a QueryDict subclass with this method? Because there's
    # no simple way to efficiently initialize a QueryDict subclass with the contents
    # of an existing instance.)
    values = qdict.getlist(field)
    if len(values) > 0:
        return values[0]
    elif default is not UNSET:
        return default
    else:
        return qdict[field]  # raise appropriate KeyError


def rfc2822date(dt):
    """Turn a datetime into a date string as specified in RFC 2822."""
    # This is almost the equivalent of Python's email.utils.format_datetime,
    # but treats naive datetimes as local rather than "UTC with no information ..."
    timeval = dt.timestamp()
    return formatdate(timeval, usegmt=True)


def angle_wrap(s):
    """Return s surrounded by angle brackets, added only if necessary"""
    # This is the inverse behavior of email.utils.unquote
    # (which you might think email.utils.quote would do, but it doesn't)
    if len(s) > 0:
        if s[0] != "<":
            s = "<" + s
        if s[-1] != ">":
            s = s + ">"
    return s


def is_lazy(obj):
    """Return True if obj is a Django lazy object."""
    # See django.utils.functional.lazy. (This appears to be preferred
    # to checking for `not isinstance(obj, str)`.)
    return isinstance(obj, Promise)


def force_non_lazy(obj):
    """
    If obj is a Django lazy object, return it coerced to text;
    otherwise return it unchanged.

    (Similar to django.utils.encoding.force_text, but doesn't alter non-text objects.)
    """
    if is_lazy(obj):
        return str(obj)

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


def get_request_basic_auth(request):
    """Returns HTTP basic auth string sent with request, or None.

    If request includes basic auth, result is string 'username:password'.
    """
    try:
        authtype, authdata = request.META["HTTP_AUTHORIZATION"].split()
        if authtype.lower() == "basic":
            return base64.b64decode(authdata).decode("utf-8")
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    return None


def get_request_uri(request):
    """Returns the "exact" url used to call request.

    Like :func:`django.http.request.HTTPRequest.build_absolute_uri`,
    but also inlines HTTP basic auth, if present.
    """
    url = request.build_absolute_uri()
    basic_auth = get_request_basic_auth(request)
    if basic_auth is not None:
        # must reassemble url with auth
        parts = urlsplit(url)
        url = urlunsplit(
            (
                parts.scheme,
                basic_auth + "@" + parts.netloc,
                parts.path,
                parts.query,
                parts.fragment,
            )
        )
    return url


def parse_rfc2822date(s):
    """Parses an RFC-2822 formatted date string into a datetime.datetime

    Returns None if string isn't parseable. Returned datetime will be naive
    if string doesn't include known timezone offset; aware if it does.

    (Same as Python 3 email.utils.parsedate_to_datetime, with improved
    handling for unparseable date strings.)
    """
    try:
        return parsedate_to_datetime(s)
    except (IndexError, TypeError, ValueError):
        # despite the docs, parsedate_to_datetime often dies on unparseable input
        return None


class CaseInsensitiveCasePreservingDict(CaseInsensitiveDict):
    """A dict with case-insensitive keys, which preserves the *first* key set.

    >>> cicpd = CaseInsensitiveCasePreservingDict()
    >>> cicpd["Accept"] = "application/text+xml"
    >>> cicpd["accEPT"] = "application/json"
    >>> cicpd["accept"]
    "application/json"
    >>> cicpd.keys()
    ["Accept"]

    Compare to CaseInsensitiveDict, which preserves *last* key set:
    >>> cid = CaseInsensitiveCasePreservingDict()
    >>> cid["Accept"] = "application/text+xml"
    >>> cid["accEPT"] = "application/json"
    >>> cid.keys()
    ["accEPT"]
    """

    def __setitem__(self, key, value):
        _k = key.lower()
        try:
            # retrieve earlier matching key, if any
            key, _ = self._store[_k]
        except KeyError:
            pass
        self._store[_k] = (key, value)

    def copy(self):
        return self.__class__(self._store.values())
