import base64
import binascii
import json

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from anymail.exceptions import (
    AnymailImproperlyInstalled,
    AnymailWebhookValidationFailure,
    _LazyError,
)
from anymail.utils import get_anymail_setting

try:
    from nacl.exceptions import CryptoError, ValueError
    from nacl.signing import VerifyKey
except ImportError:
    # This will be raised if verification is attempted (and pynacl wasn't found)
    VerifyKey = _LazyError(
        AnymailImproperlyInstalled(missing_package="pynacl", install_extra="mailpace")
    )


from ..inbound import AnymailInboundMessage
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

    webhook_key = None

    def __init__(self, **kwargs):
        self.webhook_key = get_anymail_setting(
            "webhook_key", esp_name=self.esp_name, kwargs=kwargs, allow_bare=True
        )

        super().__init__(**kwargs)

    # Used by base class
    signal = tracking

    event_record_types = {
        # Map MailPace event RecordType --> Anymail normalized event type
        "email.queued": EventType.QUEUED,
        "email.delivered": EventType.DELIVERED,
        "email.deferred": EventType.DEFERRED,
        "email.bounced": EventType.BOUNCED,
        "email.spam": EventType.REJECTED,
    }

    # MailPace doesn't send a signature for inbound webhooks, yet
    # When/if MailPace does this, move this to the parent class
    def validate_request(self, request):
        try:
            signature_base64 = request.headers["X-MailPace-Signature"]
            signature = base64.b64decode(signature_base64)
        except (KeyError, binascii.Error):
            raise AnymailWebhookValidationFailure(
                "MailPace webhook called with invalid or missing signature"
            )

        verify_key_base64 = self.webhook_key

        verify_key = VerifyKey(base64.b64decode(verify_key_base64))

        message = request.body

        try:
            verify_key.verify(message, signature)
        except (CryptoError, ValueError):
            raise AnymailWebhookValidationFailure(
                "MailPace webhook called with incorrect signature"
            )

    def esp_to_anymail_event(self, esp_event):
        event_type = self.event_record_types.get(esp_event["event"], EventType.UNKNOWN)
        payload = esp_event["payload"]

        reject_reason = (
            RejectReason.SPAM
            if event_type == EventType.REJECTED
            else RejectReason.BOUNCED
            if event_type == EventType.BOUNCED
            else None
        )
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

    signal = inbound

    def esp_to_anymail_event(self, esp_event):
        # Use Raw MIME based on guidance here:
        # https://github.com/anymail/django-anymail/blob/main/ADDING_ESPS.md
        message = AnymailInboundMessage.parse_raw_mime(esp_event.get("raw", None))

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timezone.now(),
            event_id=esp_event.get("id", None),
            esp_event=esp_event,
            message=message,
        )
