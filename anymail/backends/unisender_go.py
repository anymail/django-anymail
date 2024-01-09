from __future__ import annotations

import datetime
import typing
import uuid

from anymail.backends.base_requests import AnymailRequestsBackend, RequestsPayload
from anymail.exceptions import AnymailConfigurationError
from anymail.message import AnymailRecipientStatus
from anymail.utils import Attachment, EmailAddress, get_anymail_setting
from django.core.mail import EmailMessage
from requests import Response
from requests.structures import CaseInsensitiveDict


class EmailBackend(AnymailRequestsBackend):
    """Unsidender GO v1 API Email Backend"""

    esp_name = 'UnisenderGo'

    def __init__(self, **kwargs: typing.Any):
        """Init options from Django settings"""
        esp_name = self.esp_name

        self.api_key = get_anymail_setting(
            'api_key', esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )

        self.generate_message_id = get_anymail_setting(
            'generate_message_id', esp_name=esp_name, kwargs=kwargs, default=True
        )
        self.merge_field_format = get_anymail_setting(
            'merge_field_format', esp_name=esp_name, kwargs=kwargs, default=None
        )

        api_url = get_anymail_setting(
            'api_url', esp_name=esp_name, kwargs=kwargs, default=None
        )  # Don't set default, because url depends on location
        # url template is https://go<number>.unisender.<lang>/<lang>/transactional/api/v1

        if api_url is None:
            raise AnymailConfigurationError('api_url required')
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message: EmailMessage, defaults: dict) -> UnisenderGoPayload:
        return UnisenderGoPayload(message, defaults, self)

    def parse_recipient_status(
        self, response: Response, payload: UnisenderGoPayload, message: EmailMessage
    ) -> dict:
        return {
            recip.addr_spec: AnymailRecipientStatus(
                message_id=payload.message_ids.get(recip.addr_spec), status='queued'
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
          "amp": "<!doctype html><html amp4email><head> <meta charset=\"utf-8\"><script async src=\"https://cdn.ampproject.org/v0.js\"></script> <style amp4email-boilerplate>body{visibility:hidden}</style></head><body> Hello, AMP4EMAIL world.</body></html>"
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
          "List-Unsubscribe": "<mailto: unsubscribe@example.com?subject=unsubscribe>, <http://www.example.com/unsubscribe/{{CustomerId}}>"
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
        self.all_recipients: list[EmailAddress] = []  # used for backend.parse_recipient_status
        self.generate_message_id = backend.generate_message_id
        self.message_ids: dict = {}  # recipient -> generated message_id mapping
        self.merge_data: dict = {}  # late-bound per-recipient data
        self.merge_global_data: dict = {}
        self.merge_metadata: dict = {}

        http_headers = kwargs.pop('headers', {})
        http_headers['Content-Type'] = 'application/json'
        http_headers['Accept'] = 'application/json'
        http_headers['X-API-key'] = backend.api_key
        super().__init__(message, defaults, backend, headers=http_headers, *args, **kwargs)

    def get_api_endpoint(self) -> str:
        return 'email/send.json'

    def init_payload(self) -> None:
        self.data = {'headers': CaseInsensitiveDict()}  # becomes json

        # by default, Unisender Go adds unsubscribe link
        # to fix this, you have to request tech support
        if get_anymail_setting('skip_unsubscribe', esp_name=self.esp_name, default=False) is True:
            self.data['skip_unsubscribe'] = 1

    def serialize_data(self) -> str:
        """Performs any necessary serialization on self.data, and returns the result."""
        if self.generate_message_id:
            self.set_anymail_id()

        if not self.data['headers']:
            del self.data['headers']  # don't send empty headers

        return self.serialize_json({'message': self.data})

    def set_merge_data(self, merge_data: dict[str, dict[str, str]]) -> None:
        if not merge_data:
            return
        for recipient in self.data['recipients']:
            recipient_email = recipient['email']
            recipient.setdefault('substitutions', {})
            recipient['substitutions'] = {
                **merge_data[recipient_email],
                **recipient['substitutions'],
            }

    def set_merge_global_data(self, merge_global_data: dict[str, str]) -> None:
        self.data.setdefault('global_substitutions', {})
        self.data['global_substitutions'] = {
            **self.data['global_substitutions'],
            **merge_global_data,
        }

    def set_anymail_id(self) -> None:
        """Ensure each personalization has a known anymail_id for later event tracking"""
        for recipient in self.data['recipients']:
            anymail_id = str(uuid.uuid4())

            recipient.setdefault('metadata', {})
            recipient['metadata']['message_id'] = anymail_id

            email_address = recipient['email']
            self.message_ids[email_address] = anymail_id

    def set_from_email(self, email: EmailAddress) -> None:
        self.data['from_email'] = email.addr_spec
        self.data['from_name'] = email.display_name

    def set_recipients(self, recipient_type: str, emails: list[EmailAddress]) -> None:
        if not emails:
            return
        self.data['recipients'] = [
            {'email': email.addr_spec, 'substitutions': {'to_name': email.display_name}}
            for email in emails
        ]
        self.all_recipients += emails

    def set_subject(self, subject: str) -> None:
        if subject != '':  # see note in set_text_body about template rendering
            self.data['subject'] = subject

    def set_reply_to(self, emails: list[EmailAddress]) -> None:
        # Unisunder GO only supports a single address in the reply_to API param.
        if len(emails) > 1:
            self.unsupported_feature('multiple reply_to addresses')
        if len(emails) > 0:
            self.data['reply_to'] = emails[0].addr_spec

    def set_extra_headers(self, headers: dict[str, str]) -> None:
        self.data['headers'].update(headers)

    def set_text_body(self, body: str) -> None:
        if body == '':
            return
        if 'body' not in self.data:
            self.data['body'] = {}
        self.data['body']['plaintext'] = body

    def set_html_body(self, body: str) -> None:
        if body == '':
            return
        if 'body' not in self.data:
            self.data['body'] = {}
        self.data['body']['html'] = body

    def add_attachment(self, attachment: Attachment) -> None:
        att = {
            'content': attachment.b64content,
            'type': attachment.mimetype,
            'name': attachment.name or '',  # required -- submit empty string if unknown
        }
        if attachment.inline:
            self.data.setdefault('inline_attachments', []).append(att)
        else:
            self.data.setdefault('attachments', []).append(att)

    def set_metadata(self, metadata: dict[str, str]) -> None:
        self.data['global_metadata'] = metadata

    def set_send_at(self, send_at: datetime.datetime) -> None:
        self.data.setdefault('options', {})['send_at'] = send_at

    def set_tags(self, tags: dict[str, str]) -> None:
        self.data['tags'] = tags

    def set_template_id(self, template_id: str) -> None:
        self.data['template_id'] = template_id
