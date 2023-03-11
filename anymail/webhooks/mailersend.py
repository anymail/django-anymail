import hashlib
import hmac
import json

from django.utils.crypto import constant_time_compare
from django.utils.dateparse import parse_datetime

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
from ..utils import get_anymail_setting
from .base import AnymailBaseWebhookView


class MailerSendBaseWebhookView(AnymailBaseWebhookView):
    """Base view class for MailerSend webhooks"""

    esp_name = "MailerSend"
    warn_if_no_basic_auth = False  # because we validate against signature

    def __init__(self, _secret_name, **kwargs):
        signing_secret = get_anymail_setting(
            _secret_name,
            esp_name=self.esp_name,
            kwargs=kwargs,
        )
        # hmac.new requires bytes key:
        self.signing_secret = signing_secret.encode("ascii")
        self._secret_setting_name = f"{self.esp_name}_{_secret_name}".upper()
        super().__init__(**kwargs)

    def validate_request(self, request):
        super().validate_request(request)  # first check basic auth if enabled
        try:
            signature = request.headers["Signature"]
        except KeyError:
            raise AnymailWebhookValidationFailure(
                "MailerSend webhook called without signature"
            ) from None

        expected_signature = hmac.new(
            key=self.signing_secret,
            msg=request.body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not constant_time_compare(signature, expected_signature):
            raise AnymailWebhookValidationFailure(
                f"MailerSend webhook called with incorrect signature"
                f" (check Anymail {self._secret_setting_name} setting)"
            )


class MailerSendTrackingWebhookView(MailerSendBaseWebhookView):
    """Handler for MailerSend delivery and engagement tracking webhooks"""

    signal = tracking

    # (Declaring class attr allows override by kwargs in View.as_view.)
    signing_secret = None

    def __init__(self, **kwargs):
        super().__init__(_secret_name="signing_secret", **kwargs)

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        event_type = esp_event.get("type")
        if event_type == "inbound.message":
            raise AnymailConfigurationError(
                "You seem to have set MailerSend's *inbound* route endpoint"
                " to Anymail's MailerSend *activity tracking* webhook URL. "
            )
        return [self.esp_to_anymail_event(esp_event)]

    event_types = {
        # Map MailerSend activity.type: Anymail normalized type
        "sent": EventType.SENT,
        "delivered": EventType.DELIVERED,
        "soft_bounced": EventType.BOUNCED,
        "hard_bounced": EventType.BOUNCED,
        "opened": EventType.OPENED,
        "clicked": EventType.CLICKED,
        "unsubscribed": EventType.UNSUBSCRIBED,
        "spam_complaint": EventType.COMPLAINED,
    }

    morph_reject_reasons = {
        # Map MailerSend morph.object (type): Anymail normalized RejectReason
        "recipient_bounce": RejectReason.BOUNCED,
        "spam_complaint": RejectReason.SPAM,
        "recipient_unsubscribe": RejectReason.UNSUBSCRIBED,
        # any others?
    }

    def esp_to_anymail_event(self, esp_event):
        activity_data = esp_event.get("data", {})
        email_data = activity_data.get("email", {})
        message_data = email_data.get("message", {})
        recipient_data = email_data.get("recipient", {})

        event_type = self.event_types.get(activity_data["type"], EventType.UNKNOWN)
        event_id = activity_data.get("id")
        recipient = recipient_data.get("email")
        message_id = message_data.get("id")
        tags = email_data.get("tags", [])

        try:
            timestamp = parse_datetime(activity_data["created_at"])
        except KeyError:
            timestamp = None

        # Additional, event-specific info is included in a "morph" record.
        try:
            morph_data = activity_data["morph"]
            morph_object = morph_data["object"]  # the object type of morph_data
        except (KeyError, TypeError):
            reject_reason = None
            description = None
            click_url = None
        else:
            # It seems like email_data["status"] should map to a reject_reason, but in
            # reality status is most often just (the undocumented) "rejected" and the
            # morph_object has more accurate info.
            reject_reason = self.morph_reject_reasons.get(morph_object)
            description = morph_data.get("readable_reason") or morph_data.get("reason")
            click_url = morph_data.get("url")  # object="click"
            # user_ip = morph_data.get("ip")  # object="click" or "open"

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=event_id,
            recipient=recipient,
            reject_reason=reject_reason,
            description=description,
            tags=tags,
            click_url=click_url,
            esp_event=esp_event,
        )


class MailerSendInboundWebhookView(MailerSendBaseWebhookView):
    """Handler for MailerSend inbound webhook"""

    signal = inbound

    # (Declaring class attr allows override by kwargs in View.as_view.)
    inbound_secret = None

    def __init__(self, **kwargs):
        super().__init__(_secret_name="inbound_secret", **kwargs)

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        event_type = esp_event.get("type")
        if event_type != "inbound.message":
            raise AnymailConfigurationError(
                f"You seem to have set MailerSend's *{event_type}* webhook "
                "to Anymail's MailerSend *inbound* webhook URL. "
            )
        return [self.esp_to_anymail_event(esp_event)]

    def esp_to_anymail_event(self, esp_event):
        message_data = esp_event.get("data")
        event_id = message_data.get("id")

        try:
            timestamp = parse_datetime(message_data["created_at"])
        except (KeyError, TypeError):
            timestamp = None

        message = AnymailInboundMessage.parse_raw_mime(message_data.get("raw"))

        try:
            message.envelope_sender = message_data["sender"]["email"]
            # (also available as X-Envelope-From header)
        except KeyError:
            pass

        try:
            # There can be multiple rcptTo if the same message is sent
            # to multiple inbound recipients. Just use the first.
            envelope_recipients = [
                recipient["email"] for recipient in message_data["recipients"]["rcptTo"]
            ]
            message.envelope_recipient = envelope_recipients[0]
        except (KeyError, IndexError):
            pass

        # MailerSend doesn't seem to provide any spam annotations.
        # SPF seems to be verified, but format is undocumented:
        #     "spf_check": {"code": "+", "value": None}
        # DKIM doesn't appear to be verified yet:
        #     "dkim_check": False,

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timestamp,
            event_id=event_id,
            esp_event=esp_event,
            message=message,
        )
