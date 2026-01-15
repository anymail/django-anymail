from ..exceptions import AnymailAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Sweego Email API Backend

    Uses /send for single recipient, /send/bulk/email for multiple recipients.
    """

    esp_name = "Sweego"

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
            default="https://api.sweego.io/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return SweegoPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        try:
            # Sweego returns:
            # {
            #   "channel": "email",
            #   "provider": "sweego",
            #   "swg_uids": {"recipient@example.com": "02-xxx-xxx-xxx"},
            #   "transaction_id": "xxx-xxx-xxx"
            # }
            swg_uids = parsed_response.get("swg_uids", {})
            transaction_id = parsed_response.get("transaction_id")
        except (KeyError, TypeError) as err:
            raise AnymailAPIError(
                "Invalid Sweego API response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        # Map each recipient to their specific message_id from swg_uids
        recipient_status = {}
        for email in payload.all_recipients:
            # Get the specific swg_uid for this recipient, or fall back to transaction_id
            message_id = swg_uids.get(email.addr_spec, transaction_id)
            recipient_status[email.addr_spec] = AnymailRecipientStatus(
                message_id=message_id, status="queued"
            )
        return recipient_status


class SweegoPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.all_recipients = []  # for parse_recipient_status
        self.merge_data = {}  # store merge_data for later use
        self.merge_global_data = {}  # store global variables
        http_headers = kwargs.pop("headers", {})
        http_headers["Api-Key"] = backend.api_key
        http_headers["Content-Type"] = "application/json"
        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self):
        # Use /send/bulk/email for multiple recipients (2+)
        # Use /send for single recipient
        if len(self.all_recipients) > 1:
            return "send/bulk/email"
        return "send"

    def init_payload(self):
        # Initialize with required fields for Sweego API
        self.data = {
            "channel": "email",
            "provider": "sweego",
        }

    def set_from_email(self, email):
        self.data["from"] = {
            "email": email.addr_spec,
        }
        if email.display_name:
            self.data["from"]["name"] = email.display_name

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            # Sweego uses 'recipients' array for all recipient types
            # Note: Sweego doesn't have native cc/bcc support in API
            # All recipients go to 'recipients' array
            for email in emails:
                recipient = {"email": email.addr_spec}
                if email.display_name:
                    recipient["name"] = email.display_name
                self.data.setdefault("recipients", []).append(recipient)
            self.all_recipients += emails

    def set_subject(self, subject):
        if subject:
            self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            # Sweego accepts a single reply-to address
            reply_to = emails[0]
            self.data["reply-to"] = {
                "email": reply_to.addr_spec,
            }
            if reply_to.display_name:
                self.data["reply-to"]["name"] = reply_to.display_name

    def set_extra_headers(self, headers):
        # Sweego limits to 5 custom headers
        self.data.setdefault("headers", {}).update(
            {k: str(v) for k, v in headers.items()}
        )

    def set_text_body(self, body):
        if body:
            self.data["message-txt"] = body

    def set_html_body(self, body):
        if body:
            self.data["message-html"] = body

    def add_attachment(self, attachment):
        # Sweego attachment format: filename + content (base64)
        att = {
            "filename": attachment.name or "attachment",
            "content": attachment.b64content,
        }
        if attachment.inline and attachment.cid:
            # Add content_id for inline attachments
            att["content_id"] = attachment.cid
        self.data.setdefault("attachments", []).append(att)

    def set_metadata(self, metadata):
        # Sweego stores metadata as custom headers (max 5)
        # Headers use X-Metadata- prefix
        if metadata:
            for key, value in list(metadata.items())[:5]:  # Max 5 headers
                header_key = f"X-Metadata-{key}"
                self.data.setdefault("headers", {})[header_key] = str(value)

    def set_tags(self, tags):
        # Sweego uses campaign-tags field
        # Limited to 5 tags, 1-20 chars each, [A-Za-z0-9-] only
        # Per Anymail policy, we pass through and let ESP validate
        if tags:
            self.data["campaign-tags"] = list(tags)

    def set_template_id(self, template_id):
        self.data["template-id"] = template_id

    def set_merge_data(self, merge_data):
        # Store merge_data to apply in serialize_data
        # For /send/bulk/email: variables go in each recipient object
        # For /send (single recipient): variables go in root "variables" field
        if merge_data:
            self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        # Store global variables to apply in serialize_data
        if merge_global_data:
            self.merge_global_data = merge_global_data

    def set_esp_extra(self, extra):
        self.data.update(extra)

    def serialize_data(self):
        # Apply merge_data and merge_global_data before serializing
        if len(self.all_recipients) > 1:
            # Bulk endpoint: variables go in each recipient object
            if self.merge_data or self.merge_global_data:
                for recipient in self.data.get("recipients", []):
                    email = recipient["email"]
                    variables = {}
                    # Add global variables first
                    if self.merge_global_data:
                        variables.update(self.merge_global_data)
                    # Add per-recipient variables (override global)
                    if self.merge_data and email in self.merge_data:
                        variables.update(self.merge_data[email])
                    if variables:
                        recipient["variables"] = variables
        else:
            # Single recipient: variables go in root "variables" field
            if self.all_recipients:
                email = self.all_recipients[0].addr_spec
                variables = {}
                if self.merge_global_data:
                    variables.update(self.merge_global_data)
                if self.merge_data and email in self.merge_data:
                    variables.update(self.merge_data[email])
                if variables:
                    self.data["variables"] = variables

        return self.serialize_json(self.data)
