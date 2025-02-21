import mimetypes

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    BASIC_NUMERIC_TYPES,
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
)
from .base_requests import AnymailRequestsBackend, RequestsPayload


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
        self.merge_headers = {}
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
                data["to"] = [to_email]
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
                if to.addr_spec in self.merge_headers:
                    if "headers" in data:
                        # Merge global headers (or X-Metadata from above)
                        headers = CaseInsensitiveCasePreservingDict(data["headers"])
                        headers.update(self.merge_headers[to.addr_spec])
                    else:
                        headers = self.merge_headers[to.addr_spec]
                    data["headers"] = headers
                payload.append(data)

        return self.serialize_json(payload)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email(self, email):
        self.data["from"] = email.address

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            field = recipient_type
            self.data[field] = [email.address for email in emails]
            self.recipients += emails
            if recipient_type == "to":
                self.to_recipients = emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            self.data["reply_to"] = [email.address for email in emails]

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

    def set_send_at(self, send_at):
        try:
            # Resend can't handle microseconds; truncate to milliseconds if necessary.
            send_at = send_at.isoformat(
                timespec="milliseconds" if send_at.microsecond else "seconds"
            )
        except AttributeError:
            # User is responsible for formatting their own string
            pass
        self.data["scheduled_at"] = send_at

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

    def set_merge_headers(self, merge_headers):
        self.merge_headers = merge_headers  # late bound in serialize_data

    def set_esp_extra(self, extra):
        self.data.update(extra)
