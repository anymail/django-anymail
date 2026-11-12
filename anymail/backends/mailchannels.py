from copy import deepcopy

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    BASIC_NUMERIC_TYPES,
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
    update_deep,
)
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """MailChannels Email API sending backend."""

    esp_name = "MailChannels"

    def __init__(self, **kwargs):
        self.api_key = get_anymail_setting(
            "api_key", esp_name=self.esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://api.mailchannels.net/tx/v1/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailChannelsPayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        # Only the asynchronous endpoint's 202 means the request was queued.
        if response.status_code != 202:
            raise AnymailRequestsAPIError(
                "Expected HTTP 202 from MailChannels send-async",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )

    def parse_recipient_status(self, response, payload, message):
        parsed = self.deserialize_json_response(response, payload, message)
        if not isinstance(parsed, dict) or any(
            not isinstance(parsed.get(key), str) or not parsed[key].strip()
            for key in ("request_id", "queued_at")
        ):
            raise AnymailRequestsAPIError(
                "Invalid MailChannels async response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )
        # This is the request correlation ID, not an RFC Message-ID or proof
        # of delivery/individual recipient validation. All share the same ID.
        return dict(
            CaseInsensitiveCasePreservingDict(
                {
                    email.addr_spec: AnymailRecipientStatus(
                        message_id=parsed["request_id"], status="queued"
                    )
                    for email in payload.recipients
                }
            )
        )


class MailChannelsPayload(RequestsPayload):
    # MailChannels can't communicate these as caller-supplied custom headers.
    reserved_headers = {
        "authentication-results",
        "bcc",
        "cc",
        "content-transfer-encoding",
        "content-type",
        "dkim-signature",
        "from",
        "message-id",
        "received",
        "reply-to",
        "subject",
        "to",
    }

    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []
        self.to_recipients = []
        self.merge_data = {}
        self.merge_global_data = {}
        self.merge_headers = {}
        self.esp_extra = {}
        headers = kwargs.pop("headers", {})
        headers.update(
            {"X-Api-Key": backend.api_key, "Content-Type": "application/json"}
        )
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        return "send-async"

    def init_payload(self):
        self.data = {"personalizations": [{}], "content": []}

    def serialize_data(self):
        # Construct afresh: serialization may be called more than once.
        data = deepcopy(self.data)
        base = data["personalizations"][0]
        if not base.get("to"):
            self.unsupported_feature("messages without To recipients")
        if self.is_batch():
            personalizations = []
            for email, recipient in zip(self.to_recipients, base.get("to", [])):
                personalization = base.copy()
                personalization["to"] = [recipient]
                variables = self.merge_global_data.copy()
                variables.update(self.merge_data.get(email.addr_spec, {}))
                if variables:
                    personalization["dynamic_template_data"] = variables
                if email.addr_spec in self.merge_headers:
                    personalization["headers"] = self.merge_headers[email.addr_spec]
                personalizations.append(personalization)
        else:
            personalization = base.copy()
            if self.merge_global_data:
                personalization["dynamic_template_data"] = self.merge_global_data
            personalizations = [personalization]
        data["personalizations"] = personalizations
        if self.merge_data or self.merge_global_data:
            data["content"] = [
                dict(part, template_type="mustache") for part in data["content"]
            ]
        # The escape hatch is applied last, like other Anymail backends.
        # Lists (including personalizations) replace the generated list.
        update_deep(data, self.esp_extra)
        return self.serialize_json(data)

    def set_from_email(self, email):
        self.data["from"] = email.as_dict(idna_encode=self.backend.idna_encode)

    def set_recipients(self, recipient_type, emails):
        if emails:
            self.data["personalizations"][0][recipient_type] = [
                email.as_dict(idna_encode=self.backend.idna_encode) for email in emails
            ]
            self.recipients.extend(emails)
            if recipient_type == "to":
                self.to_recipients = emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if emails:
            self.data["reply_to"] = emails[0].as_dict(
                idna_encode=self.backend.idna_encode
            )

    def make_headers(self, headers):
        result = CaseInsensitiveCasePreservingDict()
        for name, value in headers.items():
            if name.lower() in self.reserved_headers:
                self.unsupported_feature(f"reserved header {name!r}")
            else:
                result[name] = (
                    str(value) if isinstance(value, BASIC_NUMERIC_TYPES) else value
                )
        return dict(result)

    def set_extra_headers(self, headers):
        self.data["headers"] = self.make_headers(headers)

    def set_text_body(self, body):
        self.data["content"].append({"type": "text/plain", "value": body})

    def set_html_body(self, body):
        if any(part["type"] == "text/html" for part in self.data["content"]):
            self.unsupported_feature("multiple html parts")
        self.data["content"].append({"type": "text/html", "value": body})

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(att) for att in attachments
            ]

    def make_attachment(self, attachment):
        result = {
            "filename": attachment.name or "attachment",
            "type": attachment.content_type,
            "content": attachment.b64content,
        }
        if attachment.inline:
            if not attachment.cid:
                self.unsupported_feature("inline attachments without Content-ID")
            else:
                result["content_id"] = attachment.cid
        return result

    def set_envelope_sender(self, email):
        self.data["envelope_from"] = {
            "email": email.format_addr_spec(idna_encode=self.backend.idna_encode)
        }

    def set_track_clicks(self, track_clicks):
        self.data.setdefault("tracking_settings", {})["click_tracking"] = {
            "enable": track_clicks
        }

    def set_track_opens(self, track_opens):
        self.data.setdefault("tracking_settings", {})["open_tracking"] = {
            "enable": track_opens
        }

    def set_merge_data(self, merge_data):
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        self.merge_global_data = merge_global_data

    def set_merge_headers(self, merge_headers):
        self.merge_headers = {
            email: self.make_headers(headers)
            for email, headers in merge_headers.items()
        }

    def set_esp_extra(self, extra):
        self.esp_extra = extra
