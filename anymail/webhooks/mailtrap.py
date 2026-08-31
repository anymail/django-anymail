import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone

from django.utils.crypto import constant_time_compare

from ..exceptions import AnymailWebhookValidationFailure
from ..signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from ..utils import get_anymail_setting
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
