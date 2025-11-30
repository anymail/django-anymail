import sys
from urllib.parse import quote

if sys.version_info < (3, 11):
    from typing_extensions import Any, Dict, List, Literal, NotRequired, TypedDict
else:
    from typing import Any, Dict, List, Literal, NotRequired, TypedDict

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailMessage, AnymailRecipientStatus
from ..utils import Attachment, EmailAddress, get_anymail_setting, update_deep
from .base_requests import AnymailRequestsBackend, RequestsPayload


class MailtrapAddress(TypedDict):
    email: str
    name: NotRequired[str]


class MailtrapAttachment(TypedDict):
    content: str
    type: NotRequired[str]
    filename: str
    disposition: NotRequired[Literal["attachment", "inline"]]
    content_id: NotRequired[str]


MailtrapData = TypedDict(
    "MailtrapData",
    {
        # Although "from" and "subject" are technically required,
        # allow Mailtrap's API to enforce that.
        "from": NotRequired[MailtrapAddress],
        "to": NotRequired[List[MailtrapAddress]],
        "cc": NotRequired[List[MailtrapAddress]],
        "bcc": NotRequired[List[MailtrapAddress]],
        "attachments": NotRequired[List[MailtrapAttachment]],
        "headers": NotRequired[Dict[str, str]],
        "custom_variables": NotRequired[Dict[str, str]],
        "subject": NotRequired[str],
        "text": NotRequired[str],
        "html": NotRequired[str],
        "category": NotRequired[str],
        "template_uuid": NotRequired[str],
        "template_variables": NotRequired[Dict[str, Any]],
    },
)

MailtrapBatchData = TypedDict(
    "MailtrapBatchData",
    {
        "base": MailtrapData,
        "requests": List[MailtrapData],
    },
)


