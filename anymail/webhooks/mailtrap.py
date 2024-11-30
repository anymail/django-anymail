import json
import sys
from datetime import datetime, timezone

if sys.version_info < (3, 11):
    from typing_extensions import Dict, Literal, NotRequired, TypedDict, Union
else:
    from typing import Dict, Literal, NotRequired, TypedDict, Union

from ..signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from .base import AnymailBaseWebhookView


class MailtrapEvent(TypedDict):
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
    custom_variables: NotRequired[Dict[str, Union[str, int, float, bool]]]
    reason: NotRequired[str]
    response: NotRequired[str]
    response_code: NotRequired[int]
    bounce_category: NotRequired[str]
    ip: NotRequired[str]
    user_agent: NotRequired[str]
    url: NotRequired[str]


class MailtrapTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for Mailtrap delivery and engagement tracking webhooks"""

    esp_name = "Mailtrap"
    signal = tracking

    def parse_events(self, request):
        esp_events: list[MailtrapEvent] = json.loads(request.body.decode("utf-8")).get(
            "events", []
        )
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

    def esp_to_anymail_event(self, esp_event: MailtrapEvent):
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
