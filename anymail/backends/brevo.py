from requests.structures import CaseInsensitiveDict

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import BASIC_NUMERIC_TYPES, get_anymail_setting
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Brevo v3 API Email Backend
    """

    esp_name = "Brevo"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting(
            "api_key",
            esp_name=esp_name,
            kwargs=kwargs,
            allow_bare=True,
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.brevo.com/v3/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return BrevoPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        # Brevo doesn't give any detail on a success, other than messageId
        # https://developers.brevo.com/reference/sendtransacemail
        message_id = None
        message_ids = []

        if response.content != b"":
            parsed_response = self.deserialize_json_response(response, payload, message)
            try:
                message_id = parsed_response["messageId"]
            except (KeyError, TypeError):
                try:
                    # batch send
                    message_ids = parsed_response["messageIds"]
                except (KeyError, TypeError) as err:
                    raise AnymailRequestsAPIError(
                        "Invalid Brevo API response format",
                        email_message=message,
                        payload=payload,
                        response=response,
                        backend=self,
                    ) from err

        status = AnymailRecipientStatus(message_id=message_id, status="queued")
        recipient_status = {
            recipient.addr_spec: status for recipient in payload.all_recipients
        }
        if message_ids:
            for to, message_id in zip(payload.to_recipients, message_ids):
                recipient_status[to.addr_spec] = AnymailRecipientStatus(
                    message_id=message_id, status="queued"
                )
        return recipient_status


class BrevoPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.all_recipients = []  # used for backend.parse_recipient_status
        self.to_recipients = []  # used for backend.parse_recipient_status

        http_headers = kwargs.pop("headers", {})
        http_headers["api-key"] = backend.api_key
        http_headers["Content-Type"] = "application/json"

        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self):
        return "smtp/email"

    def init_payload(self):
        self.data = {"headers": CaseInsensitiveDict()}  # becomes json
        self.merge_data = {}
        self.metadata = {}
        self.merge_metadata = {}
        self.merge_headers = {}

    def serialize_data(self):
        """Performs any necessary serialization on self.data, and returns the result."""
        if self.is_batch():
            # Burst data["to"] into data["messageVersions"]
            to_list = self.data.pop("to", [])
            self.data["messageVersions"] = []
            for to in to_list:
                to_email = to["email"]
                version = {"to": [to]}
                headers = CaseInsensitiveDict()
                if to_email in self.merge_data:
                    version["params"] = self.merge_data[to_email]
                if to_email in self.merge_metadata:
                    # Merge global metadata with any per-recipient metadata.
                    # (Top-level X-Mailin-custom header already has global metadata,
                    # and will apply for recipients without version headers.)
                    recipient_metadata = self.metadata.copy()
                    recipient_metadata.update(self.merge_metadata[to_email])
                    headers["X-Mailin-custom"] = self.serialize_json(recipient_metadata)
                if to_email in self.merge_headers:
                    headers.update(self.merge_headers[to_email])
                if headers:
                    version["headers"] = headers
                self.data["messageVersions"].append(version)

        if not self.data["headers"]:
            del self.data["headers"]  # don't send empty headers
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    @staticmethod
    def email_object(email):
        """Converts EmailAddress to Brevo API array"""
        email_object = dict()
        email_object["email"] = email.addr_spec
        if email.display_name:
            email_object["name"] = email.display_name
        return email_object

    def set_from_email(self, email):
        self.data["sender"] = self.email_object(email)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            self.data[recipient_type] = [self.email_object(email) for email in emails]
            self.all_recipients += emails  # used for backend.parse_recipient_status
            if recipient_type == "to":
                self.to_recipients = emails  # used for backend.parse_recipient_status

    def set_subject(self, subject):
        if subject != "":  # see note in set_text_body about template rendering
            self.data["subject"] = subject

    def set_reply_to(self, emails):
        # Brevo only supports a single address in the reply_to API param.
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if len(emails) > 0:
            self.data["replyTo"] = self.email_object(emails[0])

    def set_extra_headers(self, headers):
        # Brevo requires header values to be strings (not integers) as of 11/2022.
        # Stringify ints and floats; anything else is the caller's responsibility.
        self.data["headers"].update(
            {
                k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
                for k, v in headers.items()
            }
        )

    def set_tags(self, tags):
        if len(tags) > 0:
            self.data["tags"] = tags

    def set_template_id(self, template_id):
        self.data["templateId"] = template_id

    def set_text_body(self, body):
        if body:
            self.data["textContent"] = body

    def set_html_body(self, body):
        if body:
            if "htmlContent" in self.data:
                self.unsupported_feature("multiple html parts")

            self.data["htmlContent"] = body

    def add_attachment(self, attachment):
        """Converts attachments to Brevo API {name, base64} array"""
        att = {
            "name": attachment.name or "",
            "content": attachment.b64content,
        }

        if attachment.inline:
            self.unsupported_feature("inline attachments")

        self.data.setdefault("attachment", []).append(att)

    def set_esp_extra(self, extra):
        self.data.update(extra)

    def set_merge_data(self, merge_data):
        # Late bound in serialize_data:
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        self.data["params"] = merge_global_data

    def set_metadata(self, metadata):
        # Brevo expects a single string payload
        self.data["headers"]["X-Mailin-custom"] = self.serialize_json(metadata)
        self.metadata = metadata  # needed in serialize_data for batch send

    def set_merge_metadata(self, merge_metadata):
        # Late-bound in serialize_data:
        self.merge_metadata = merge_metadata

    def set_merge_headers(self, merge_headers):
        # Late-bound in serialize_data:
        self.merge_headers = merge_headers

    def set_send_at(self, send_at):
        try:
            start_time_iso = send_at.isoformat(timespec="milliseconds")
        except (AttributeError, TypeError):
            start_time_iso = send_at  # assume user already formatted
        self.data["scheduledAt"] = start_time_iso
