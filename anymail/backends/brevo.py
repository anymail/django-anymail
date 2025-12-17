from requests.structures import CaseInsensitiveDict

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import BASIC_NUMERIC_TYPES, get_anymail_setting, has_specials
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

        # Undocumented setting to control workaround for Brevo display-name bug.
        # If/when Brevo improves their API, you can disable Anymail's workaround
        # by adding:
        #   "BREVO_WORKAROUND_DISPLAY_NAME_BUGS": False
        # to your `ANYMAIL` settings.
        self.workaround_display_name_bugs = get_anymail_setting(
            "workaround_display_name_bugs",
            esp_name=esp_name,
            kwargs=kwargs,
            default=True,
        )

        # Undocumented setting to control workaround for Brevo header encoding
        # bug. If/when Brevo fixes the problem, you can disable Anymail's error
        # on non-ASCII headers/metadata by adding:
        #    "BREVO_PREVENT_HEADER_ENCODING_BUGS": False
        # to your `ANYMAIL` settings.
        self.prevent_header_encoding_bugs = get_anymail_setting(
            "prevent_header_encoding_bugs",
            esp_name=esp_name,
            kwargs=kwargs,
            default=True,
        )

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
                    mailin_custom = self.serialize_json(recipient_metadata)
                    # set_metadata() already validated self.metadata,
                    # so any problem here originates in merge_metadata:
                    self.prevent_header_encoding_bug("merge_metadata", mailin_custom)
                    headers["X-Mailin-custom"] = mailin_custom
                if to_email in self.merge_headers:
                    for value in self.merge_headers[to_email].values():
                        self.prevent_header_encoding_bug("merge_headers", value)
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

    def email_object(self, email):
        """Converts EmailAddress to Brevo API object with workarounds"""
        use_rfc2047 = False
        # In from/to/cc/bcc, Brevo silently drops the "name" field if it
        # contains both non-ASCII chars and a comma (or other special).
        # In replyTo, Brevo sends the name as 8-bit (unencoded) utf-8.
        # (If the name is all ASCII, or is non-ASCII but doesn't have a special,
        # Brevo encodes and sends it correctly using RFC 2047.)
        # Workaround by applying RFC 2047 encoding here. This works fine for
        # from/to/cc/bcc. In replyTo, the result is an encoded-word inside
        # a quoted-string, but that's better than sending 8-bit header values.
        if (
            self.backend.workaround_display_name_bugs
            and not email.display_name.isascii()
            and has_specials(email.display_name)
        ):
            use_rfc2047 = "force"
        return email.as_dict(
            use_rfc2047=use_rfc2047, idna_encode=self.backend.idna_encode
        )

    def prevent_header_encoding_bug(self, field, value):
        # Brevo transmits non-ASCII custom headers as raw 8-bit utf-8.
        # This can cause messages to be rejected or create other delivery
        # problems. (Anymail can't work around this, because if we apply
        # RFC 2047 encoding to the value before calling Brevo's API, Brevo
        # _decodes_ that value and sends it as 8-bit anyway.)
        if (
            self.backend.prevent_header_encoding_bugs
            and isinstance(value, str)
            and (not value.isascii() or "\\u" in value)
        ):
            self.unsupported_feature(f"non-ASCII characters in {field}")

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
        for field, value in headers.items():
            # Brevo requires header values to be strings (not integers) as of 11/2022.
            # Stringify ints and floats; anything else is the caller's responsibility.
            if isinstance(value, BASIC_NUMERIC_TYPES):
                value = str(value)

            self.prevent_header_encoding_bug(f"{field!r} header", value)
            self.data["headers"][field] = value

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
        # Brevo guesses content type from the name
        # and returns a useful API error for an empty name.
        # Text content must be utf-8 (Brevo adds `charset=utf-8`).
        att = {
            "name": attachment.name or "",
            "content": attachment.b64content_utf8,
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
        mailin_custom = self.serialize_json(metadata)
        self.prevent_header_encoding_bug("metadata", mailin_custom)
        self.data["headers"]["X-Mailin-custom"] = mailin_custom
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
