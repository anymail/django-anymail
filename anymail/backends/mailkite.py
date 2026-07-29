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
    MailKite (mailkite.dev) API Email Backend

    MailKite is an inbound-first email platform: receive email as a webhook,
    send with one API. This backend implements transactional *sending* through
    MailKite's REST API. (Tracking and inbound webhook handling are not yet
    implemented; see the PR notes.)
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
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                "Invalid MailKite API response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        # MailKite returns a single send-level status with the response id:
        #   "sent"      -> accepted + handed to the provider for delivery
        #   "scheduled" -> parked for a future "send later" drain
        status = parsed_response.get("status", "sent")
        recipient_status_name = "queued" if status == "scheduled" else "sent"

        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status=recipient_status_name
                )
                for recip in payload.recipients
            }
        )
        return dict(recipient_status)


class MailKitePayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []  # all to/cc/bcc, for parse_recipient_status
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer %s" % backend.api_key
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        # MailKite has a single send endpoint; there is no batch variant.
        return "v1/send"

    def serialize_data(self):
        # MailKite's API takes a JSON body.
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email(self, email):
        # MailKite's `from` is a single address on a verified domain.
        self.data["from"] = email.format(idna_encode=self.backend.idna_encode)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            self.data[recipient_type] = [
                email.format(idna_encode=self.backend.idna_encode) for email in emails
            ]
            self.recipients += emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        # MailKite's `replyTo` is a single string. Comma-join multiple addresses
        # into one RFC 5322 Reply-To value.
        if emails:
            self.data["replyTo"] = ", ".join(
                [email.format(idna_encode=self.backend.idna_encode) for email in emails]
            )

    def set_extra_headers(self, headers):
        # MailKite accepts extra raw MIME headers as a {name: value} object.
        # Stringify ints/floats; anything else is the caller's responsibility.
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
        """Returns a MailKite attachment dict for an Anymail attachment"""
        if attachment.inline:
            # MailKite's send API attachment has no content-id / inline field,
            # so inline (cid-referenced) attachments can't be expressed without
            # silently breaking the reference. Surface it rather than mis-handle.
            self.unsupported_feature("inline attachments")

        # MailKite requires a filename. Generate one if Django didn't provide it.
        filename = attachment.name or ""
        if not filename:
            ext = mimetypes.guess_extension(attachment.mimetype)
            filename = "attachment%s" % ext if ext else "attachment"

        att = {
            "filename": filename,
            "content": attachment.b64content,
            "contentType": attachment.content_type,
        }
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_send_at(self, send_at):
        try:
            # MailKite can't handle microseconds; truncate to milliseconds if necessary.
            send_at = send_at.isoformat(
                timespec="milliseconds" if send_at.microsecond else "seconds"
            )
        except AttributeError:
            # User is responsible for formatting their own string
            pass
        self.data["scheduledAt"] = send_at

    def set_template_id(self, template_id):
        # MailKite templates are server-rendered from a saved template
        # (user `tpl_…` or base `base_…`), filled via `templateData`.
        self.data["templateId"] = template_id

    def set_merge_global_data(self, merge_global_data):
        # MailKite template merge variables (the {{merge_tags}} in a template).
        self.data["templateData"] = merge_global_data

    def set_track_opens(self, track_opens):
        self.data["trackOpens"] = track_opens

    # MailKite's send API has no dedicated tags, metadata, or per-recipient
    # batch/merge fields. (Extra headers can carry ad-hoc X-… header values via
    # `extra_headers` / `esp_extra`.)
    def set_tags(self, tags):
        self.unsupported_feature("tags")

    def set_metadata(self, metadata):
        self.unsupported_feature("metadata")

    def set_merge_data(self, merge_data):
        # Empty merge_data is a no-op request to hide the To list from other
        # recipients; MailKite has no batch send, so it degrades to a single
        # message with no per-recipient splitting. Any actual per-recipient data
        # is unsupported.
        if any(recipient_data for recipient_data in merge_data.values()):
            self.unsupported_feature("merge_data")

    def set_merge_metadata(self, merge_metadata):
        self.unsupported_feature("merge_metadata")

    def set_merge_headers(self, merge_headers):
        self.unsupported_feature("merge_headers")

    def set_esp_extra(self, extra):
        self.data.update(extra)
