import binascii
import json
from base64 import b64decode
from datetime import datetime, timezone


from .base import AnymailBaseWebhookView
from ..exceptions import (
    AnymailInvalidAddress,
    AnymailWebhookValidationFailure,
    AnymailImproperlyInstalled,
    _LazyError,
    AnymailConfigurationError,
)
from ..inbound import AnymailInboundMessage
from ..signals import (
    inbound,
    tracking,
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
)
from ..utils import parse_single_address, get_anymail_setting

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature
except ImportError:
    # This module gets imported by anymail.urls, so don't complain about cryptography missing
    # unless one of the Postal webhook views is actually used and needs it
    error = _LazyError(AnymailImproperlyInstalled(missing_package='cryptography', backend='postal'))
    serialization = error
    hashes = error
    default_backend = error
    padding = error
    InvalidSignature = object


class PostalBaseWebhookView(AnymailBaseWebhookView):
    """Base view class for Postal webhooks"""

    esp_name = "Postal"

    warn_if_no_basic_auth = False

    # These can be set from kwargs in View.as_view, or pulled from settings in init:
    webhook_key = None

    def __init__(self, **kwargs):
        self.webhook_key = get_anymail_setting('webhook_key', esp_name=self.esp_name, kwargs=kwargs, allow_bare=True)

        super().__init__(**kwargs)

    def validate_request(self, request):
        try:
            signature = request.META["HTTP_X_POSTAL_SIGNATURE"]
        except KeyError:
            raise AnymailWebhookValidationFailure("X-Postal-Signature header missing from webhook")

        public_key = serialization.load_pem_public_key(
            ('-----BEGIN PUBLIC KEY-----\n' + self.webhook_key + '\n-----END PUBLIC KEY-----').encode(),
            backend=default_backend()
        )

        try:
            public_key.verify(
                b64decode(signature),
                request.body,
                padding.PKCS1v15(),
                hashes.SHA1()
            )
        except (InvalidSignature, binascii.Error):
            raise AnymailWebhookValidationFailure(
                "Postal webhook called with incorrect signature")


class PostalTrackingWebhookView(PostalBaseWebhookView):
    """Handler for Postal message, engagement, and generation event webhooks"""

    signal = tracking

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))

        if 'rcpt_to' in esp_event:
            raise AnymailConfigurationError(
                "You seem to have set Postal's *inbound* webhook "
                "to Anymail's Postal *tracking* webhook URL.")

        raw_timestamp = esp_event.get("timestamp")
        timestamp = (
            datetime.fromtimestamp(int(raw_timestamp), tz=timezone.utc)
            if raw_timestamp
            else None
        )

        payload = esp_event.get("payload", {})

        status_types = {
            "Sent": EventType.DELIVERED,
            "SoftFail": EventType.DEFERRED,
            "HardFail": EventType.FAILED,
            "Held": EventType.QUEUED,
        }

        if "status" in payload:
            event_type = status_types.get(payload["status"], EventType.UNKNOWN)
        elif "bounce" in payload:
            event_type = EventType.BOUNCED
        elif "url" in payload:
            event_type = EventType.CLICKED
        else:
            event_type = EventType.UNKNOWN

        description = payload.get("details")
        mta_response = payload.get("output")

        # extract message-related fields
        message = payload.get("message") or payload.get("original_message", {})
        message_id = message.get("id")
        tag = message.get("tag")
        recipient = None
        message_to = message.get("to")
        if message_to is not None:
            try:
                recipient = parse_single_address(message_to).addr_spec
            except AnymailInvalidAddress:
                pass

        if message.get("direction") == "incoming":
            # Let's ignore tracking events about an inbound emails.
            # This happens when an inbound email could not be forwarded.
            # The email didn't originate from Anymail, so the user can't do much about it.
            # It is part of normal Postal operation, not a configuration error.
            return []

        # only for MessageLinkClicked
        click_url = payload.get("url")
        user_agent = payload.get("user_agent")

        event = AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            event_id=esp_event.get('uuid'),
            esp_event=esp_event,
            click_url=click_url,
            description=description,
            message_id=message_id,
            metadata=None,
            mta_response=mta_response,
            recipient=recipient,
            reject_reason=RejectReason.BOUNCED if event_type == EventType.BOUNCED else None,
            tags=[tag],
            user_agent=user_agent,
        )

        return [event]


class PostalInboundWebhookView(PostalBaseWebhookView):
    """Handler for Postal inbound relay webhook"""

    signal = inbound

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))

        if 'status' in esp_event:
            raise AnymailConfigurationError(
                "You seem to have set Postal's *tracking* webhook "
                "to Anymail's Postal *inbound* webhook URL.")

        raw_mime = esp_event["message"]
        if esp_event.get("base64") is True:
            raw_mime = b64decode(esp_event["message"]).decode("utf-8")
        message = AnymailInboundMessage.parse_raw_mime(raw_mime)

        message.envelope_sender = esp_event.get('mail_from', None)
        message.envelope_recipient = esp_event.get('rcpt_to', None)

        event = AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=None,
            event_id=esp_event.get("id"),
            esp_event=esp_event,
            message=message,
        )

        return [event]
