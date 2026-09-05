import hashlib
import hmac
import json
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from urllib.parse import quote, urljoin

import requests
from django.utils.crypto import constant_time_compare

from ..exceptions import AnymailConfigurationError, AnymailWebhookValidationFailure
from ..inbound import AnymailInboundMessage
from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from ..utils import DEFAULT_DOWNLOAD_CHUNK_SIZE, get_anymail_setting
from .base import AnymailBaseWebhookView

if sys.version_info < (3, 11):
    from typing import Literal

    from typing_extensions import NotRequired, TypedDict
else:
    from typing import Literal, NotRequired, TypedDict


class MailtrapWebhookView(AnymailBaseWebhookView):
    esp_name = "Mailtrap"

    def __init__(self, _secret_name, **kwargs):
        signing_secret = get_anymail_setting(
            _secret_name,
            esp_name=self.esp_name,
            default=None,
            kwargs=kwargs,
        )
        if signing_secret is None:
            self.signing_secret = None
        else:
            self.signing_secret = signing_secret.encode()
            self.warn_if_no_basic_auth = False
        self._secret_setting_name = f"{self.esp_name}_{_secret_name}".upper()
        super().__init__(**kwargs)

    def validate_request(self, request):
        if self.signing_secret is None:
            return

        try:
            signature = request.headers["Mailtrap-Signature"]
        except KeyError:
            raise AnymailWebhookValidationFailure(
                "Mailtrap webhook called without signature"
            ) from None

        expected_signature = hmac.new(
            key=self.signing_secret,
            msg=request.body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not constant_time_compare(signature, expected_signature):
            raise AnymailWebhookValidationFailure(
                f"Mailtrap webhook called with incorrect signature"
                f" (check Anymail {self._secret_setting_name} setting)"
            )


class MailtrapReceiveEvent(TypedDict):
    # https://docs.mailtrap.io/email-api-smtp/advanced/webhooks
    event: Literal[
        "delivery",
        "open",
        "click",
        "unsubscribe",
        "spam",
        "soft bounce",
        "bounce",
        "suspension",
        "reject",
    ]
    message_id: str
    sending_stream: Literal["transactional", "bulk"]
    email: str
    timestamp: int
    event_id: str
    category: NotRequired[str]
    custom_variables: NotRequired[dict[str, str | int | float | bool]]
    reason: NotRequired[str]
    response: NotRequired[str]
    response_code: NotRequired[int]
    bounce_category: NotRequired[str]
    ip: NotRequired[str]
    user_agent: NotRequired[str]
    url: NotRequired[str]


class MailtrapTrackingWebhookView(MailtrapWebhookView):
    """Handler for Mailtrap delivery and engagement tracking webhooks"""

    signal = tracking

    # (Declaring class attr allows override by kwargs in View.as_view.)
    tracking_secret = None

    def __init__(self, **kwargs):
        super().__init__(_secret_name="tracking_secret", **kwargs)

    def parse_events(self, request):
        esp_events: list[MailtrapReceiveEvent] = json.loads(
            request.body.decode("utf-8")
        ).get("events", [])
        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    # https://help.mailtrap.io/article/87-statuses-and-events
    event_types = {
        # Map Mailtrap event: Anymail normalized type
        "delivery": EventType.DELIVERED,
        "open": EventType.OPENED,
        "click": EventType.CLICKED,
        "bounce": EventType.BOUNCED,
        "soft bounce": EventType.DEFERRED,
        "spam": EventType.COMPLAINED,
        "unsubscribe": EventType.UNSUBSCRIBED,
        "reject": EventType.REJECTED,
        "suspension": EventType.DEFERRED,
    }

    reject_reasons = {
        # Map Mailtrap event type to Anymail normalized reject_reason
        "bounce": RejectReason.BOUNCED,
        "blocked": RejectReason.BLOCKED,
        "spam": RejectReason.SPAM,
        "unsubscribe": RejectReason.UNSUBSCRIBED,
        "reject": RejectReason.BLOCKED,
        "suspension": RejectReason.OTHER,
        "soft bounce": RejectReason.OTHER,
    }

    def esp_to_anymail_event(self, esp_event: MailtrapReceiveEvent):
        if esp_event["event"].startswith("inbound"):
            raise AnymailConfigurationError(
                "You seem to have set Mailtrap's *inbound* webhook "
                "to Anymail's Mailtrap *tracking* webhook URL."
            )

        event_type = self.event_types.get(esp_event["event"], EventType.UNKNOWN)
        timestamp = datetime.fromtimestamp(esp_event["timestamp"], tz=timezone.utc)
        reject_reason = self.reject_reasons.get(esp_event["event"])
        custom_variables = esp_event.get("custom_variables", {})
        category = esp_event.get("category")
        tags = [category] if category else []

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=esp_event["message_id"],
            event_id=esp_event.get("event_id"),
            recipient=esp_event.get("email"),
            reject_reason=reject_reason,
            mta_response=esp_event.get("response"),
            tags=tags,
            metadata=custom_variables,
            click_url=esp_event.get("url"),
            user_agent=esp_event.get("user_agent"),
            esp_event=esp_event,
        )


