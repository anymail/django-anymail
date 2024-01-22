from __future__ import annotations

import datetime
import typing
import uuid

from django.core.mail import EmailMessage
from requests import Response
from requests.structures import CaseInsensitiveDict

from anymail.backends.base_requests import AnymailRequestsBackend, RequestsPayload
from anymail.exceptions import AnymailConfigurationError
from anymail.message import AnymailRecipientStatus
from anymail.utils import Attachment, EmailAddress, get_anymail_setting


class EmailBackend(AnymailRequestsBackend):
    """Unsidender GO v1 API Email Backend"""

    esp_name = "Unisender Go"

    def __init__(self, **kwargs: typing.Any):
        """Init options from Django settings"""
        esp_name = self.esp_name

        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )

        self.generate_message_id = get_anymail_setting(
            "generate_message_id", esp_name=esp_name, kwargs=kwargs, default=True
        )
        self.merge_field_format = get_anymail_setting(
            "merge_field_format", esp_name=esp_name, kwargs=kwargs, default=None
        )

        api_url = get_anymail_setting("api_url", esp_name=esp_name, kwargs=kwargs)
        # Don't set default, because url depends on location

        super().__init__(api_url, **kwargs)

    def build_message_payload(
        self, message: EmailMessage, defaults: dict
    ) -> UnisenderGoPayload:
        return UnisenderGoPayload(message, defaults, self)

    def parse_recipient_status(
        self, response: Response, payload: UnisenderGoPayload, message: EmailMessage
    ) -> dict:
        return {
            recip.addr_spec: AnymailRecipientStatus(
                message_id=payload.message_ids.get(recip.addr_spec), status="queued"
            )
            for recip in payload.all_recipients
        }


