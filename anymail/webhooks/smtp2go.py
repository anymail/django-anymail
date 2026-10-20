import json
from datetime import datetime, timezone

from django.utils.dateparse import parse_datetime

from ..exceptions import AnymailWebhookValidationFailure
from ..signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from .base import AnymailBaseWebhookView


class SMTP2GOTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for SMTP2GO email delivery and engagement tracking webhooks."""

    esp_name = "SMTP2GO"
    signal = tracking

    event_types = {
        "processed": EventType.QUEUED,
        "delivered": EventType.DELIVERED,
        "open": EventType.OPENED,
        "click": EventType.CLICKED,
        "bounce": EventType.BOUNCED,
        "spam": EventType.COMPLAINED,
        "unsubscribe": EventType.UNSUBSCRIBED,
        "resubscribe": EventType.SUBSCRIBED,
        "reject": EventType.REJECTED,
    }

    reject_reasons = {
        "bounce": RejectReason.BOUNCED,
        "spam": RejectReason.SPAM,
        "unsubscribe": RejectReason.UNSUBSCRIBED,
        # Reject can mean suppression, unverified sender, or sandbox mode;
        # the event does not identify a normalized suppression reason.
        "reject": RejectReason.OTHER,
    }

    def parse_events(self, request):
        if request.content_type == "application/json":
            try:
                esp_event = json.loads(request.body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as err:
                raise AnymailWebhookValidationFailure(
                    "Invalid SMTP2GO webhook JSON"
                ) from err
        else:
            esp_event = request.POST.dict()
        if not isinstance(esp_event, dict) or not isinstance(
            esp_event.get("event"), str
        ):
            raise AnymailWebhookValidationFailure("Invalid SMTP2GO webhook event")
        return [self.esp_to_anymail_event(esp_event)]

    @staticmethod
    def parse_timestamp(value):
        if value is None:
            return None
        try:
            # Accept Unix timestamps (including form-encoded numeric strings).
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (TypeError, ValueError, OverflowError, OSError):
            pass
        try:
            timestamp = parse_datetime(value)
        except (TypeError, ValueError):
            return None
        if timestamp is not None and timestamp.tzinfo is None:
            # SMTP2GO documents event time as UTC, even without an offset.
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    def esp_to_anymail_event(self, esp_event):
        event_type = self.event_types.get(esp_event["event"], EventType.UNKNOWN)
        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=self.parse_timestamp(esp_event.get("time")),
            event_id=esp_event.get("id"),
            message_id=esp_event.get("email_id"),
            recipient=esp_event.get("rcpt"),
            reject_reason=self.reject_reasons.get(esp_event["event"]),
            mta_response=esp_event.get("message"),
            user_agent=esp_event.get("user-agent"),
            esp_event=esp_event,
        )
