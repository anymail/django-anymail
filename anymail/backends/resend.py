import mimetypes
from email.charset import QP, Charset
from email.utils import formataddr

from ..message import AnymailRecipientStatus
from ..utils import CaseInsensitiveCasePreservingDict, get_anymail_setting
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
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return ResendPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        # Resend provides single message id, no other information.
        # Assume "queued".
        parsed_response = self.deserialize_json_response(response, payload, message)
        message_id = parsed_response["id"]
        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status="queued"
                )
                for recip in payload.recipients
            }
        )
        return dict(recipient_status)


class ResendPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []  # for parse_recipient_status
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer %s" % backend.api_key
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        return "emails"

    def serialize_data(self):
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    @staticmethod
    def _resend_email_address(address):
        """
        Return EmailAddress address formatted for use with Resend.

        Works around a Resend bug that rejects properly formatted RFC 5322
        addresses that have the display-name enclosed in double quotes (e.g.,
        any display-name containing a comma).
        """
        formatted = address.address
        if formatted.startswith('"'):
            # Workaround: force RFC-2047 encoded word
            formatted = formataddr(
                (QP_CHARSET.header_encode(address.display_name), address.addr_spec)
            )
        return formatted

    def set_from_email(self, email):
        # Can't use the address header workaround for the `from` field:
        #   self.data["from"] = self._resend_email_address(email)
        # (If `from` uses RFC-2047 encoding, Resend returns a "security_error"
        # status 451, "The email payload contain invalid characters".)
        # Just use the RFC-5322 formatted address, and document that some
        # display-names will cause invalid_parameter or security_error errors.
        # TODO: update `from` handling after hearing back from Resend support
        self.data["from"] = email.address

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            field = recipient_type
            self.data[field] = [self._resend_email_address(email) for email in emails]
            self.recipients += emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            self.data["reply_to"] = [
                self._resend_email_address(email) for email in emails
            ]

    def set_extra_headers(self, headers):
        self.data.setdefault("headers", {}).update(headers)

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

    # Resend doesn't support delayed sending
    # def set_send_at(self, send_at):

    def set_tags(self, tags):
        # Send tags using a custom X-Tag header.
        # (Resend's own "tags" are severely limited in character set)
        # This will result in one X-Tag header per tag:
        self.data.setdefault("headers", {})["X-Tag"] = tags

    # Resend doesn't support changing click/open tracking per message
    # def set_track_clicks(self, track_clicks):
    # def set_track_opens(self, track_opens):

    # Resend doesn't support server-rendered templates.
    # (Their template feature is rendered client-side,
    # using React in node.js.)
    # def set_template_id(self, template_id):
    # def set_merge_data(self, merge_data):
    # def set_merge_global_data(self, merge_global_data):
    # def set_merge_metadata(self, merge_metadata):

    def set_esp_extra(self, extra):
        self.data.update(extra)
