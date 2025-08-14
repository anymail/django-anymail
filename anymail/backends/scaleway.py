from urllib.parse import quote

from ..exceptions import AnymailAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Scaleway Transactional Email API Backend
    """

    esp_name = "Scaleway"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.secret_key = get_anymail_setting(
            "secret_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        self.project_id = get_anymail_setting(
            "project_id", esp_name=esp_name, kwargs=kwargs
        )
        region = get_anymail_setting(
            "region", esp_name=esp_name, kwargs=kwargs, default="fr-par"
        )
        api_url_template = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default=(
                "https://api.scaleway.com/transactional-email/v1alpha1/regions/{region}/"
            ),
        )
        api_url = api_url_template.format(region=quote(region, safe=""))
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return ScalewayPayload(message, defaults, self)

    _recipient_status_map = {
        # Scaleway send status -> Anymail status.
        # (In practice, only "sending" seems to be reported.
        # Invalid addresses cause an API failure.
        # Blocked addresses show as "sending" and are rejected later.)
        "unknown": "unknown",
        "new": "queued",
        "sending": "queued",
        "sent": "sent",
        "failed": "failed",
        "canceled": "failed",
    }

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        statuses = {}
        try:
            emails = parsed_response["emails"]
        except (KeyError, TypeError):
            raise AnymailAPIError(
                "Invalid response from Scaleway API",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )

        for email_info in emails:
            recipient = email_info.get("mail_rcpt")
            message_id = email_info.get("id")
            status = email_info.get("status")
            anymail_status = AnymailRecipientStatus(
                message_id=message_id,
                status=self._recipient_status_map.get(status, "unknown"),
            )
            if recipient:
                statuses[recipient] = anymail_status
        return statuses


class ScalewayPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.project_id = backend.project_id
        http_headers = kwargs.pop("headers", {})
        http_headers["X-Auth-Token"] = backend.secret_key
        http_headers["Content-Type"] = "application/json"
        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self):
        return "emails"

    def init_payload(self):
        self.data = {
            "project_id": self.project_id,
        }

    def _scaleway_email(self, email):
        """Expand an Anymail EmailAddress into Scaleway's {"email", "name"} dict"""
        result = {"email": email.addr_spec}
        if email.display_name:
            result["name"] = email.display_name
        return result

    def set_from_email(self, email):
        self.data["from"] = self._scaleway_email(email)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in {"to", "cc", "bcc"}
        if emails:
            self.data[recipient_type] = [
                self._scaleway_email(email) for email in emails
            ]

    def set_subject(self, subject):
        if subject:
            self.data["subject"] = subject

    def set_text_body(self, body):
        if body:
            self.data["text"] = body

    def set_html_body(self, html):
        if html:
            self.data["html"] = html

    def add_attachment(self, attachment):
        if attachment.inline:
            self.unsupported_feature("inline attachments")
        self.data.setdefault("attachments", []).append(
            {
                "name": attachment.name,
                "type": attachment.mimetype,
                "content": attachment.b64content,
            }
        )

    def set_extra_headers(self, headers):
        self.data.setdefault("additional_headers", []).extend(
            [{"key": key, "value": str(value)} for key, value in headers.items()]
        )

    def set_reply_to(self, emails):
        if emails:
            reply_to_string = ", ".join([str(email) for email in emails])
            self.data.setdefault("additional_headers", []).append(
                {"key": "Reply-To", "value": reply_to_string}
            )

    def set_tags(self, tags):
        if tags:
            self.data.setdefault("additional_headers", []).append(
                {"key": "X-Tags", "value": self.serialize_json(tags)}
            )

    def set_metadata(self, metadata):
        if metadata:
            self.data.setdefault("additional_headers", []).append(
                {"key": "X-Metadata", "value": self.serialize_json(metadata)}
            )

    def set_esp_extra(self, extra):
        self.data.update(extra)

    def serialize_data(self):
        return self.serialize_json(self.data)
