import base64
import mimetypes
from base64 import b64encode
from collections.abc import Mapping, MutableMapping
from copy import copy, deepcopy
from email.charset import Charset
from email.errors import HeaderParseError, InvalidHeaderDefect
from email.header import decode_header
from email.headerregistry import Address
from email.mime.base import MIMEBase
from email.utils import formatdate, getaddresses, parsedate_to_datetime, unquote
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.mail.message import DEFAULT_ATTACHMENT_MIME_TYPE
from django.utils.encoding import force_str
from django.utils.functional import Promise, cached_property
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
    try:
        parsed = [
            EmailAddress(display_name=name, addr_spec=email)
            for (name, email) in name_email_pairs
        ]
    except AnymailInvalidAddress as error:
        # Add context to message.
        msg = error.args[0]
        if field:
            msg += f" in `{field}`"
        source = ", ".join(address_list_strings)
        msg += f" parsed from {source!r}"
        if any("," in value for value in address_list_strings):
            msg += " (maybe missing quotes around a display-name?)"
        raise error.__class__(msg, *error.args[1:]) from error

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


class EmailAddress(Address):
    """A sanitized, complete email address with easy access
    to display-name, addr-spec (email), etc.

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

    def __init__(self, display_name="", addr_spec=None, *, username="", domain=None):
        if display_name is None:
            display_name = ""

        if addr_spec and not addr_spec.isascii():
            # Work around python/cpython#81074 bug with Address(addr_spec=non_ascii).
            try:
                username, domain = addr_spec.rsplit("@", 1)
            except ValueError:  # not enough values to unpack
                # local-part only address. Django supports that, but no Anymail ESP does.
                raise AnymailInvalidAddress(
                    f"Invalid email address {addr_spec!r}: missing @domain part"
                ) from None
            username = unquote_string(username)
            addr_spec = None

        try:
            super().__init__(display_name, username, domain, addr_spec)
        except (HeaderParseError, IndexError, InvalidHeaderDefect, ValueError) as error:
            msg = f"Invalid email address {addr_spec!r}"
            if display_name:
                msg += f" display_name={display_name!r}"
            raise AnymailInvalidAddress(msg) from error

    def __repr__(self):
        return f"{self.__class__.__name__}({self.display_name!r}, {self.addr_spec!r})"

    @cached_property
    def address(self):
        """
        Fully-formatted string address, properly quoted and escaped.
        Non-ASCII content is rendered as Unicode characters (not encoded).

        :return str:
        """
        return self.format()

    def format_display_name(self, *, use_rfc2047=False, use_quotes=False):
        """
        Return display_name formatted as specified.

        :param bool | Literal["force"] use_rfc2047:
            Whether to convert a non-ASCII display-name to an RFC 2047 encoded-word.
            If "force", converts unconditionally.
        :param bool | Literal["force"] use_quotes:
            Whether to enclose display-name containing RFC 5322 special characters
            in double quotes. If "force", quotes unconditionally.
        :return str:
        """
        if use_rfc2047 == "force" or (use_rfc2047 and not self.display_name.isascii()):
            return rfc2047_encode(self.display_name)
        if use_quotes:
            return quote_string(self.display_name, force=(use_quotes == "force"))
        return self.display_name

    def format_addr_spec(self, *, idna_encode=None):
        """
        Return addr_spec formatted as specified.

        :param Callable[[str], str] | None idna_encode:
            IDNA encoding function to apply to a non-ASCII domain.
            If None, non-ASCII domains are left as-is.
        :return str:
        """
        # (Note there is no 7-bit encoding for the username portion.
        # If that local part isn't ASCII, probably the ESP will complain.)
        if idna_encode and not self.domain.isascii():
            return str(Address(username=self.username, domain=idna_encode(self.domain)))
        return self.addr_spec

    def format(self, *, use_rfc2047=False, idna_encode=None):
        """
        Return a fully-formatted email address.

        Parameters control handling of non-ASCII address parts.

        :param bool | Literal["force"] use_rfc2047:
            Whether to convert a non-ASCII display-name to an RFC 2047 encoded-word.
            Passing "force" applies rfc2047 unconditionally, even to ASCII-only names.
        :param Callable[[str], str] | None idna_encode:
            IDNA encoding function to apply to a non-ASCII domain.
            If None, non-ASCII domains are left as-is.
        :return str:
        """
        # This is essentially:
        #     str(Address(display_name=self.format_display_name(...),
        #                 addr_spec=self.format_addr_spec(...)))
        # but working around around python/cpython#81074.
        display_name = self.format_display_name(use_rfc2047=use_rfc2047)
        username = self.username
        if idna_encode and not self.domain.isascii():
            domain = idna_encode(self.domain)
        else:
            domain = self.domain
        return str(Address(display_name=display_name, username=username, domain=domain))

    def as_dict(
        self,
        *,
        name="name",
        email="email",
        use_rfc2047=False,
        quote_name=False,
        idna_encode=None,
    ):
        """
        Return a dict representing the address, useful for JSON APIs.

        :param str name: name of the display_name field
        :param str email: name of the addr_spec field
        :param bool | Literal["force"] use_rfc2047:
            whether to encode the name field with rfc2047,
            as in format_display_name()
        :param bool | Literal["force"] quote_name:
            whether to wrap the name field as an RFC 5322 quoted-string,
            as in format_display_name()
        :param Callable[[str], str] | None idna_encode:
            IDNA encoding function to apply to a non-ASCII domain.
            If None, non-ASCII domains are left as-is.
        :return dict[str,str]:
        """
        obj = {email: self.format_addr_spec(idna_encode=idna_encode)}
        if self.display_name:
            obj[name] = self.format_display_name(
                use_rfc2047=use_rfc2047, use_quotes=quote_name
            )
        return obj

    @property
    def uses_eai(self):
        return not self.username.isascii()

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


def rfc2047_encode(text):
    """Convert text to an RFC 2047 encoded-word using the utf-8 charset."""
    # This uses Python's legacy email API, as the modern API does not expose
    # a standalone RFC 2047 encoding operation.
    return Charset("utf-8").header_encode(text)


def rfc2047_decode(encoded):
    """Convert an email header that may include RFC 2047 encoded-words to text."""
    # This uses Python's legacy email API, as the modern API does not expose
    # a standalone RFC 2047 decoding operation.
    return "".join(
        (
            segment
            if charset is None and isinstance(segment, str)
            else segment.decode(charset or "ascii")
        )
        for segment, charset in decode_header(encoded)
    )


#: Set of characters that need special handling in a structured (address) header.
RFC5322_SPECIALS = set('()<>@,:;."[]\\')


def has_specials(text):
    """Return True if text includes any RFC 5322 special characters."""
    return not set(text).isdisjoint(RFC5322_SPECIALS)


def quote_string(name, force=False):
    """
    Wrap name as an RFC 5322 quoted-string if necessary (or unconditionally if force).
    """
    # Adapted from email._header_value_parser.quote_string().
    if force or has_specials(name):
        escaped = str(name).replace("\\", "\\\\").replace('"', r"\"")
        return f'"{escaped}"'
    return name


def unquote_string(name):
    """
    If name is an RFC 5322 quoted-string, return unquoted (and unescaped) value.
    """
    if name.startswith('"') and name.endswith('"'):
        return name[1:-1].replace("\\\\", "\\").replace('\\"', '"')
    return name


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
