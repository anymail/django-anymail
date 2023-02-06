from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Postal v1 API Email Backend
    """

    esp_name = "Postal"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name

        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )

        # Required, as there is no hosted instance of Postal
        api_url = get_anymail_setting("api_url", esp_name=esp_name, kwargs=kwargs)
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return PostalPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)

        if parsed_response["status"] != "success":
            raise AnymailRequestsAPIError(
                email_message=message, payload=payload, response=response, backend=self
            )

        # If we get here, the send call was successful.
        messages = parsed_response["data"]["messages"]

        return {
            email: AnymailRecipientStatus(message_id=details["id"], status="queued")
            for email, details in messages.items()
        }


class PostalPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        http_headers = kwargs.pop("headers", {})
        http_headers["X-Server-API-Key"] = backend.api_key
        http_headers["Content-Type"] = "application/json"
        http_headers["Accept"] = "application/json"
        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self):
        return "api/v1/send/message"

    def init_payload(self):
        self.data = {}

    def serialize_data(self):
        return self.serialize_json(self.data)

    def set_from_email(self, email):
        self.data["from"] = str(email)

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_to(self, emails):
        self.data["to"] = [str(email) for email in emails]

    def set_cc(self, emails):
        self.data["cc"] = [str(email) for email in emails]

    def set_bcc(self, emails):
        self.data["bcc"] = [str(email) for email in emails]

    def set_reply_to(self, emails):
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if len(emails) > 0:
            self.data["reply_to"] = str(emails[0])

    def set_extra_headers(self, headers):
        self.data["headers"] = headers

    def set_text_body(self, body):
        self.data["plain_body"] = body

    def set_html_body(self, body):
        if "html_body" in self.data:
            self.unsupported_feature("multiple html parts")
        self.data["html_body"] = body

    def make_attachment(self, attachment):
        """Returns Postal attachment dict for attachment"""
        att = {
            "name": attachment.name or "",
            "data": attachment.b64content,
            "content_type": attachment.mimetype,
        }
        if attachment.inline:
            # see https://github.com/postalhq/postal/issues/731
            # but it might be possible with the send/raw endpoint
            self.unsupported_feature("inline attachments")
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_envelope_sender(self, email):
        self.data["sender"] = str(email)

    def set_tags(self, tags):
        if len(tags) > 1:
            self.unsupported_feature("multiple tags")
        if len(tags) > 0:
            self.data["tag"] = tags[0]

    def set_esp_extra(self, extra):
        self.data.update(extra)
