# Tests for the anymail/utils.py module
# (not to be confused with utilities for testing found in tests/utils.py)
import base64
import copy
import pickle
from email.mime.image import MIMEImage
from email.mime.text import MIMEText

from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy

from anymail._idna import idna2008
from anymail.exceptions import AnymailInvalidAddress, _LazyError
from anymail.utils import (
    UNSET,
    Attachment,
    CaseInsensitiveCasePreservingDict,
    EmailAddress,
    concat_lists,
    force_non_lazy,
    force_non_lazy_dict,
    force_non_lazy_list,
    get_request_basic_auth,
    get_request_uri,
    has_specials,
    is_lazy,
    last,
    merge_dicts_deep,
    merge_dicts_one_level,
    merge_dicts_shallow,
    parse_address_list,
    parse_rfc2822date,
    parse_single_address,
    querydict_getfirst,
    quote_string,
    rfc2047_decode,
    rfc2047_encode,
    unquote_string,
    update_deep,
)


class ParseAddressListTests(SimpleTestCase):
    """Test utils.parse_address_list"""

    def test_simple_email(self):
        parsed_list = parse_address_list(["test@example.com"])
        self.assertEqual(len(parsed_list), 1)
        parsed = parsed_list[0]
        self.assertIsInstance(parsed, EmailAddress)
        self.assertEqual(parsed.addr_spec, "test@example.com")
        self.assertEqual(parsed.display_name, "")
        self.assertEqual(parsed.address, "test@example.com")
        self.assertEqual(parsed.username, "test")
        self.assertEqual(parsed.domain, "example.com")

    def test_display_name(self):
        parsed_list = parse_address_list(['"Display Name, Inc." <test@example.com>'])
        self.assertEqual(len(parsed_list), 1)
        parsed = parsed_list[0]
        self.assertEqual(parsed.addr_spec, "test@example.com")
        self.assertEqual(parsed.display_name, "Display Name, Inc.")
        self.assertEqual(parsed.address, '"Display Name, Inc." <test@example.com>')
        self.assertEqual(parsed.username, "test")
        self.assertEqual(parsed.domain, "example.com")

    def test_obsolete_display_name(self):
        # you can get away without the quotes if there are no commas or parens
        # (but it's not recommended)
        parsed_list = parse_address_list(["Display Name <test@example.com>"])
        self.assertEqual(len(parsed_list), 1)
        parsed = parsed_list[0]
        self.assertEqual(parsed.addr_spec, "test@example.com")
        self.assertEqual(parsed.display_name, "Display Name")
        self.assertEqual(parsed.address, "Display Name <test@example.com>")

    def test_unicode_display_name(self):
        parsed_list = parse_address_list(
            ['"Unicode \N{HEAVY BLACK HEART}" <test@example.com>']
        )
        self.assertEqual(len(parsed_list), 1)
        parsed = parsed_list[0]
        self.assertEqual(parsed.addr_spec, "test@example.com")
        self.assertEqual(parsed.display_name, "Unicode \N{HEAVY BLACK HEART}")
        # formatted display-name automatically shifts
        # to quoted-printable/base64 for non-ascii chars:
        self.assertEqual(
            parsed.address, "Unicode \N{HEAVY BLACK HEART} <test@example.com>"
        )

    def test_invalid_display_name(self):
        with self.assertRaisesMessage(
            AnymailInvalidAddress, "Invalid email address 'webmaster'"
        ):
            parse_address_list(["webmaster"])

        with self.assertRaisesMessage(
            AnymailInvalidAddress, "maybe missing quotes around a display-name?"
        ):
            # this parses as multiple email addresses, because of the comma:
            parse_address_list(["Display Name, Inc. <test@example.com>"])

    def test_idn(self):
        parsed_list = parse_address_list(["idn@\N{ENVELOPE}.example.com"])
        self.assertEqual(len(parsed_list), 1)
        parsed = parsed_list[0]
        self.assertEqual(parsed.addr_spec, "idn@\N{ENVELOPE}.example.com")
        # No attempt to apply IDNA to domain (leave that to the backend):
        self.assertEqual(parsed.address, "idn@\N{ENVELOPE}.example.com")
        self.assertEqual(parsed.username, "idn")
        self.assertEqual(parsed.domain, "\N{ENVELOPE}.example.com")

    def test_none_address(self):
        # used for, e.g., telling Mandrill to use template default from_email
        self.assertEqual(parse_address_list([None]), [])
        self.assertEqual(parse_address_list(None), [])

    def test_empty_address(self):
        with self.assertRaises(AnymailInvalidAddress):
            parse_address_list([""])

    def test_whitespace_only_address(self):
        with self.assertRaises(AnymailInvalidAddress):
            parse_address_list([" "])

    def test_invalid_address(self):
        invalid_addresses = [
            "localonly",
            "localonly@",
            "@domainonly",
            "<localonly@>",
            "<@domainonly>",
        ]
        for address in invalid_addresses:
            with self.subTest(address=address):
                with self.assertRaises(AnymailInvalidAddress):
                    parse_address_list([address])

    def test_email_list(self):
        parsed_list = parse_address_list(["first@example.com", "second@example.com"])
        self.assertEqual(len(parsed_list), 2)
        self.assertEqual(parsed_list[0].addr_spec, "first@example.com")
        self.assertEqual(parsed_list[1].addr_spec, "second@example.com")

    def test_multiple_emails(self):
        # Django's EmailMessage allows multiple, comma-separated emails
        # in a single recipient string. (It passes them along to the backend intact.)
        # (Depending on this behavior is not recommended.)
        parsed_list = parse_address_list(["first@example.com, second@example.com"])
        self.assertEqual(len(parsed_list), 2)
        self.assertEqual(parsed_list[0].addr_spec, "first@example.com")
        self.assertEqual(parsed_list[1].addr_spec, "second@example.com")

    def test_invalid_in_list(self):
        # Make sure it's not just concatenating list items...
        # the bare "Display Name" below should *not* get merged with
        # the email in the second item
        with self.assertRaisesMessage(AnymailInvalidAddress, "Display Name"):
            parse_address_list(['"Display Name"', "<valid@example.com>"])

    def test_invalid_with_unicode(self):
        with self.assertRaisesMessage(
            AnymailInvalidAddress, "Invalid email address '\N{ENVELOPE}'"
        ):
            parse_address_list(["\N{ENVELOPE}"])

    def test_single_string(self):
        # bare strings are used by the from_email parsing in BasePayload
        parsed_list = parse_address_list("one@example.com")
        self.assertEqual(len(parsed_list), 1)
        self.assertEqual(parsed_list[0].addr_spec, "one@example.com")

    def test_lazy_strings(self):
        parsed_list = parse_address_list(
            [gettext_lazy('"Example, Inc." <one@example.com>')]
        )
        self.assertEqual(len(parsed_list), 1)
        self.assertEqual(parsed_list[0].display_name, "Example, Inc.")
        self.assertEqual(parsed_list[0].addr_spec, "one@example.com")

        parsed_list = parse_address_list(gettext_lazy("one@example.com"))
        self.assertEqual(len(parsed_list), 1)
        self.assertEqual(parsed_list[0].display_name, "")
        self.assertEqual(parsed_list[0].addr_spec, "one@example.com")

    def test_parse_one(self):
        parsed = parse_single_address("one@example.com")
        self.assertEqual(parsed.address, "one@example.com")

        with self.assertRaisesMessage(
            AnymailInvalidAddress, "Only one email address is allowed; found 2"
        ):
            parse_single_address("one@example.com, two@example.com")

        with self.assertRaisesMessage(AnymailInvalidAddress, "Invalid email address"):
            parse_single_address(" ")