class MailtrapInboundEvent(TypedDict):
    # Notification webhook payload
    event: Literal["inbound.message_received"]
    event_id: str
    timestamp: int
    inbox_id: int
    message_id: str
    # from: str


class MailtrapInboundMessage(TypedDict):
    # Result from get inbound message API
    # https://docs.mailtrap.io/developers/inbound/messages#get-api-inbound-inboxes-inbox_id-messages-id
    id: str
    raw_message_url: str
    raw_message_expires_at: NotRequired[str]
    # (There are several other fields that Anymail doesn't currently use.)


class MailtrapInboundWebhookView(MailtrapWebhookView):
    """Handler for Mailtrap inbound webhook events."""

    signal = inbound

    # (Declaring class attr allows override by kwargs in View.as_view.)
    api_token = None
    api_url = None
    inbound_secret = None

    def __init__(self, **kwargs):
        self.api_token = get_anymail_setting(
            "api_token", esp_name=self.esp_name, kwargs=kwargs, allow_bare=True
        )
        self.api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://mailtrap.io/api/",
        )
        if not self.api_url.endswith("/"):
            self.api_url += "/"
        self.chunk_size = get_anymail_setting(
            "download_chunk_size",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=DEFAULT_DOWNLOAD_CHUNK_SIZE,
        )
        super().__init__(_secret_name="inbound_secret", **kwargs)

    def parse_events(self, request):
        esp_events: list[MailtrapInboundEvent] = json.loads(
            request.body.decode("utf-8")
        ).get("events", [])
        return [
            self.esp_to_anymail_event(esp_event)
            for esp_event in esp_events
            if esp_event is not None
        ]

    def esp_to_anymail_event(
        self, esp_event: MailtrapInboundEvent
    ) -> AnymailInboundEvent:
        # Mailtrap's sample payload uses "inbound_message_received",
        # actual webhook calls use "inbound.message_received".
        if esp_event["event"] not in {
            "inbound.message_received",
            "inbound_message_received",
        }:
            if esp_event["event"].startswith("inbound"):
                raise ValueError(
                    f"Unknown Mailtrap inbound event type: {esp_event['event']}"
                )
            raise AnymailConfigurationError(
                "You seem to have set Mailtrap's *tracking* webhook "
                "to Anymail's Mailtrap *inbound* webhook URL."
            )

        inbox_id = esp_event.get("inbox_id")
        if inbox_id is None or inbox_id == 1:
            # Ignore example payload from "Test your integration"
            return None
        message_id = esp_event["message_id"]
        message_data = self.fetch_inbound_message(inbox_id, message_id)

        # Download the full raw message. (message_data isn't quite enough to
        # reconstruct the inbound message, and any attachments would require
        # separate downloads anyway. Easier to do it all at once.)
        # The raw_message_url is a signed S3 URL -- no auth required.
        raw_message_url = message_data["raw_message_url"]
        chunks_iterator = self.fetch_raw_message_chunks(raw_message_url)
        message = AnymailInboundMessage.parse_raw_mime_chunks(chunks_iterator)

        try:
            timestamp = datetime.fromtimestamp(
                esp_event["timestamp"] / 1000, tz=timezone.utc
            )
        except (KeyError, TypeError, ValueError):
            timestamp = None

        # Mailtrap doesn't seem to provide envelope_sender, envelope_recipient,
        # or any spam scoring.

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timestamp,
            # esp_event["event_id"] may not be stable across retries;
            # inbox_id+message_id is unique to an inbound message:
            event_id=f"{inbox_id}/{message_id}",
            # The fetched inbound message_data is more useful than
            # (and includes nearly all of) the esp_event webhook payload:
            esp_event=message_data,
            message=message,
        )

    def fetch_inbound_message(
        self, inbox_id: int, message_id: str
    ) -> MailtrapInboundMessage:
        message_url = urljoin(
            self.api_url,
            f"inbound/inboxes/{quote(str(inbox_id), safe='')}"
            f"/messages/{quote(message_id, safe='')}",
        )
        response = requests.get(
            message_url, headers={"Authorization": f"Bearer {self.api_token}"}
        )
        response.raise_for_status()
        return response.json()

    def fetch_raw_message_chunks(self, raw_message_url: str) -> Iterator[bytes]:
        # The raw_message_url is a signed S3 URL -- no auth required.
        with requests.get(raw_message_url, stream=True) as response:
            response.raise_for_status()
            yield from response.iter_content(chunk_size=self.chunk_size)