class MailtrapPayload(RequestsPayload):
    def __init__(
        self,
        message: AnymailMessage,
        defaults,
        backend: "EmailBackend",
        *args,
        **kwargs,
    ):
        http_headers = {
            "Api-Token": backend.api_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Yes, the parent sets this, but setting it here, too, gives type hints
        self.backend = backend

        # Late bound batch send data
        self.merge_data: Dict[str, Any] = {}
        self.merge_metadata: Dict[str, Dict[str, str]] = {}
        self.merge_headers: Dict[str, Dict[str, str]] = {}

        # needed for backend.parse_recipient_status
        self.recipients_to: List[str] = []
        self.recipients_cc: List[str] = []
        self.recipients_bcc: List[str] = []

        super().__init__(
            message, defaults, backend, *args, headers=http_headers, **kwargs
        )

    def get_api_endpoint(self):
        endpoint = "batch" if self.is_batch() else "send"
        if self.backend.use_sandbox:
            sandbox_id = quote(str(self.backend.sandbox_id), safe="")
            return f"{endpoint}/{sandbox_id}"
        else:
            return endpoint

    def serialize_data(self):
        data = self.burst_for_batch() if self.is_batch() else self.data
        return self.serialize_json(data)

    def burst_for_batch(self) -> MailtrapBatchData:
        """Transform self.data into the payload for a batch send."""
        # One batch send request for each 'to' address.
        # Any cc and bcc recipients are duplicated to every request.
        to = self.data.pop("to", [])
        cc = self.data.pop("cc", None)
        bcc = self.data.pop("bcc", None)
        base_template_variables = self.data.get("template_variables", {})
        base_custom_variables = self.data.get("custom_variables", {})
        base_headers = self.data.get("headers", {})
        requests = []
        for recipient in to:
            email = recipient["email"]
            request: MailtrapData = {"to": [recipient]}
            if cc:
                request["cc"] = cc
            if bcc:
                request["bcc"] = bcc
            # Any request props completely override base props, so must merge base.
            if email in self.merge_data:
                request["template_variables"] = base_template_variables.copy()
                request["template_variables"].update(self.merge_data[email])
            if email in self.merge_metadata:
                request["custom_variables"] = base_custom_variables.copy()
                request["custom_variables"].update(self.merge_metadata[email])
            if email in self.merge_headers:
                request["headers"] = base_headers.copy()
                request["headers"].update(self.merge_headers[email])
            requests.append(request)
        return {"base": self.data, "requests": requests}

    #
    # Payload construction
    #

    def init_payload(self):
        self.data: MailtrapData = {}

    @staticmethod
    def _mailtrap_email(email: EmailAddress) -> MailtrapAddress:
        """Expand an Anymail EmailAddress into Mailtrap's {"email", "name"} dict"""
        result: MailtrapAddress = {"email": email.addr_spec}
        if email.display_name:
            result["name"] = email.display_name
        return result

    def set_from_email(self, email: EmailAddress):
        self.data["from"] = self._mailtrap_email(email)

    def set_recipients(
        self, recipient_type: Literal["to", "cc", "bcc"], emails: List[EmailAddress]
    ):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            self.data[recipient_type] = [
                self._mailtrap_email(email) for email in emails
            ]

            if recipient_type == "to":
                self.recipients_to = [email.addr_spec for email in emails]
            elif recipient_type == "cc":
                self.recipients_cc = [email.addr_spec for email in emails]
            elif recipient_type == "bcc":
                self.recipients_bcc = [email.addr_spec for email in emails]

    def set_subject(self, subject):
        if subject:
            # (must ignore default empty subject for use with template_uuid)
            self.data["subject"] = subject

    def set_reply_to(self, emails: List[EmailAddress]):
        if emails:
            # Use header rather than "reply_to" param
            # to allow multiple reply-to addresses
            self.data.setdefault("headers", {})["Reply-To"] = ", ".join(
                email.address for email in emails
            )

    def set_extra_headers(self, headers):
        # Note: Mailtrap appears to correctly RFC 2047 encode non-ASCII header
        # values for us, even though its docs say that we "must ensure these
        # are properly encoded if they contain unicode characters."
        self.data.setdefault("headers", {}).update(headers)

    def set_text_body(self, body):
        if body:
            self.data["text"] = body

    def set_html_body(self, body):
        if "html" in self.data:
            # second html body could show up through multiple alternatives,
            # or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["html"] = body

    def add_attachment(self, attachment: Attachment):
        att: MailtrapAttachment = {
            # Mailtrap requires filename even for inline attachments.
            # Provide a fallback filename like the Mailjet backend does.
            "filename": attachment.name or "attachment",
            "content": attachment.b64content,
            # default disposition is "attachment"
        }
        if attachment.mimetype:
            att["type"] = attachment.mimetype
        if attachment.inline:
            att["disposition"] = "inline"
            att["content_id"] = attachment.cid
        self.data.setdefault("attachments", []).append(att)

    def set_tags(self, tags: List[str]):
        if len(tags) > 1:
            self.unsupported_feature("multiple tags")
        if len(tags) > 0:
            self.data["category"] = tags[0]

    def set_metadata(self, metadata):
        self.data.setdefault("custom_variables", {}).update(
            {str(k): str(v) for k, v in metadata.items()}
        )

    def set_template_id(self, template_id):
        self.data["template_uuid"] = template_id

    def set_merge_data(self, merge_data):
        # Late-bound in burst_for_batch
        self.merge_data = merge_data

    def set_merge_headers(self, merge_headers):
        # Late-bound in burst_for_batch
        self.merge_headers = merge_headers

    def set_merge_global_data(self, merge_global_data: Dict[str, Any]):
        self.data.setdefault("template_variables", {}).update(merge_global_data)

    def set_merge_metadata(self, merge_metadata):
        # Late-bound in burst_for_batch
        self.merge_metadata = merge_metadata

    def set_esp_extra(self, extra):
        update_deep(self.data, extra)


class EmailBackend(AnymailRequestsBackend):
    """
    Mailtrap API Email Backend
    """

    esp_name = "Mailtrap"

    DEFAULT_API_URL = "https://send.api.mailtrap.io/api/"
    DEFAULT_SANDBOX_API_URL = "https://sandbox.api.mailtrap.io/api/"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        self.api_token = get_anymail_setting(
            "api_token", esp_name=self.esp_name, kwargs=kwargs, allow_bare=True
        )
        self.sandbox_id = get_anymail_setting(
            "sandbox_id", esp_name=self.esp_name, kwargs=kwargs, default=None
        )
        self.use_sandbox = self.sandbox_id is not None

        api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=(
                self.DEFAULT_SANDBOX_API_URL
                if self.use_sandbox
                else self.DEFAULT_API_URL
            ),
        )
        if not api_url.endswith("/"):
            api_url += "/"

        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailtrapPayload(message, defaults, self)

    def parse_recipient_status(
        self, response, payload: MailtrapPayload, message: AnymailMessage
    ):
        parsed_response = self.deserialize_json_response(response, payload, message)

        if parsed_response.get("errors") or not parsed_response.get("success"):
            # Superclass has already filtered http error status responses,
            # so errors here (or general batch send error) shouldn't be possible.
            status = response.status_code
            raise AnymailRequestsAPIError(
                f"Unexpected API failure fields with response status {status}",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )

        if payload.is_batch():
            try:
                responses = parsed_response["responses"]
            except KeyError:
                raise AnymailRequestsAPIError("")
            if len(payload.recipients_to) != len(responses):
                raise AnymailRequestsAPIError(
                    f"Expected {len(payload.recipients_to)} batch send responses"
                    f" but got {len(responses)}",
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                )

            # Merge recipient statuses for each item in the batch.
            # Each API response includes message_ids in the order 'to', 'cc, 'bcc'.
            recipient_status: Dict[str, AnymailRecipientStatus] = {}
            for to, one_response in zip(payload.recipients_to, responses):
                recipients = [to, *payload.recipients_cc, *payload.recipients_bcc]
                one_status = self.parse_one_response(
                    one_response, recipients, response, payload, message
                )
                recipient_status.update(one_status)
        else:
            # Non-batch send.
            # API response includes message_ids in the order 'to', 'cc, 'bcc'.
            recipients = [
                *payload.recipients_to,
                *payload.recipients_cc,
                *payload.recipients_bcc,
            ]
            recipient_status = self.parse_one_response(
                parsed_response, recipients, response, payload, message
            )

        return recipient_status

    def parse_one_response(
        self,
        one_response,
        recipients: List[str],
        raw_response,
        payload: MailtrapPayload,
        message: AnymailMessage,
    ) -> Dict[str, AnymailRecipientStatus]:
        """
        Return parsed status for recipients in one_response, which is either
        a top-level send response or an individual 'responses' item for batch send.
        """
        if not one_response["success"]:
            # (Could try to parse status out of one_response["errors"].)
            return {
                email: AnymailRecipientStatus(message_id=None, status="failed")
                for email in recipients
            }

        try:
            message_ids = one_response["message_ids"]
        except KeyError:
            raise AnymailRequestsAPIError(
                "Unexpected API response format",
                email_message=message,
                payload=payload,
                response=raw_response,
                backend=self,
            )

        # The sandbox API always returns a single message id for all recipients;
        # the production API returns one message id per recipient.
        expected_count = 1 if self.use_sandbox else len(recipients)
        actual_count = len(message_ids)
        if expected_count != actual_count:
            raise AnymailRequestsAPIError(
                f"Expected {expected_count} message_ids, got {actual_count}",
                email_message=message,
                payload=payload,
                response=raw_response,
                backend=self,
            )
        if self.use_sandbox:
            message_ids = [message_ids[0]] * len(recipients)

        recipient_status = {
            email: AnymailRecipientStatus(
                message_id=message_id,
                status="queued",
            )
            for email, message_id in zip(recipients, message_ids)
        }
        return recipient_status