class EmailAddressTests(SimpleTestCase):
    """Test utils.EmailAddress"""

    def test_no_newlines(self):
        for name, addr in [
            ("Potential\nInjection", "addr@example.com"),
            ("Potential\rInjection", "addr@example.com"),
            ("Name", "potential\ninjection@example.com"),
            ("Name", "potential\rinjection@example.com"),
        ]:
            with self.subTest(name=name, addr=addr):
                with self.assertRaisesMessage(
                    AnymailInvalidAddress, "cannot contain CR or LF"
                ):
                    _ = EmailAddress(name, addr)

    def test_repr(self):
        self.assertEqual(
            "EmailAddress('Name', 'addr@example.com')",
            repr(EmailAddress("Name", "addr@example.com")),
        )

    def test_address_property(self):
        cases = [
            # display_name, addr_spec, expected
            ("John Smith", "john@example.com", "John Smith <john@example.com>"),
            ("Smith, John", "john@example.com", '"Smith, John" <john@example.com>'),
            ("Juan Lopéz", "juan@example.com", "Juan Lopéz <juan@example.com>"),
            (None, "juan@éxample.com", "juan@éxample.com"),
            ("Juan Lopéz", "juan@éxample.com", "Juan Lopéz <juan@éxample.com>"),
            (None, "maría@example.com", "maría@example.com"),
            ("María Lopéz", "maría@éxample.com", "María Lopéz <maría@éxample.com>"),
        ]
        for display_name, addr_spec, expected in cases:
            with self.subTest(display_name=display_name, addr_spec=addr_spec):
                email = EmailAddress(display_name, addr_spec)
                self.assertEqual(email.address, expected)

    def test_format_display_name(self):
        cases = [
            # display_name, format_display_name() kwargs, expected
            ("John Smith", {}, "John Smith"),
            ("Smith, John", {}, "Smith, John"),
            # use_quotes
            ("Smith, John", {"use_quotes": True}, '"Smith, John"'),
            ("John Smith", {"use_quotes": True}, "John Smith"),
            ("John Smith", {"use_quotes": "force"}, '"John Smith"'),
            # use_rfc2047
            ("Juan Lopéz", {}, "Juan Lopéz"),
            ("Juan Lopéz", {"use_rfc2047": True}, "=?utf-8?q?Juan_Lop=C3=A9z?="),
            ("John Smith", {"use_rfc2047": True}, "John Smith"),
            ("John Smith", {"use_rfc2047": "force"}, "=?utf-8?q?John_Smith?="),
            # rfc2047 is never quoted
            (
                "Juan Lopéz",
                {"use_rfc2047": True, "use_quotes": True},
                "=?utf-8?q?Juan_Lop=C3=A9z?=",
            ),
            (
                "Lopéz, Juan Carlo",
                {"use_rfc2047": True, "use_quotes": True},
                "=?utf-8?q?Lop=C3=A9z=2C_Juan_Carlo?=",
            ),
            (
                "Juan Lopéz",
                {"use_rfc2047": True, "use_quotes": "force"},
                "=?utf-8?q?Juan_Lop=C3=A9z?=",
            ),
            (
                "John Smith",
                {"use_rfc2047": "force", "use_quotes": "force"},
                "=?utf-8?q?John_Smith?=",
            ),
            # Corner cases
            ("", {}, ""),
            ("", {"use_quotes": "force"}, '""'),
        ]
        for display_name, args, expected in cases:
            with self.subTest(display_name=display_name, args=args):
                email = EmailAddress(display_name, "user@example.com")
                result = email.format_display_name(**args)
                self.assertEqual(result, expected)

    def test_format_addr_spec(self):
        cases = [
            # addr_spec, format_addr_spec() kwargs, expected
            ("user@example.com", {}, "user@example.com"),
            ("user@exämple.com", {}, "user@exämple.com"),
            ("user@example.com", {"idna_encode": idna2008}, "user@example.com"),
            (
                "user@exämple.com",
                {"idna_encode": idna2008},
                "user@xn--exmple-cua.com",
            ),
            ("user+tag@example.com", {}, "user+tag@example.com"),
            ('"user@example.net"@example.com', {}, '"user@example.net"@example.com'),
            ("üser@exämple.com", {}, "üser@exämple.com"),
            (
                "üser@exämple.com",
                {"idna_encode": idna2008},
                "üser@xn--exmple-cua.com",
            ),
        ]
        for addr_spec, args, expected in cases:
            with self.subTest(addr_spec=addr_spec, args=args):
                email = EmailAddress(addr_spec=addr_spec)
                result = email.format_addr_spec(**args)
                self.assertEqual(result, expected)

    def test_format(self):
        cases = [
            # email, format() kwargs, expected
            (
                EmailAddress("John Smith", "john@example.com"),
                {},
                "John Smith <john@example.com>",
            ),
            (
                EmailAddress("Smith, John", "john@example.com"),
                {},
                '"Smith, John" <john@example.com>',
            ),
            (
                EmailAddress("", "john@example.com"),
                {},
                "john@example.com",
            ),
            (
                EmailAddress("Juan Lopéz", "juan@example.com"),
                {},
                "Juan Lopéz <juan@example.com>",
            ),
            (
                EmailAddress("Lopéz, Juan", "juan@example.com"),
                {},
                '"Lopéz, Juan" <juan@example.com>',
            ),
            (
                EmailAddress("", "user@exämple.com"),
                {},
                "user@exämple.com",
            ),
            # RFC 2047
            (
                EmailAddress("Juan Lopéz", "juan@example.com"),
                {"use_rfc2047": True},
                "=?utf-8?q?Juan_Lop=C3=A9z?= <juan@example.com>",
            ),
            (
                EmailAddress("John Smith", "john@example.com"),
                {"use_rfc2047": True},
                "John Smith <john@example.com>",
            ),
            (
                EmailAddress("John Smith", "john@example.com"),
                {"use_rfc2047": "force"},
                "=?utf-8?q?John_Smith?= <john@example.com>",
            ),
            # IDNA
            (
                EmailAddress("", "user@exämple.com"),
                {"idna_encode": idna2008},
                "user@xn--exmple-cua.com",
            ),
            (
                EmailAddress("", "user@example.com"),
                {"idna_encode": idna2008},
                "user@example.com",
            ),
            (
                EmailAddress("John Smith", "user@exämple.com"),
                {"idna_encode": idna2008},
                "John Smith <user@xn--exmple-cua.com>",
            ),
            # Combinations
            (
                EmailAddress("Juan Lopéz", "user@exämple.com"),
                {"use_rfc2047": True, "idna_encode": idna2008},
                "=?utf-8?q?Juan_Lop=C3=A9z?= <user@xn--exmple-cua.com>",
            ),
        ]

        for email, args, expected in cases:
            with self.subTest(email=email, args=args):
                self.assertEqual(email.format(**args), expected)

    def test_as_dict(self):
        cases = [
            # email, kwargs, expected
            (
                EmailAddress("John Smith", "john@example.com"),
                {},
                {"name": "John Smith", "email": "john@example.com"},
            ),
            (
                EmailAddress(None, "john@example.com"),
                {},
                {"email": "john@example.com"},
            ),
            (
                EmailAddress("John Smith", "john@example.com"),
                {"name": "Name", "email": "Address"},
                {"Name": "John Smith", "Address": "john@example.com"},
            ),
            (
                EmailAddress("Smith, John", "john@example.com"),
                {"quote_name": True},
                {"name": '"Smith, John"', "email": "john@example.com"},
            ),
            (
                EmailAddress("Juan Lopéz", "juan@éxample.com"),
                {"idna_encode": idna2008},
                {"name": "Juan Lopéz", "email": "juan@xn--xample-9ua.com"},
            ),
            (
                EmailAddress("Juan Lopéz", "juan@example.com"),
                {"use_rfc2047": True},
                {"name": "=?utf-8?q?Juan_Lop=C3=A9z?=", "email": "juan@example.com"},
            ),
            (
                EmailAddress("John Smith", "john@example.com"),
                {"use_rfc2047": "force"},
                {"name": "=?utf-8?q?John_Smith?=", "email": "john@example.com"},
            ),
            (
                EmailAddress("John Smith", "john@exämple.com"),
                {"quote_name": "force", "idna_encode": idna2008},
                {"name": '"John Smith"', "email": "john@xn--exmple-cua.com"},
            ),
        ]
        for email, kwargs, expected in cases:
            with self.subTest(email=email, args=kwargs):
                result = email.as_dict(**kwargs)
                self.assertEqual(result, expected)

    def test_long_unicode(self):
        # (Earlier implementations using Django's sanitize_address could incorrectly
        # introduce folding in the formatted address.)
        display_name = (
            "* * * 💲 Snag Your Free Gift! Click Here:"
            " https://spam.example.com/uploads/spammy.php?spammy 💲 * * * 8v1e8k"
        )
        address = EmailAddress(display_name, "addr@example.com")
        self.assertNotIn("\n", str(address))

    def test_uses_eai(self):
        cases = [
            (EmailAddress(addr_spec="j.lópez@example.com"), True),
            (EmailAddress(addr_spec="j.lopez@example.com"), False),
            (EmailAddress(addr_spec="john@exämple.com"), False),
            (EmailAddress(display_name="Jörg", addr_spec="jorg@example.com"), False),
            (EmailAddress(display_name="Jörg", addr_spec="jörg@example.com"), True),
        ]
        for email, expected in cases:
            with self.subTest(email=email):
                self.assertIs(email.uses_eai, expected)


