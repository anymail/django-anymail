import mimetypes
from email.charset import QP, Charset
from email.header import decode_header, make_header
from email.headerregistry import Address

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    BASIC_NUMERIC_TYPES,
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
)
from .base_requests import AnymailRequestsBackend, RequestsPayload

# Used to force RFC-2047 encoded word
# in address formatting workaround
QP_CHARSET = Charset("utf-8")
QP_CHARSET.header_encoding = QP


class EmailBackend(AnymailRequestsBackend):
    """
    Resend (resend.com) API Email Backend
    """

    esp_name = "Resend"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.resend.com/",
        )
        if not api_url.endswith("/"):
            api_url += "/"

        # Undocumented setting to control workarounds for Resend display-name issues
        # (see below). If/when Resend improves their API, you can disable Anymail's
        # workarounds by adding `"RESEND_WORKAROUND_DISPLAY_NAME_BUGS": False`
        # to your `ANYMAIL` settings.
        self.workaround_display_name_bugs = get_anymail_setting(
            "workaround_display_name_bugs",
            esp_name=esp_name,
            kwargs=kwargs,
            default=True,
        )

        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return ResendPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        try:
            message_id = parsed_response["id"]
            message_ids = None
        except (KeyError, TypeError):
            # Batch send?
            try:
                message_id = None
                message_ids = [item["id"] for item in parsed_response["data"]]
            except (KeyError, TypeError) as err:
                raise AnymailRequestsAPIError(
                    "Invalid Resend API response format",
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                ) from err

        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status="queued"
                )
                for recip in payload.recipients
            }
        )
        if message_ids:
            # batch send: ids are in same order as to_recipients
            for recip, message_id in zip(payload.to_recipients, message_ids):
                recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                    message_id=message_id, status="queued"
                )
        return dict(recipient_status)


class ResendPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []  # for parse_recipient_status
        self.to_recipients = []  # for parse_recipient_status
        self.metadata = {}
        self.merge_metadata = {}
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer %s" % backend.api_key
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        if self.is_batch():
            return "emails/batch"
        return "emails"

    def serialize_data(self):
        payload = self.data
        if self.is_batch():
            # Burst payload across to addresses
            to_emails = self.data.pop("to", [])
            payload = []
            for to_email, to in zip(to_emails, self.to_recipients):
                data = self.data.copy()
                data["to"] = [to_email]  # formatted for Resend (w/ workarounds)
                if to.addr_spec in self.merge_metadata:
                    # Merge global metadata with any per-recipient metadata.
                    recipient_metadata = self.metadata.copy()
                    recipient_metadata.update(self.merge_metadata[to.addr_spec])
                    if "headers" in data:
                        data["headers"] = data["headers"].copy()
                    else:
                        data["headers"] = {}
                    data["headers"]["X-Metadata"] = self.serialize_json(
                        recipient_metadata
                    )
                payload.append(data)

        return self.serialize_json(payload)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def _resend_email_address(self, address):
        """
        Return EmailAddress address formatted for use with Resend.

        Works around a Resend bug that rejects properly formatted RFC 5322
        addresses that have the display-name enclosed in double quotes (e.g.,
        any display-name containing a comma), by substituting an RFC 2047
        encoded word.

        This works for all Resend address fields _except_ `from` (see below).
        """
        formatted = address.address
        if self.backend.workaround_display_name_bugs:
            if formatted.startswith('"'):
                # Workaround: force RFC-2047 encoded word
                formatted = str(
                    Address(
                        display_name=QP_CHARSET.header_encode(address.display_name),
                        addr_spec=address.addr_spec,
                    )
                )
        return formatted

    def set_from_email(self, email):
        # Can't use the address header workaround above for the `from` field:
        #   self.data["from"] = self._resend_email_address(email)
        # When `from` uses RFC-2047 encoding, Resend returns a "security_error"
        # status 451, "The email payload contain invalid characters".
        formatted = email.address
        if self.backend.workaround_display_name_bugs:
            if formatted.startswith("=?"):
                # Workaround: use an *unencoded* (Unicode str) display-name.
                # This allows use of non-ASCII characters (which Resend rejects when
                # encoded with RFC 2047). Some punctuation will still result in unusual
                # behavior or cause an "invalid `from` field" 422 error, but there's
                # nothing we can do about that.
                formatted = str(
                    # email.headerregistry.Address str format uses unencoded Unicode
                    Address(
                        # Convert RFC 2047 display name back to Unicode str
                        display_name=str(
                            make_header(decode_header(email.display_name))
                        ),
                        addr_spec=email.addr_spec,
                    )
                )
        self.data["from"] = formatted

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            field = recipient_type
            self.data[field] = [self._resend_email_address(email) for email in emails]
            self.recipients += emails
            if recipient_type == "to":
                self.to_recipients = emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            self.data["reply_to"] = [
                self._resend_email_address(email) for email in emails
            ]

    def set_extra_headers(self, headers):
        # Resend requires header values to be strings (not integers) as of 2023-10-20.
        # Stringify ints and floats; anything else is the caller's responsibility.
        self.data.setdefault("headers", {}).update(
            {
                k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
                for k, v in headers.items()
            }
        )

    def set_text_body(self, body):
        self.data["text"] = body

    def set_html_body(self, body):
        if "html" in self.data:
            # second html body could show up through multiple alternatives,
            # or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["html"] = body

    @staticmethod
    def make_attachment(attachment):
        """Returns Resend attachment dict for attachment"""
        filename = attachment.name or ""
        if not filename:
            # Provide default name with reasonable extension.
            # (Resend guesses content type from the filename extension;
            # there doesn't seem to be any other way to specify it.)
            ext = mimetypes.guess_extension(attachment.content_type)
            if ext is not None:
                filename = f"attachment{ext}"
        att = {"content": attachment.b64content, "filename": filename}
        # attachment.inline / attachment.cid not supported
        return att

    def set_attachments(self, attachments):
        if attachments:
            if any(att.content_id for att in attachments):
                self.unsupported_feature("inline content-id")
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_metadata(self, metadata):
        # Send metadata as json in a custom X-Metadata header.
        # (Resend's own "tags" are severely limited in character set)
        self.data.setdefault("headers", {})["X-Metadata"] = self.serialize_json(
            metadata
        )
        self.metadata = metadata  # may be needed for batch send in serialize_data

    # Resend doesn't support delayed sending
    # def set_send_at(self, send_at):

    def set_tags(self, tags):
        # Send tags using a custom X-Tags header.
        # (Resend's own "tags" are severely limited in character set)
        self.data.setdefault("headers", {})["X-Tags"] = self.serialize_json(tags)

    # Resend doesn't support changing click/open tracking per message
    # def set_track_clicks(self, track_clicks):
    # def set_track_opens(self, track_opens):

    # Resend doesn't support server-rendered templates.
    # (Their template feature is rendered client-side,
    # using React in node.js.)
    # def set_template_id(self, template_id):
    # def set_merge_global_data(self, merge_global_data):

    def set_merge_data(self, merge_data):
        # Empty merge_data is a request to use batch send;
        # any other merge_data is unsupported.
        if any(recipient_data for recipient_data in merge_data.values()):
            self.unsupported_feature("merge_data")

    def set_merge_metadata(self, merge_metadata):
        self.merge_metadata = merge_metadata  # late bound in serialize_data

    def set_esp_extra(self, extra):
        self.data.update(extra)
