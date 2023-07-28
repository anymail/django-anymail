import json
from datetime import datetime, timezone
from email.utils import unquote
from urllib.parse import quote, urljoin

import requests

from ..exceptions import AnymailConfigurationError
from ..inbound import AnymailInboundMessage
from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from ..utils import get_anymail_setting
from .base import AnymailBaseWebhookView


class SendinBlueBaseWebhookView(AnymailBaseWebhookView):
    esp_name = "SendinBlue"


class SendinBlueTrackingWebhookView(SendinBlueBaseWebhookView):
    """Handler for SendinBlue delivery and engagement tracking webhooks"""

    signal = tracking

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        if "items" in esp_event:
            # This is an inbound webhook post
            raise AnymailConfigurationError(
                "You seem to have set SendinBlue's *inbound* webhook URL "
                "to Anymail's SendinBlue *tracking* webhook URL."
            )
        return [self.esp_to_anymail_event(esp_event)]

    # SendinBlue's webhook payload data doesn't seem to be documented anywhere.
    # There's a list of webhook events at https://apidocs.sendinblue.com/webhooks/#3.
    event_types = {
        # Map SendinBlue event type: Anymail normalized (event type, reject reason)
        # received even if message won't be sent (e.g., before "blocked"):
        "request": (EventType.QUEUED, None),
        "delivered": (EventType.DELIVERED, None),
        "hard_bounce": (EventType.BOUNCED, RejectReason.BOUNCED),
        "soft_bounce": (EventType.BOUNCED, RejectReason.BOUNCED),
        "blocked": (EventType.REJECTED, RejectReason.BLOCKED),
        "spam": (EventType.COMPLAINED, RejectReason.SPAM),
        "invalid_email": (EventType.BOUNCED, RejectReason.INVALID),
        "deferred": (EventType.DEFERRED, None),
        "opened": (EventType.OPENED, None),  # see also unique_opened below
        "click": (EventType.CLICKED, None),
        "unsubscribe": (EventType.UNSUBSCRIBED, None),
        # shouldn't occur for transactional messages:
        "list_addition": (EventType.SUBSCRIBED, None),
        "unique_opened": (EventType.OPENED, None),  # you'll *also* receive an "opened"
    }

    def esp_to_anymail_event(self, esp_event):
        esp_type = esp_event.get("event")
        event_type, reject_reason = self.event_types.get(
            esp_type, (EventType.UNKNOWN, None)
        )
        recipient = esp_event.get("email")

        try:
            # SendinBlue supplies "ts", "ts_event" and "date" fields, which seem to be
            # based on the timezone set in the account preferences (and possibly with
            # inconsistent DST adjustment). "ts_epoch" is the only field that seems to
            # be consistently UTC; it's in milliseconds
            timestamp = datetime.fromtimestamp(
                esp_event["ts_epoch"] / 1000.0, tz=timezone.utc
            )
        except (KeyError, ValueError):
            timestamp = None

        tags = []
        try:
            # If `tags` param set on send, webhook payload includes 'tags' array field.
            tags = esp_event["tags"]
        except KeyError:
            try:
                # If `X-Mailin-Tag` header set on send, webhook payload includes single
                # 'tag' string. (If header not set, webhook 'tag' will be the template
                # name for template sends.)
                tags = [esp_event["tag"]]
            except KeyError:
                pass

        try:
            metadata = json.loads(esp_event["X-Mailin-custom"])
        except (KeyError, TypeError):
            metadata = {}

        return AnymailTrackingEvent(
            description=None,
            esp_event=esp_event,
            # SendinBlue doesn't provide a unique event id:
            event_id=None,
            event_type=event_type,
            message_id=esp_event.get("message-id"),
            metadata=metadata,
            mta_response=esp_event.get("reason"),
            recipient=recipient,
            reject_reason=reject_reason,
            tags=tags,
            timestamp=timestamp,
            user_agent=None,
            click_url=esp_event.get("link"),
        )


class SendinBlueInboundWebhookView(SendinBlueBaseWebhookView):
    """Handler for SendinBlue inbound email webhooks"""

    signal = inbound

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # API is required to fetch inbound attachment content:
        self.api_key = get_anymail_setting(
            "api_key",
            esp_name=self.esp_name,
            kwargs=kwargs,
            allow_bare=True,
        )
        self.api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://api.brevo.com/v3/",
        )
        if not self.api_url.endswith("/"):
            self.api_url += "/"

    def parse_events(self, request):
        payload = json.loads(request.body.decode("utf-8"))
        try:
            esp_events = payload["items"]
        except KeyError:
            # This is not n inbound webhook post
            raise AnymailConfigurationError(
                "You seem to have set SendinBlue's *tracking* webhook URL "
                "to Anymail's SendinBlue *inbound* webhook URL."
            )
        else:
            return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    def esp_to_anymail_event(self, esp_event):
        # Inbound event's "Uuid" is documented as
        # "A list of recipients UUID (can be used with the Public API)".
        # In practice, it seems to be a single-item list (even when sending
        # to multiple inbound recipients at once) that uniquely identifies this
        # inbound event. (And works as a param for the /inbound/events/{uuid} API
        # that will "Fetch all events history for one particular received email.")
        try:
            event_id = esp_event["Uuid"][0]
        except (KeyError, IndexError):
            event_id = None

        attachments = [
            self._fetch_attachment(attachment)
            for attachment in esp_event.get("Attachments", [])
        ]
        headers = [
            (name, value)
            for name, values in esp_event.get("Headers", {}).items()
            # values is string if single header instance, list of string if multiple
            for value in ([values] if isinstance(values, str) else values)
        ]

        # (esp_event From, To, Cc, ReplyTo, Subject, Date, etc. are also in Headers)
        message = AnymailInboundMessage.construct(
            headers=headers,
            text=esp_event.get("RawTextBody", ""),
            html=esp_event.get("RawHtmlBody", ""),
            attachments=attachments,
        )

        if message["Return-Path"]:
            message.envelope_sender = unquote(message["Return-Path"])
        if message["Delivered-To"]:
            message.envelope_recipient = unquote(message["Delivered-To"])
        message.stripped_text = esp_event.get("ExtractedMarkdownMessage")

        # Documented as "Spam.Score" object, but both example payload
        # and actual received payload use single "SpamScore" field:
        message.spam_score = esp_event.get("SpamScore")

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=None,  # Brevo doesn't provide inbound event timestamp
            event_id=event_id,
            esp_event=esp_event,
            message=message,
        )

    def _fetch_attachment(self, attachment):
        # Download attachment content from SendinBlue API.
        # FUTURE: somehow defer download until attachment is accessed?
        token = attachment["DownloadToken"]
        url = urljoin(self.api_url, f"inbound/attachments/{quote(token, safe='')}")
        response = requests.get(url, headers={"api-key": self.api_key})
        response.raise_for_status()  # or maybe just log and continue?

        content = response.content
        # Prefer response Content-Type header to attachment ContentType field,
        # as the header will include charset but the ContentType field won't.
        content_type = response.headers.get("Content-Type") or attachment["ContentType"]
        return AnymailInboundMessage.construct_attachment(
            content_type=content_type,
            content=content,
            filename=attachment.get("Name"),
            content_id=attachment.get("ContentID"),
        )