class UnisenderGoPayload(RequestsPayload):
    """
    API EXAMPLE:

    request_body = {
      "message": {
        "recipients": [
          {
            "email": "user@example.com",
            "substitutions": {
              "CustomerId": 12452,
              "to_name": "John Smith"
            },
            "metadata": {
              "campaign_id": "c77f4f4e-3561-49f7-9f07-c35be01b4f43",
              "customer_hash": "b253ac7"
            }
          }
        ],
        "template_id": "string",
        "tags": [
          "string1"
        ],
        "skip_unsubscribe": 0,
        "global_language": "string",
        "template_engine": "simple",
        "global_substitutions": {
          "property1": "string",
          "property2": "string"
        },
        "global_metadata": {
          "property1": "string",
          "property2": "string"
        },
        "body": {
          "html": "<b>Hello, {{to_name}}</b>",
          "plaintext": "Hello, {{to_name}}",
          "amp": "<!doctype html>Some HTML staff</html>"
        },
        "subject": "string",
        "from_email": "user@example.com",
        "from_name": "John Smith",
        "reply_to": "user@example.com",
        "track_links": 0,
        "track_read": 0,
        "bypass_global": 0,
        "bypass_unavailable": 0,
        "bypass_unsubscribed": 0,
        "bypass_complained": 0,
        "headers": {
          "X-MyHeader": "some data",
          "List-Unsubscribe": (
            "<mailto: unsubscribe@example.com?subject=unsubscribe>, "
            "<http://www.example.com/unsubscribe/{{CustomerId}}>"
          )
        },
        "attachments": [
          {
            "type": "text/plain",
            "name": "readme.txt",
            "content": "SGVsbG8sIHdvcmxkIQ=="
          }
        ],
        "inline_attachments": [
          {
            "type": "image/gif",
            "name": "IMAGECID1",
            "content": "R0lGODdhAwADAIABAP+rAP///ywAAAAAAwADAAACBIQRBwUAOw=="
          }
        ],
        "options": {
          "send_at": "2021-11-19 10:00:00",
          "unsubscribe_url": "https://example.org/unsubscribe/{{CustomerId}}",
          "custom_backend_id": 0,
          "smtp_pool_id": "string"
        }
      }
    }
    """

    data: dict

    def __init__(
        self,
        message: EmailMessage,
        defaults: dict,
        backend: EmailBackend,
        *args: typing.Any,
        **kwargs: typing.Any,
    ):
        self.all_recipients: list[
            EmailAddress
        ] = []  # used for backend.parse_recipient_status
        self.generate_message_id = backend.generate_message_id
        self.message_ids: dict = {}  # recipient -> generated message_id mapping
        self.merge_data: dict = {}  # late-bound per-recipient data
        self.merge_global_data: dict = {}
        self.merge_metadata: dict = {}

        http_headers = kwargs.pop("headers", {})
        http_headers["Content-Type"] = "application/json"
        http_headers["Accept"] = "application/json"
        http_headers["X-API-key"] = backend.api_key
        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self) -> str:
        return "email/send.json"

    def set_skip_unsubscribe(self, extra: dict) -> None:
        """
        By default, Unisender Go adds unsubscribe link.

        It's needed due to guarantee not abusing users with spam.
        Before to use this setting, you have to request tech support.

        Expects skip_unsubscribe to be True or False, then transfers it to 0 or 1.
        Anyway, works if skip_unsubscribe converts to True or False (for flexibility).
        """
        if "skip_unsubscribe" in extra and extra["skip_unsubscribe"]:
            self.data["skip_unsubscribe"] = 1

    def set_global_language(self, extra):
        """
        Language for link language and unsubscribe page.
        Options: 'be', 'de', 'en', 'es', 'fr', 'it', 'pl', 'pt', 'ru', 'ua', 'kz'.
        """
        if "global_language" in extra and extra["global_language"]:
            self.data["global_language"] = extra["global_language"]

    def set_amp(self, extra):
        """AMP-part of email"""
        if "amp" in extra and extra["amp"]:
            self.data["amp"] = extra["amp"]

    def set_bypass_settings(self, extra):
        """
        Set extra settings with bypass prefix.

        bypass_global: optional 0/1 (0 by default)
        If 1: To ignore list of global unavailability.
        Can be forbidden for some system records.

        bypass_unavailable: optional 0/1 (0 by default)
        If 1: To ignore current project unavailable addresses.
        Works only with bypass_global = 1.

        bypass_unsubscribed: optional 0/1 (0 by default)
        If 1: To ignore list of unsubscribed people.
        Works only with bypass_global=1 and requires tech support's approve.

        bypass_complained: optional 0/1 (0 by default)
        If 1: To ignore complainers on project.
        Works only with bypass_global=1 and requires tech support's approve.
        """
        bypass_fields = (
            "bypass_global",
            "bypass_unavailable",
            "bypass_unsubscribed",
            "bypass_complained",
        )
        for field in bypass_fields:
            if field in extra:
                self.data[field] = extra[field]

    def set_template_engine(self, extra):
        """
        Templating choosing parameter. Can be either 'simple' or 'velocity' or 'none'.

        'simple' by default.
        'none' available only for emails with
        ‘track_links’ and ‘track_read’ equal 0 and with turned off unsubscribe block.

        "Simple" templating is for simple substitutions.
        "Velocity" templating allows loops, arrays, etc.
        """
        if "template_engine" in extra and extra["template_engine"]:
            self.data["template_engine"] = extra["template_engine"]

    def set_esp_extra(self, extra: dict) -> None:
        """Set every esp extra parameter with its docstring"""
        self.set_skip_unsubscribe(extra)
        self.set_global_language(extra)
        self.set_template_engine(extra)
        self.set_amp(extra)
        self.set_bypass_settings(extra)

    def set_global_settings_from_config(self):
        """
        Here we set variables from global config.

        If there is no esp_extra in backend's kwargs, set_esp_extra won't be called.
        So we have to set default values in init.
        You can change them with backend's kwarg esp_extra.
        """
        if get_anymail_setting(
            "skip_unsubscribe", esp_name=self.esp_name, default=False
        ):
            self.data["skip_unsubscribe"] = 1

        global_language = get_anymail_setting(
            "global_language", esp_name=self.esp_name, default=None
        )
        if global_language:
            self.data["global_language"] = global_language

    def init_payload(self) -> None:
        self.data = {"headers": CaseInsensitiveDict()}  # becomes json
        self.set_global_settings_from_config()

    def serialize_data(self) -> str:
        """Performs any necessary serialization on self.data, and returns the result."""
        if self.generate_message_id:
            self.set_anymail_id()

        if not self.data["headers"]:
            del self.data["headers"]  # don't send empty headers

        return self.serialize_json({"message": self.data})

    def set_merge_data(self, merge_data: dict[str, dict[str, str]]) -> None:
        if not merge_data:
            return
        for recipient in self.data["recipients"]:
            recipient_email = recipient["email"]
            recipient.setdefault("substitutions", {})
            recipient["substitutions"] = {
                **merge_data[recipient_email],
                **recipient["substitutions"],
            }

    def set_merge_global_data(self, merge_global_data: dict[str, str]) -> None:
        self.data.setdefault("global_substitutions", {})
        self.data["global_substitutions"] = {
            **self.data["global_substitutions"],
            **merge_global_data,
        }

    def set_anymail_id(self) -> None:
        """Ensure each personalization has a known anymail_id for event tracking"""
        for recipient in self.data["recipients"]:
            anymail_id = str(uuid.uuid4())

            recipient.setdefault("metadata", {})
            recipient["metadata"]["message_id"] = anymail_id

            email_address = recipient["email"]
            self.message_ids[email_address] = anymail_id

    def set_from_email(self, email: EmailAddress) -> None:
        self.data["from_email"] = email.addr_spec
        self.data["from_name"] = email.display_name

    def set_recipients(self, recipient_type: str, emails: list[EmailAddress]) -> None:
        if not emails:
            return
        self.data["recipients"] = [
            {"email": email.addr_spec, "substitutions": {"to_name": email.display_name}}
            for email in emails
        ]
        self.all_recipients += emails

    def set_subject(self, subject: str) -> None:
        if subject != "":  # see note in set_text_body about template rendering
            self.data["subject"] = subject

    def set_reply_to(self, emails: list[EmailAddress]) -> None:
        # Unisunder GO only supports a single address in the reply_to API param.
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if len(emails) > 0:
            self.data["reply_to"] = emails[0].addr_spec

    def set_extra_headers(self, headers: dict[str, str]) -> None:
        """
        Available service extra headers are:
        - X-UNISENDER-GO-Global-Language
        - X-UNISENDER-GO-Template-Engine

        Value in header has higher priority than in config.
        """
        self.data["headers"].update(headers)

    def set_text_body(self, body: str) -> None:
        if body == "":
            return
        if "body" not in self.data:
            self.data["body"] = {}
        self.data["body"]["plaintext"] = body

    def set_html_body(self, body: str) -> None:
        if body == "":
            return
        if "body" not in self.data:
            self.data["body"] = {}
        self.data["body"]["html"] = body

    def add_attachment(self, attachment: Attachment) -> None:
        """Seek! Name must not have / in it, esp fails in this case."""
        if "/" in attachment.name:
            raise AnymailConfigurationError("found '/' in attachment name")
        att = {
            "content": attachment.b64content,
            "type": attachment.mimetype,
            "name": attachment.name or "",  # required - submit empty string if unknown
        }
        if attachment.inline:
            self.data.setdefault("inline_attachments", []).append(att)
        else:
            self.data.setdefault("attachments", []).append(att)

    def set_metadata(self, metadata: dict[str, str]) -> None:
        self.data["global_metadata"] = metadata

    def set_send_at(self, send_at: datetime.datetime) -> None:
        self.data.setdefault("options", {})["send_at"] = send_at

    def set_tags(self, tags: dict[str, str]) -> None:
        self.data["tags"] = tags

    def set_template_id(self, template_id: str) -> None:
        self.data["template_id"] = template_id
