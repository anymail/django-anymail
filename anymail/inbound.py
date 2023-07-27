import warnings
from base64 import b64decode
from email.message import EmailMessage
from email.parser import BytesParser, Parser
from email.policy import default as default_policy
from email.utils import unquote

from django.core.files.uploadedfile import SimpleUploadedFile

from .exceptions import AnymailDeprecationWarning
from .utils import angle_wrap, parse_address_list, parse_rfc2822date


class AnymailInboundMessage(EmailMessage):
    """
    A normalized, parsed inbound email message.

    A subclass of email.message.EmailMessage, with some additional
    convenience properties.
    """

    # Why Python email.message.EmailMessage rather than django.core.mail.EmailMessage?
    # Django's EmailMessage is really intended for constructing a (limited subset of)
    # an EmailMessage to send; Python's EmailMessage is better designed for representing
    # arbitrary messages:
    #
    # * Python's EmailMessage is easily parsed from raw mime (which is an inbound format
    #   provided by many ESPs), and can accurately represent any mime email received
    # * Python's EmailMessage can represent repeated header fields (e.g., "Received")
    #   which are common in inbound messages
    # * Django's EmailMessage defaults a bunch of properties in ways that aren't helpful
    #   (e.g., from_email from settings)

    def __init__(self, *args, **kwargs):
        # Note: this must accept zero arguments,
        # for use with message_from_string (email.parser)
        super().__init__(*args, **kwargs)

        # Additional attrs provided by some ESPs:
        self.envelope_sender = None
        self.envelope_recipient = None
        self.stripped_text = None
        self.stripped_html = None
        self.spam_detected = None
        self.spam_score = None

    #
    # Convenience accessors
    #

    @property
    def from_email(self):
        """EmailAddress"""
        # equivalent to Python 3.2+ message['From'].addresses[0]
        from_email = self.get_address_header("From")
        if len(from_email) == 1:
            return from_email[0]
        elif len(from_email) == 0:
            return None
        else:
            # unusual, but technically-legal multiple-From; preserve list:
            return from_email

    @property
    def to(self):
        """list of EmailAddress objects from To header"""
        # equivalent to Python 3.2+ message['To'].addresses
        return self.get_address_header("To")

    @property
    def cc(self):
        """list of EmailAddress objects from Cc header"""
        # equivalent to Python 3.2+ message['Cc'].addresses
        return self.get_address_header("Cc")

    @property
    def bcc(self):
        """list of EmailAddress objects from Bcc header"""
        # equivalent to Python 3.2+ message['Bcc'].addresses
        return self.get_address_header("Bcc")

    @property
    def subject(self):
        """str value of Subject header, or None"""
        return self["Subject"]

    @property
    def date(self):
        """datetime.datetime from Date header, or None if missing/invalid"""
        # equivalent to Python 3.2+ message['Date'].datetime
        return self.get_date_header("Date")

    @property
    def text(self):
        """Contents of the (first) text/plain body part, or None"""
        return self._get_body_content("text/plain")

    @property
    def html(self):
        """Contents of the (first) text/html body part, or None"""
        return self._get_body_content("text/html")

    @property
    def attachments(self):
        """list of attachments (as MIMEPart objects); excludes inlines"""
        return [part for part in self.walk() if part.is_attachment()]

    @property
    def inlines(self):
        """list of inline parts (as MIMEPart objects)"""
        return [part for part in self.walk() if part.is_inline()]

    @property
    def inline_attachments(self):
        """DEPRECATED: use content_id_map instead"""
        warnings.warn(
            "inline_attachments has been renamed to content_id_map and will be removed"
            " in the near future.",
            AnymailDeprecationWarning,
        )

        return self.content_id_map

    @property
    def content_id_map(self):
        """dict of Content-ID: attachment (as MIMEPart objects)"""

        return {
            unquote(part["Content-ID"]): part
            for part in self.walk()
            if part.is_inline() and part["Content-ID"] is not None
        }

    def get_address_header(self, header):
        """
        Return the value of header parsed into a (possibly-empty)
        list of EmailAddress objects
        """
        values = self.get_all(header)
        if values is not None:
            if "".join(values).strip() == "":
                values = None
            else:
                values = parse_address_list(values)
        return values or []

    def get_date_header(self, header):
        """Return the value of header parsed into a datetime.date, or None"""
        value = self[header]
        if value is not None:
            value = parse_rfc2822date(value)
        return value

    def _get_body_content(self, content_type):
        # This doesn't handle as many corner cases as Python 3.6
        # email.message.EmailMessage.get_body, but should work correctly
        # for nearly all real-world inbound messages.
        # We're guaranteed to have `is_attachment` available, because all
        # AnymailInboundMessage parts should themselves be AnymailInboundMessage.
        for part in self.walk():
            if part.get_content_type() == content_type and not part.is_attachment():
                return part.get_content_text()
        return None

    def is_inline(self):
        return self.get_content_disposition() == "inline"

    # New for Anymail
    def is_inline_attachment(self):
        """DEPRECATED: use in_inline instead"""
        warnings.warn(
            "is_inline_attachment has been renamed to is_inline and will be removed"
            " in the near future.",
            AnymailDeprecationWarning,
        )

        return self.is_inline()

    def get_content_bytes(self):
        """Return the raw payload bytes"""
        maintype = self.get_content_maintype()
        if maintype == "message":
            # The attachment's payload is a single (parsed) email Message;
            # flatten it to bytes.
            # (Note that self.is_multipart() misleadingly returns True in this case.)
            payload = self.get_payload()
            assert len(payload) == 1  # should be exactly one message
            return payload[0].as_bytes()
        elif maintype == "multipart":
            # The attachment itself is multipart; the payload is a list of parts,
            # and it's not clear which one is the "content".
            raise ValueError(
                "get_content_bytes() is not valid on multipart messages "
                "(perhaps you want as_bytes()?)"
            )
        return self.get_payload(decode=True)

    def get_content_text(self, charset=None, errors=None):
        """Return the payload decoded to text"""
        maintype = self.get_content_maintype()
        if maintype == "message":
            # The attachment's payload is a single (parsed) email Message;
            # flatten it to text.
            # (Note that self.is_multipart() misleadingly returns True in this case.)
            payload = self.get_payload()
            assert len(payload) == 1  # should be exactly one message
            return payload[0].as_string()
        elif maintype == "multipart":
            # The attachment itself is multipart; the payload is a list of parts,
            # and it's not clear which one is the "content".
            raise ValueError(
                "get_content_text() is not valid on multipart messages "
                "(perhaps you want as_string()?)"
            )
        else:
            payload = self.get_payload(decode=True)
            if payload is None:
                return payload
            charset = charset or self.get_content_charset("US-ASCII")
            errors = errors or "replace"
            return payload.decode(charset, errors=errors)

    def as_uploaded_file(self):
        """Return the attachment converted to a Django UploadedFile"""
        if self["Content-Disposition"] is None:
            return None  # this part is not an attachment
        name = self.get_filename()
        content_type = self.get_content_type()
        content = self.get_content_bytes()
        return SimpleUploadedFile(name, content, content_type)

    #
    # Construction
    #
    # These methods are intended primarily for internal Anymail use
    # (in inbound webhook handlers)

    @classmethod
    def parse_raw_mime(cls, s):
        """Returns a new AnymailInboundMessage parsed from str s"""
        if isinstance(s, str):
            # Avoid Python 3.x issue https://bugs.python.org/issue18271
            # (See test_inbound: test_parse_raw_mime_8bit_utf8)
            return cls.parse_raw_mime_bytes(s.encode("utf-8"))
        return Parser(cls, policy=default_policy).parsestr(s)

    @classmethod
    def parse_raw_mime_bytes(cls, b):
        """Returns a new AnymailInboundMessage parsed from bytes b"""
        return BytesParser(cls, policy=default_policy).parsebytes(b)

    @classmethod
    def parse_raw_mime_file(cls, fp):
        """Returns a new AnymailInboundMessage parsed from file-like object fp"""
        if isinstance(fp.read(0), bytes):
            return BytesParser(cls, policy=default_policy).parse(fp)
        else:
            return Parser(cls, policy=default_policy).parse(fp)

    @classmethod
    def construct(
        cls,
        raw_headers=None,
        from_email=None,
        to=None,
        cc=None,
        bcc=None,
        subject=None,
        headers=None,
        text=None,
        text_charset="utf-8",
        html=None,
        html_charset="utf-8",
        attachments=None,
    ):
        """
        Returns a new AnymailInboundMessage constructed from params.

        This is designed to handle the sorts of email fields typically present in ESP
        parsed inbound messages. (It's not a generalized MIME message constructor.)

        :param raw_headers: {str|None}
            base (or complete) message headers as a single string
        :param from_email: {str|None} value for From header
        :param to: {str|None} value for To header
        :param cc: {str|None} value for Cc header
        :param bcc: {str|None} value for Bcc header
        :param subject: {str|None} value for Subject header
        :param headers: {sequence[(str, str)]|mapping|None} additional headers
        :param text: {str|None} plaintext body
        :param text_charset: {str} charset of plaintext body; default utf-8
        :param html: {str|None} html body
        :param html_charset: {str} charset of html body; default utf-8
        :param attachments: {list[MIMEBase]|None} as returned by construct_attachment
        :return: {AnymailInboundMessage}
        """
        if raw_headers is not None:
            msg = Parser(cls, policy=default_policy).parsestr(
                raw_headers, headersonly=True
            )
            # headersonly forces an empty string payload, which breaks things later:
            msg.set_payload(None)
        else:
            msg = cls()

        if from_email is not None:
            del msg["From"]  # override raw_headers value, if any
            msg["From"] = from_email
        if to is not None:
            del msg["To"]
            msg["To"] = to
        if cc is not None:
            del msg["Cc"]
            msg["Cc"] = cc
        if bcc is not None:
            del msg["Bcc"]
            msg["Bcc"] = bcc
        if subject is not None:
            del msg["Subject"]
            msg["Subject"] = subject
        if headers is not None:
            try:
                header_items = headers.items()  # mapping
            except AttributeError:
                header_items = headers  # sequence of (key, value)
            for name, value in header_items:
                msg.add_header(name, value)

        # For simplicity, always build a MIME structure that could support
        # plaintext/html alternative bodies, inline attachments for the body(ies), and
        # message attachments. This may be overkill for simpler messages, but the
        # structure is never incorrect.
        del msg["MIME-Version"]  # override raw_headers values, if any
        del msg["Content-Type"]
        msg["MIME-Version"] = "1.0"
        msg["Content-Type"] = "multipart/mixed"

        related = cls()  # container for alternative bodies and inline attachments
        related["Content-Type"] = "multipart/related"
        msg.attach(related)

        alternatives = cls()  # container for text and html bodies
        alternatives["Content-Type"] = "multipart/alternative"
        related.attach(alternatives)

        if text is not None:
            part = cls()
            part["Content-Type"] = "text/plain"
            part.set_payload(text, charset=text_charset)
            alternatives.attach(part)
        if html is not None:
            part = cls()
            part["Content-Type"] = "text/html"
            part.set_payload(html, charset=html_charset)
            alternatives.attach(part)

        if attachments is not None:
            for attachment in attachments:
                if attachment.is_inline():
                    related.attach(attachment)
                else:
                    msg.attach(attachment)

        return msg

    @classmethod
    def construct_attachment_from_uploaded_file(cls, file, content_id=None):
        # This pulls the entire file into memory; it would be better to implement
        # some sort of lazy attachment where the content is only pulled in if/when
        # requested (and then use file.chunks() to minimize memory usage)
        return cls.construct_attachment(
            content_type=getattr(file, "content_type", None),
            content=file.read(),
            filename=getattr(file, "name", None),
            content_id=content_id,
            charset=getattr(file, "charset", None),
        )

    @classmethod
    def construct_attachment(
        cls,
        content_type,
        content,
        charset=None,
        filename=None,
        content_id=None,
        base64=False,
    ):
        part = cls()
        part["Content-Type"] = content_type
        part["Content-Disposition"] = (
            "inline" if content_id is not None else "attachment"
        )

        if filename is not None:
            part.set_param("name", filename, header="Content-Type")
            part.set_param("filename", filename, header="Content-Disposition")

        if content_id is not None:
            part["Content-ID"] = angle_wrap(content_id)

        if base64:
            content = b64decode(content)

        payload = content
        if part.get_content_maintype() == "message":
            # email.Message parses message/rfc822 parts as a "multipart" (list) payload
            # whose single item is the recursively-parsed message attachment
            if isinstance(content, bytes):
                content = content.decode()
            payload = [cls.parse_raw_mime(content)]
            charset = None

        part.set_payload(payload, charset)
        return part
