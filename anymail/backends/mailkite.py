import mimetypes

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    BASIC_NUMERIC_TYPES,
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
)
from .base_requests import AnymailRequestsBackend, RequestsPayload

# MailKite message status values returned from the send endpoint, mapped to
# Anymail's normalized recipient statuses. The API documents the send response
# as ``{"id": "...", "status": "..."}`` (e.g. ``"queued"``); we pass the status
# through as-is, defaulting to ``"queued"`` when the ESP omits it.
DEFAULT_RESPONSE_STATUS = "queued"


class EmailBackend(AnymailRequestsBackend):
    """
    MailKite (mailkite.dev) API Email Backend

    MailKite is an inbound-first email platform: it sends transactional mail over
    a single JSON API and (unlike most ESPs) also *receives* mail — parsed body
    plus an authentication verdict, delivered as one signed webhook. This backend
    implements the transactional send API.
    """

    esp_name = "MailKite"

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
            default="https://api.mailkite.dev/",
        )
        if not api_url.endswith("/"):
            api_url += "/"

        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailKitePayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        try:
            message_id = parsed_response["id"]
            status = parsed_response.get("status", DEFAULT_RESPONSE_STATUS)
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                "Invalid MailKite API response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        # MailKite sends one message (one returned id) covering every recipient.
        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status=status
                )
                for recip in payload.recipients
            }
        )
        return dict(recipient_status)


class MailKitePayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []  # for parse_recipient_status
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer %s" % backend.api_key
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        # MailKite has a single send endpoint; there is no separate batch API.
        return "v1/send"

    def serialize_data(self):
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email(self, email):
        self.data["from"] = email.format(idna_encode=self.backend.idna_encode)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            field = recipient_type
            self.data[field] = [
                email.format(idna_encode=self.backend.idna_encode) for email in emails
            ]
            self.recipients += emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        # MailKite's ``replyTo`` is a single string. A header value can hold
        # multiple addresses, so join them rather than dropping any.
        if emails:
            self.data["replyTo"] = ", ".join(
                email.format(idna_encode=self.backend.idna_encode) for email in emails
            )

    def set_extra_headers(self, headers):
        # MailKite requires header values to be strings. Stringify ints/floats;
        # anything else is the caller's responsibility.
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

    def make_attachment(self, attachment):
        """Returns a MailKite attachment dict for the attachment"""
        if attachment.inline:
            # The MailKite send API has no Content-ID / inline-attachment field,
            # so we can't accurately communicate inline attachments.
            self.unsupported_feature("inline attachments")

        filename = attachment.name or ""
        if not filename:
            # MailKite requires a filename. Generate a reasonable default.
            ext = mimetypes.guess_extension(attachment.mimetype or "")
            if ext:
                filename = "attachment%s" % ext
            else:
                self.unsupported_feature(
                    "unnamed attachments of type %s" % attachment.mimetype
                )
        att = {
            "filename": filename,
            "content": attachment.b64content,
        }
        if attachment.mimetype:
            att["contentType"] = attachment.mimetype
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_metadata(self, metadata):
        # MailKite has no dedicated metadata field; carry it as JSON in a custom
        # header (the ESP accepts arbitrary string-valued raw MIME headers).
        self.data.setdefault("headers", {})["X-Metadata"] = self.serialize_json(
            metadata
        )

    def set_tags(self, tags):
        # MailKite has no tags field; carry them as JSON in a custom header.
        self.data.setdefault("headers", {})["X-Tags"] = self.serialize_json(tags)

    # MailKite's /v1/send endpoint has no scheduling parameter (scheduled sends
    # are a separate flow), and no per-message tracking toggle.
    # def set_send_at(self, send_at):
    # def set_track_clicks(self, track_clicks):
    # def set_track_opens(self, track_opens):
    # def set_envelope_sender(self, envelope_sender):

    def set_template_id(self, template_id):
        self.data["templateId"] = template_id

    def set_merge_global_data(self, merge_global_data):
        # MailKite renders templates server-side from templateData.
        self.data["templateData"] = merge_global_data

    def set_merge_data(self, merge_data):
        # MailKite sends a single message to all recipients (not one per
        # recipient), so per-recipient merge data can't be expressed.
        if any(recipient_data for recipient_data in merge_data.values()):
            self.unsupported_feature("merge_data")

    def set_esp_extra(self, extra):
        self.data.update(extra)
