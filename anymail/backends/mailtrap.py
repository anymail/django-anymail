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
        "from": MailtrapAddress,
        "to": NotRequired[List[MailtrapAddress]],
        "cc": NotRequired[List[MailtrapAddress]],
        "bcc": NotRequired[List[MailtrapAddress]],
        "attachments": NotRequired[List[MailtrapAttachment]],
        "headers": NotRequired[Dict[str, str]],
        "custom_variables": NotRequired[Dict[str, str]],
        "subject": str,
        "text": str,
        "html": NotRequired[str],
        "category": NotRequired[str],
        "template_id": NotRequired[str],
        "template_variables": NotRequired[Dict[str, Any]],
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
        self.metadata = None

        # needed for backend.parse_recipient_status
        self.recipients_to: List[str] = []
        self.recipients_cc: List[str] = []
        self.recipients_bcc: List[str] = []

        super().__init__(
            message, defaults, backend, *args, headers=http_headers, **kwargs
        )

    def get_api_endpoint(self):
        if self.backend.testing_enabled:
            test_inbox_id = quote(self.backend.test_inbox_id, safe="")
            return f"send/{test_inbox_id}"
        return "send"

    def serialize_data(self):
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data: MailtrapData = {
            "from": {
                "email": "",
            },
            "subject": "",
            "text": "",
        }

    @staticmethod
    def _mailtrap_email(email: EmailAddress) -> MailtrapAddress:
        """Expand an Anymail EmailAddress into Mailtrap's {"email", "name"} dict"""
        result = {"email": email.addr_spec}
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
        self.data["subject"] = subject

    def set_reply_to(self, emails: List[EmailAddress]):
        self.data.setdefault("headers", {})["Reply-To"] = ", ".join(
            email.address for email in emails
        )

    def set_extra_headers(self, headers):
        self.data.setdefault("headers", {}).update(headers)

    def set_text_body(self, body):
        self.data["text"] = body

    def set_html_body(self, body):
        if "html" in self.data:
            # second html body could show up through multiple alternatives,
            # or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["html"] = body

    def add_attachment(self, attachment: Attachment):
        att: MailtrapAttachment = {
            "disposition": "attachment",
            "filename": attachment.name,
            "content": attachment.b64content,
        }
        if attachment.mimetype:
            att["type"] = attachment.mimetype
        if attachment.inline:
            if not attachment.cid:
                self.unsupported_feature("inline attachment without content-id")
            att["disposition"] = "inline"
            att["content_id"] = attachment.cid
        elif not attachment.name:
            self.unsupported_feature("attachment without filename")
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
        self.metadata = metadata  # save for set_merge_metadata

    def set_template_id(self, template_id):
        self.data["template_uuid"] = template_id

    def set_merge_global_data(self, merge_global_data: Dict[str, Any]):
        self.data.setdefault("template_variables", {}).update(merge_global_data)

    def set_esp_extra(self, extra):
        update_deep(self.data, extra)


class EmailBackend(AnymailRequestsBackend):
    """
    Mailtrap API Email Backend
    """

    esp_name = "Mailtrap"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        self.api_token = get_anymail_setting(
            "api_token", esp_name=self.esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://send.api.mailtrap.io/api/",
        )
        if not api_url.endswith("/"):
            api_url += "/"

        test_api_url = get_anymail_setting(
            "test_api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://sandbox.api.mailtrap.io/api/",
        )
        if not test_api_url.endswith("/"):
            test_api_url += "/"
        self.test_api_url = test_api_url

        self.testing_enabled = get_anymail_setting(
            "testing",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=False,
        )

        if self.testing_enabled:
            self.test_inbox_id = get_anymail_setting(
                "test_inbox_id",
                esp_name=self.esp_name,
                kwargs=kwargs,
                # (no default means required -- error if not set)
            )
            api_url = self.test_api_url
        else:
            self.test_inbox_id = None

        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailtrapPayload(message, defaults, self)

    def parse_recipient_status(
        self, response, payload: MailtrapPayload, message: AnymailMessage
    ):
        parsed_response = self.deserialize_json_response(response, payload, message)

        # TODO: how to handle fail_silently?
        if not self.fail_silently and (
            not parsed_response.get("success")
            or ("errors" in parsed_response and parsed_response["errors"])
            or ("message_ids" not in parsed_response)
        ):
            raise AnymailRequestsAPIError(
                email_message=message, payload=payload, response=response, backend=self
            )
        else:
            # message-ids will be in this order
            recipient_status_order = [
                *payload.recipients_to,
                *payload.recipients_cc,
                *payload.recipients_bcc,
            ]
            recipient_status = {
                email: AnymailRecipientStatus(
                    message_id=parsed_response["message_ids"][0],
                    status="sent",
                )
                for email in recipient_status_order
            }
            return recipient_status
