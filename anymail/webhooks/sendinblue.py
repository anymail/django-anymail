import json
from datetime import datetime, timezone

from ..signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from .base import AnymailBaseWebhookView


class SendinBlueTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for SendinBlue delivery and engagement tracking webhooks"""

    esp_name = "SendinBlue"
    signal = tracking

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
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