class RFC2047Tests(SimpleTestCase):
    cases = [
        # text, encoded
        ("ascii text", "=?utf-8?q?ascii_text?="),
        ("Café", "=?utf-8?b?Q2Fmw6k=?="),
        ("Café Florence", "=?utf-8?q?Caf=C3=A9_Florence?="),
        ("こんにちは", "=?utf-8?b?44GT44KT44Gr44Gh44Gv?="),
        ("Hello, World!", "=?utf-8?q?Hello=2C_World!?="),
        ("", ""),
    ]

    decode_only_cases = [
        # Cases where `encoded` is a valid representation of `text`,
        # but not the one used by rfc2047_encode().
        # text, encoded
        ("Café Florence", "=?utf-8?q?Caf=C3=A9?= Florence"),
        ("Café Florence", "=?utf-8?q?Caf=C3=A9?= =?utf-8?q?_Florence?="),
        ("Café Florence", "Café Florence"),
        (
            "Café Café Café",
            "=?utf-8?q?Caf=C3=A9_?= =?iso-8859-1?q?Caf=E9_?= =?utf-8?b?Q2Fmw6k=?=",
        ),
    ]

    def test_rfc2047_encode(self):
        for text, expected in self.cases:
            with self.subTest(text=text):
                result = rfc2047_encode(text)
                self.assertEqual(result, expected)

    def test_rfc2047_decode(self):
        for text, encoded in self.cases + self.decode_only_cases:
            with self.subTest(encoded=encoded):
                result = rfc2047_decode(encoded)
                self.assertEqual(result, text)


