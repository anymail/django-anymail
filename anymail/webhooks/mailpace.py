import json
from email.utils import unquote

from django.utils.dateparse import parse_datetime

from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from .base import AnymailBaseWebhookView


class MailPaceBaseWebhookView(AnymailBaseWebhookView):
    """Base view class for MailPace webhooks"""

    esp_name = "MailPace"

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        return [self.esp_to_anymail_event(esp_event)]

class MailPaceTrackingWebhookView(MailPaceBaseWebhookView):
    """Handler for MailPace delivery webhooks"""

    # Used by base class
    signal = tracking

    event_record_types = {
        # Map MailPace event RecordType --> Anymail normalized event type
        "email.queued": EventType.QUEUED,
        "email.delivered": EventType.DELIVERED,
        "email.deferred": EventType.DEFERRED,
        "email.bounced": EventType.BOUNCED,
        "email.spam": EventType.REJECTED
    }

    def esp_to_anymail_event(self, esp_event):
        event_type = self.event_record_types.get(esp_event["event"], EventType.UNKNOWN)
        payload = esp_event["payload"]

        reject_reason = RejectReason.SPAM if event_type == EventType.REJECTED else RejectReason.BOUNCED if event_type == EventType.BOUNCED else None
        tags = payload.get("tags", [])

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=parse_datetime(payload["created_at"]),
            event_id=payload["id"],
            message_id=payload["message_id"],
            recipient=payload["to"],
            tags=tags,
            reject_reason=reject_reason,
        )


class MailPaceInboundWebhookView(MailPaceBaseWebhookView):
    """Handler for MailPace inbound webhook"""

    # Used by base class
    signal = tracking

    def esp_to_anymail_event(self, esp_event):
        payload = esp_event.get("payload", {})
        headers = payload.get("headers", [])

        # Extract necessary information from the payload
        subject = payload.get("subject", "")
        from_email = payload.get("from", "")
        to_email = payload.get("to", "")
        text_body = payload.get("text", "")
        html_body = payload.get("html", "")
        message_id = payload.get("message_id", "")

        # Parse date and time
        created_at = parse_datetime(payload.get("created_at", ""))

        # Construct AnymailInboundEvent
        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=created_at,
            message_id=message_id,
            recipient=to_email,
            from_email=from_email,
            subject=subject,
            text=text_body,
            html=html_body,
            headers=headers,
        )
