from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting, update_deep
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """SMTP2GO v3 API email backend."""

    esp_name = "SMTP2GO"

    def __init__(self, **kwargs):
        self.api_key = get_anymail_setting(
            "api_key", esp_name=self.esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://api.smtp2go.com/v3/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return SMTP2GOPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed = self.deserialize_json_response(response, payload, message)

        def api_error(detail):
            return AnymailRequestsAPIError(
                detail,
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )

        try:
            data = parsed["data"]
            if payload.is_batch():
                if not isinstance(data, list) or len(data) != len(
                    payload.batch_recipients
                ):
                    raise ValueError("Unexpected number of batch responses")
                results = zip(data, payload.batch_recipients)
            else:
                results = [(data, payload.recipients)]
            statuses = {}
            for result, recipients in results:
                if not isinstance(result, dict):
                    raise ValueError("Expected an email response object")
                # Even HTTP 200 can report processing failures. The API does not
                # document a mapping from failures to individual recipients.
                if result.get("error") or result.get("error_code"):
                    raise api_error(result.get("error") or result["error_code"])
                if result.get("failed") or result.get("failures"):
                    raise api_error("SMTP2GO reported sending failures")
                message_id = result.get("email_id") or result.get("schedule_id")
                if not isinstance(message_id, str) or not message_id:
                    raise ValueError("Missing email_id or schedule_id")
                statuses.update(
                    {
                        email: AnymailRecipientStatus(message_id, "queued")
                        for email in recipients
                    }
                )
            return statuses
        except (KeyError, TypeError, ValueError) as err:
            raise api_error("Invalid SMTP2GO API response") from err


class SMTP2GOPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []
        self.to_emails = []
        self.cc_and_bcc = []
        self.batch_recipients = []
        self.merge_data = {}
        self.merge_headers = {}
        super().__init__(
            message,
            defaults,
            backend,
            *args,
            headers={
                "X-Smtp2go-Api-Key": backend.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            **kwargs,
        )

    def init_payload(self):
        self.data = {"to": [], "fastaccept": True}

    def get_api_endpoint(self):
        return "email/batch" if self.is_batch() else "email/send"

    def serialize_data(self):
        if not self.is_batch():
            return self.serialize_json(self.data)
        emails = []
        self.batch_recipients = []
        # Batch objects are independent messages. Copy common cc/bcc to each.
        for email in self.to_emails:
            recipient = email.addr_spec
            data = self.data.copy()
            data["to"] = [email.format(idna_encode=self.backend.idna_encode)]
            if self.merge_data:
                data["template_data"] = self.data.get("template_data", {}).copy()
                data["template_data"].update(self.merge_data.get(recipient, {}))
            if recipient in self.merge_headers:
                headers = {
                    header["header"]: header["value"]
                    for header in self.data.get("custom_headers", [])
                }
                headers.update(self.merge_headers[recipient])
                data["custom_headers"] = self.format_headers(headers)
            emails.append(data)
            self.batch_recipients.append([recipient, *self.cc_and_bcc])
        return self.serialize_json({"emails": emails})

    def set_from_email(self, email):
        self.data["sender"] = email.format(idna_encode=self.backend.idna_encode)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in {"to", "cc", "bcc"}
        if emails:
            self.data[recipient_type] = [
                email.format(idna_encode=self.backend.idna_encode) for email in emails
            ]
            addresses = [email.addr_spec for email in emails]
            self.recipients.extend(addresses)
            if recipient_type == "to":
                self.to_emails = emails
            else:
                self.cc_and_bcc.extend(addresses)

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            self.set_extra_headers(
                {
                    "Reply-To": ", ".join(
                        email.format(idna_encode=self.backend.idna_encode)
                        for email in emails
                    )
                }
            )

    @staticmethod
    def format_headers(headers):
        return [{"header": key, "value": str(value)} for key, value in headers.items()]

    def set_extra_headers(self, headers):
        self.data.setdefault("custom_headers", []).extend(self.format_headers(headers))

    def set_text_body(self, body):
        if body:
            self.data["text_body"] = body

    def set_html_body(self, body):
        if "html_body" in self.data:
            self.unsupported_feature("multiple html parts")
        self.data["html_body"] = body

    def add_attachment(self, attachment):
        # SMTP2GO uses the inline filename as its Content-ID.
        filename = attachment.cid if attachment.inline else attachment.name
        self.data.setdefault(
            "inlines" if attachment.inline else "attachments", []
        ).append(
            {
                "filename": filename or "attachment",
                "mimetype": attachment.content_type,
                "fileblob": attachment.b64content,
            }
        )

    def set_send_at(self, send_at):
        self.data["schedule"] = send_at.strftime("%Y-%m-%d %H:%M:%S %z")

    def set_template_id(self, template_id):
        self.data["template_id"] = template_id

    def set_merge_global_data(self, merge_global_data):
        self.data.setdefault("template_data", {}).update(merge_global_data)

    def set_merge_data(self, merge_data):
        self.merge_data = merge_data or {}

    def set_merge_headers(self, merge_headers):
        self.merge_headers = merge_headers or {}

    def set_esp_extra(self, extra):
        update_deep(self.data, extra)