class TestQuoting(SimpleTestCase):
    def test_has_specials(self):
        cases = [
            # (value, expected)
            ("", False),
            ("Abc's åßç & $%=*+_^#! \t", False),
            ("1, 2", True),
            ("<3", True),
            (">", True),
            ("foo@bar@baz", True),
            ("(Remark", True),
            (")", True),
            ('"dquote"', True),
            ("back\\slash", True),
            (";", True),
            (".", True),
            (":", True),
            ("[bracket", True),
            ("]", True),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                result = has_specials(value)
                self.assertIs(result, expected)

    def test_quote_display_name(self):
        cases = [
            # name, expected
            ("John Doe", "John Doe"),
            ("John, Doe", '"John, Doe"'),
            ("Juan Lopéz", "Juan Lopéz"),
            ("Lopéz, Juan", '"Lopéz, Juan"'),
            ('Name "Namey"', r'"Name \"Namey\""'),
            (r"John\Doe", r'"John\\Doe"'),
            (r'"John\"Doe', r'"\"John\\\"Doe"'),
            ("Name <Namey>", '"Name <Namey>"'),
            ("Name@Email", '"Name@Email"'),
            ("Name: Details;", '"Name: Details;"'),
            ("(Remark)", '"(Remark)"'),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                result = quote_string(name)
                self.assertEqual(result, expected)

    def test_quote_display_name_force(self):
        cases = [
            # name, expected (with force=True)
            ("John Doe", '"John Doe"'),
            ("Juan Lopéz", '"Juan Lopéz"'),
            ('John "Doe"', r'"John \"Doe\""'),
        ]
        for name, expected in cases:
            with self.subTest(name=name):
                result = quote_string(name, force=True)
                self.assertEqual(result, expected)

    def test_unquote_string(self):
        cases = [
            # quoted, expected
            ('"John Doe"', "John Doe"),
            ("John Doe", "John Doe"),
            (
                r'"inline \"quotes\" and \\backslashes"',
                r'inline "quotes" and \backslashes',
            ),
            # Doesn't touch angle brackets (unlike email.utils.unquote)
            ('"<foo@bar>"', "<foo@bar>"),
            ("<foo@bar>", "<foo@bar>"),
            # Corner cases
            ('"', ""),
            ("", ""),
        ]
        for quoted, expected in cases:
            with self.subTest(quoted=quoted):
                result = unquote_string(quoted)
                self.assertEqual(result, expected)


class NormalizedAttachmentTests(SimpleTestCase):
    """Test utils.Attachment"""

    # (Several basic tests could be added here)

    def test_content_disposition_attachment(self):
        image = MIMEImage(b";-)", "x-emoticon")
        image["Content-Disposition"] = 'attachment; filename="emoticon.txt"'
        att = Attachment(image, "ascii")
        self.assertEqual(att.name, "emoticon.txt")
        self.assertEqual(att.content, b";-)")
        self.assertFalse(att.inline)
        self.assertIsNone(att.content_id)
        self.assertEqual(att.cid, "")
        self.assertEqual(
            repr(att), "Attachment<image/x-emoticon, len=3, name='emoticon.txt'>"
        )

    def test_content_disposition_inline(self):
        image = MIMEImage(b";-)", "x-emoticon")
        image["Content-Disposition"] = "inline"
        att = Attachment(image, "ascii")
        self.assertIsNone(att.name)
        self.assertEqual(att.content, b";-)")
        self.assertTrue(att.inline)  # even without the Content-ID
        self.assertIsNone(att.content_id)
        self.assertEqual(att.cid, "")
        self.assertEqual(
            repr(att), "Attachment<inline, image/x-emoticon, len=3, content_id=None>"
        )

        image["Content-ID"] = "<abc123@example.net>"
        att = Attachment(image, "ascii")
        self.assertEqual(att.content_id, "<abc123@example.net>")
        self.assertEqual(att.cid, "abc123@example.net")
        self.assertEqual(
            repr(att),
            "Attachment<inline, image/x-emoticon, len=3,"
            " content_id='<abc123@example.net>'>",
        )

    def test_content_id_implies_inline(self):
        """A MIME object with a Content-ID should be assumed to be inline"""
        image = MIMEImage(b";-)", "x-emoticon")
        image["Content-ID"] = "<abc123@example.net>"
        att = Attachment(image, "ascii")
        self.assertTrue(att.inline)
        self.assertEqual(att.content_id, "<abc123@example.net>")
        self.assertEqual(
            repr(att),
            "Attachment<inline, image/x-emoticon, len=3,"
            " content_id='<abc123@example.net>'>",
        )

        # ... but not if explicit Content-Disposition says otherwise
        image["Content-Disposition"] = "attachment"
        att = Attachment(image, "ascii")
        self.assertFalse(att.inline)
        self.assertIsNone(att.content_id)  # ignored for non-inline Attachment
        self.assertEqual(repr(att), "Attachment<image/x-emoticon, len=3>")

    def test_content_type(self):
        att = Attachment(MIMEText("text", "plain", "iso8859-1"), "ascii")
        self.assertEqual(att.mimetype, "text/plain")
        self.assertEqual(att.content_type, 'text/plain; charset="iso8859-1"')
        self.assertEqual(repr(att), "Attachment<text/plain, len=4>")


class LazyCoercionTests(SimpleTestCase):
    """Test utils.is_lazy and force_non_lazy*"""

    def test_is_lazy(self):
        self.assertTrue(is_lazy(gettext_lazy("lazy string is lazy")))

    def test_not_lazy(self):
        self.assertFalse(is_lazy("text not lazy"))
        self.assertFalse(is_lazy(b"bytes not lazy"))
        self.assertFalse(is_lazy(None))
        self.assertFalse(is_lazy({"dict": "not lazy"}))
        self.assertFalse(is_lazy(["list", "not lazy"]))
        self.assertFalse(is_lazy(object()))
        self.assertFalse(is_lazy([gettext_lazy("doesn't recurse")]))

    def test_force_lazy(self):
        result = force_non_lazy(gettext_lazy("text"))
        self.assertIsInstance(result, str)
        self.assertEqual(result, "text")

    def test_format_lazy(self):
        self.assertTrue(
            is_lazy(
                format_lazy(
                    "{0}{1}", gettext_lazy("concatenation"), gettext_lazy("is lazy")
                )
            )
        )
        result = force_non_lazy(
            format_lazy(
                "{first}/{second}",
                first=gettext_lazy("text"),
                second=gettext_lazy("format"),
            )
        )
        self.assertIsInstance(result, str)
        self.assertEqual(result, "text/format")

    def test_force_string(self):
        result = force_non_lazy("text")
        self.assertIsInstance(result, str)
        self.assertEqual(result, "text")

    def test_force_bytes(self):
        result = force_non_lazy(b"bytes \xFE")
        self.assertIsInstance(result, bytes)
        self.assertEqual(result, b"bytes \xFE")

    def test_force_none(self):
        result = force_non_lazy(None)
        self.assertIsNone(result)

    def test_force_dict(self):
        result = force_non_lazy_dict(
            {"a": 1, "b": gettext_lazy("b"), "c": {"c1": gettext_lazy("c1")}}
        )
        self.assertEqual(result, {"a": 1, "b": "b", "c": {"c1": "c1"}})
        self.assertIsInstance(result["b"], str)
        self.assertIsInstance(result["c"]["c1"], str)

    def test_force_list(self):
        result = force_non_lazy_list([0, gettext_lazy("b"), "c"])
        self.assertEqual(result, [0, "b", "c"])  # coerced to list
        self.assertIsInstance(result[1], str)


class UpdateDeepTests(SimpleTestCase):
    """Test utils.update_deep"""

    def test_updates_recursively(self):
        first = {"a": {"a1": 1, "aa": {}}, "b": "B"}
        second = {"a": {"a2": 2, "aa": {"aa1": 11}}}
        result = update_deep(first, second)
        self.assertEqual(first, {"a": {"a1": 1, "a2": 2, "aa": {"aa1": 11}}, "b": "B"})
        # modifies first in place; doesn't return it (same as dict.update()):
        self.assertIsNone(result)

    def test_overwrites_sequences(self):
        """Only mappings are handled recursively; sequences are considered atomic"""
        first = {"a": [1, 2]}
        second = {"a": [3]}
        update_deep(first, second)
        self.assertEqual(first, {"a": [3]})

    def test_handles_non_dict_mappings(self):
        """Mapping types in general are supported"""
        from collections import OrderedDict, defaultdict

        first = OrderedDict(a=OrderedDict(a1=1), c={"c1": 1})
        second = defaultdict(None, a=dict(a2=2))
        update_deep(first, second)
        self.assertEqual(first, {"a": {"a1": 1, "a2": 2}, "c": {"c1": 1}})


@override_settings(ALLOWED_HOSTS=[".example.com"])
class RequestUtilsTests(SimpleTestCase):
    """Test utils.get_request_* helpers"""

    def setUp(self):
        self.request_factory = RequestFactory()
        super().setUp()

    @staticmethod
    def basic_auth(username, password):
        """
        Return HTTP_AUTHORIZATION header value for basic auth with username, password
        """
        credentials = base64.b64encode(
            "{}:{}".format(username, password).encode("utf-8")
        ).decode("utf-8")
        return "Basic {}".format(credentials)

    def test_get_request_basic_auth(self):
        # without auth:
        request = self.request_factory.post(
            "/path/to/?query", HTTP_HOST="www.example.com", HTTP_SCHEME="https"
        )
        self.assertIsNone(get_request_basic_auth(request))

        # with basic auth:
        request = self.request_factory.post(
            "/path/to/?query",
            HTTP_HOST="www.example.com",
            HTTP_AUTHORIZATION=self.basic_auth("user", "pass"),
        )
        self.assertEqual(get_request_basic_auth(request), "user:pass")

        # with some other auth
        request = self.request_factory.post(
            "/path/to/?query",
            HTTP_HOST="www.example.com",
            HTTP_AUTHORIZATION="Bearer abcde12345",
        )
        self.assertIsNone(get_request_basic_auth(request))

    def test_get_request_uri(self):
        # without auth:
        request = self.request_factory.post(
            "/path/to/?query", secure=True, HTTP_HOST="www.example.com"
        )
        self.assertEqual(
            get_request_uri(request), "https://www.example.com/path/to/?query"
        )

        # with basic auth:
        request = self.request_factory.post(
            "/path/to/?query",
            secure=True,
            HTTP_HOST="www.example.com",
            HTTP_AUTHORIZATION=self.basic_auth("user", "pass"),
        )
        self.assertEqual(
            get_request_uri(request), "https://user:pass@www.example.com/path/to/?query"
        )

    @override_settings(
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
        USE_X_FORWARDED_HOST=True,
    )
    def test_get_request_uri_with_proxy(self):
        request = self.request_factory.post(
            "/path/to/?query",
            secure=False,
            HTTP_HOST="web1.internal",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_X_FORWARDED_HOST="secret.example.com:8989",
            HTTP_AUTHORIZATION=self.basic_auth("user", "pass"),
        )
        self.assertEqual(
            get_request_uri(request),
            "https://user:pass@secret.example.com:8989/path/to/?query",
        )


class QueryDictUtilsTests(SimpleTestCase):
    def test_querydict_getfirst(self):
        q = QueryDict("a=one&a=two&a=three")
        q.getfirst = querydict_getfirst.__get__(q)
        self.assertEqual(q.getfirst("a"), "one")

        # missing key exception:
        with self.assertRaisesMessage(KeyError, "not a key"):
            q.getfirst("not a key")

        # defaults:
        self.assertEqual(q.getfirst("not a key", "beta"), "beta")
        self.assertIsNone(q.getfirst("not a key", None))


class ParseRFC2822DateTests(SimpleTestCase):
    def test_with_timezones(self):
        dt = parse_rfc2822date("Tue, 24 Oct 2017 10:11:35 -0700")
        self.assertEqual(dt.isoformat(), "2017-10-24T10:11:35-07:00")
        self.assertIsNotNone(dt.utcoffset())  # aware

        dt = parse_rfc2822date("Tue, 24 Oct 2017 10:11:35 +0700")
        self.assertEqual(dt.isoformat(), "2017-10-24T10:11:35+07:00")
        self.assertIsNotNone(dt.utcoffset())  # aware

        dt = parse_rfc2822date("Tue, 24 Oct 2017 10:11:35 +0000")
        self.assertEqual(dt.isoformat(), "2017-10-24T10:11:35+00:00")
        self.assertIsNotNone(dt.tzinfo)  # aware

    def test_without_timezones(self):
        # "no timezone information":
        dt = parse_rfc2822date("Tue, 24 Oct 2017 10:11:35 -0000")
        self.assertEqual(dt.isoformat(), "2017-10-24T10:11:35")
        # naive (compare with +0000 version in previous test):
        self.assertIsNone(dt.tzinfo)

        dt = parse_rfc2822date("Tue, 24 Oct 2017 10:11:35")
        self.assertEqual(dt.isoformat(), "2017-10-24T10:11:35")
        self.assertIsNone(dt.tzinfo)  # naive

    def test_unparseable_dates(self):
        self.assertIsNone(parse_rfc2822date(""))
        self.assertIsNone(parse_rfc2822date("  "))
        self.assertIsNone(parse_rfc2822date("garbage"))
        self.assertIsNone(parse_rfc2822date("Tue, 24 Oct"))
        self.assertIsNone(parse_rfc2822date("Lug, 24 Nod 2017 10:11:35 +0000"))
        self.assertIsNone(parse_rfc2822date("Tue, 99 Oct 9999 99:99:99 +9999"))


class LazyErrorTests(SimpleTestCase):
    def test_attr(self):
        lazy = _LazyError(ValueError("lazy failure"))  # creating doesn't cause error
        lazy.some_prop = "foo"  # setattr doesn't cause error
        with self.assertRaisesMessage(ValueError, "lazy failure"):
            self.unused = lazy.anything  # getattr *does* cause error

    def test_call(self):
        lazy = _LazyError(ValueError("lazy failure"))  # creating doesn't cause error
        with self.assertRaisesMessage(ValueError, "lazy failure"):
            self.unused = lazy()  # call *does* cause error


class CaseInsensitiveCasePreservingDictTests(SimpleTestCase):
    def setUp(self):
        self.dict = CaseInsensitiveCasePreservingDict()
        self.dict["Accept"] = "application/text+xml"
        self.dict["accEPT"] = "application/json"

    def test_preserves_first_key(self):
        self.assertEqual(list(self.dict.keys()), ["Accept"])

    def test_copy(self):
        copy = self.dict.copy()
        self.assertIsNot(copy, self.dict)
        self.assertEqual(copy, self.dict)
        # Here's why the superclass CaseInsensitiveDict.copy is insufficient:
        self.assertIsInstance(copy, CaseInsensitiveCasePreservingDict)

    def test_get_item(self):
        self.assertEqual(self.dict["accept"], "application/json")
        self.assertEqual(self.dict["Accept"], "application/json")
        self.assertEqual(self.dict["accEPT"], "application/json")

    # The base CaseInsensitiveDict functionality is well-tested in Requests,
    # so we don't repeat it here.


class UnsetValueTests(SimpleTestCase):
    """Tests for the UNSET sentinel value"""

    def test_not_other_values(self):
        self.assertIsNot(UNSET, None)
        self.assertIsNot(UNSET, False)
        self.assertNotEqual(UNSET, 0)
        self.assertNotEqual(UNSET, "")

    def test_unset_survives_pickle(self):
        # Required for using AnymailMessage with django-mailer
        pickled = pickle.dumps(UNSET)
        self.assertIs(pickle.loads(pickled), UNSET)

    def test_unset_survives_copy(self):
        self.assertIs(copy.copy(UNSET), UNSET)
        self.assertIs(copy.deepcopy(UNSET), UNSET)

    def test_unset_has_useful_repr(self):
        # (something better than '<object object at ...>')
        self.assertIn("UNSET", repr(UNSET))

    def test_equality(self):
        # `is UNSET` is preferred to `== UNSET`, but both should work
        self.assertEqual(UNSET, UNSET)


class CombinerTests(SimpleTestCase):
    def test_concat_lists(self):
        for args, expected in [
            (([1, 2], [3, 4]), [1, 2, 3, 4]),
            # Does not flatten:
            (([1, [11, 12]], [2]), [1, [11, 12], 2]),
            # UNSET args ignored:
            ((UNSET, [1, 2], UNSET, [3, 4], UNSET), [1, 2, 3, 4]),
            # None clears previous:
            (([1, 2], None, [3, 4]), [3, 4]),
            # Works with other sequence-like types:
            (([1], (2, 3), {4}), [1, 2, 3, 4]),
            # Degenerate cases:
            ((), UNSET),
            ((UNSET,), UNSET),
            ((None,), UNSET),
            (([], None), UNSET),
        ]:
            with self.subTest(repr(args)):
                original_args = copy.deepcopy(args)
                merged = concat_lists(*args)
                self.assertEqual(merged, expected)
                # Verify args were not modified:
                self.assertEqual(args, original_args)

    def test_merge_dicts_shallow(self):
        for args, expected in [
            (({"a": 1}, {"b": 2}), {"a": 1, "b": 2}),
            (
                ({"a": 1, "b": 2}, {"a": 11, "c": 33}, {"c": 3}),
                {"a": 11, "b": 2, "c": 3},
            ),
            # shallow merge:
            (({"a": {"a1": 1}, "b": 2}, {"a": {"a2": 2}}), {"a": {"a2": 2}, "b": 2}),
            # UNSET args ignored:
            ((UNSET, {"a": 1}, UNSET, {"b": 2}, UNSET), {"a": 1, "b": 2}),
            # None clears previous:
            (({"a": 1}, None, {"b": 2}), {"b": 2}),
            # Degenerate cases:
            ((), UNSET),
            ((UNSET,), UNSET),
            ((None,), UNSET),
            (({}, None), UNSET),
        ]:
            with self.subTest(repr(args)):
                original_args = copy.deepcopy(args)
                merged = merge_dicts_shallow(*args)
                self.assertEqual(merged, expected)
                # Verify args were not modified:
                self.assertEqual(args, original_args)

    def test_merge_dicts_deep(self):
        for args, expected in [
            (({"a": 1}, {"b": 2}), {"a": 1, "b": 2}),
            (
                ({"a": 1, "b": 2}, {"a": 11, "c": 33}, {"c": 3}),
                {"a": 11, "b": 2, "c": 3},
            ),
            # deep merge:
            (
                (
                    {"a": {"a1": 1, "a3": {"a3a": 31}}},
                    {"a": {"a2": 2, "a3": {"a3b": 32}}},
                ),
                {"a": {"a1": 1, "a2": 2, "a3": {"a3a": 31, "a3b": 32}}},
            ),
            # UNSET (top-level) args ignored:
            ((UNSET, {"a": 1}, UNSET, {"b": 2}, UNSET), {"a": 1, "b": 2}),
            # None clears previous:
            (({"a": 1}, None, {"b": 2}), {"b": 2}),
            # Degenerate cases:
            ((), UNSET),
            ((UNSET,), UNSET),
            ((None,), UNSET),
            (({}, None), UNSET),
        ]:
            with self.subTest(repr(args)):
                original_args = copy.deepcopy(args)
                merged = merge_dicts_deep(*args)
                self.assertEqual(merged, expected)
                # Verify args were not modified:
                self.assertEqual(args, original_args)

    def test_merge_dicts_one_level(self):
        for args, expected in [
            # one-level merge:
            (
                (
                    {"a": {"a1": 1, "a3": {"a3a": 31}}},
                    {"a": {"a2": 2, "a3": {"a3b": 32}}},
                ),
                {"a": {"a1": 1, "a2": 2, "a3": {"a3b": 32}}},  # but not a3a
            ),
            # UNSET (top-level) args ignored:
            ((UNSET, {"a": {}}, UNSET, {"b": {}}, UNSET), {"a": {}, "b": {}}),
            # None clears previous:
            (({"a": {}}, None, {"b": {}}), {"b": {}}),
            # Degenerate cases:
            ((), UNSET),
            ((UNSET,), UNSET),
            ((None,), UNSET),
            (({}, None), UNSET),
        ]:
            with self.subTest(repr(args)):
                original_args = copy.deepcopy(args)
                merged = merge_dicts_one_level(*args)
                self.assertEqual(merged, expected)
                # Verify args were not modified:
                self.assertEqual(args, original_args)

    def test_last(self):
        for args, expected in [
            ((1, 2, 3), 3),
            # UNSET args ignored:
            ((UNSET, 1, UNSET, 2, UNSET), 2),
            # None clears previous:
            ((1, 2, None), UNSET),
            # Degenerate cases:
            ((), UNSET),
            ((UNSET,), UNSET),
            ((None,), UNSET),
        ]:
            with self.subTest(repr(args)):
                original_args = copy.deepcopy(args)
                merged = last(*args)
                self.assertEqual(merged, expected)
                # Verify args were not modified:
                self.assertEqual(args, original_args)
