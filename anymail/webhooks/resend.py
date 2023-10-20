import json
from datetime import datetime

from ..exceptions import (
    AnymailImproperlyInstalled,
    AnymailInvalidAddress,
    AnymailWebhookValidationFailure,
    _LazyError,
)
from ..signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from ..utils import get_anymail_setting, parse_single_address
from .base import AnymailBaseWebhookView, AnymailCoreWebhookView

try:
    # Valid webhook signatures with svix library if available
    from svix.webhooks import Webhook as SvixWebhook, WebhookVerificationError
except ImportError:
    # Otherwise, validating with basic auth is sufficient
    # (unless settings specify signature validation, which will then raise this error)
    SvixWebhook = _LazyError(
        AnymailImproperlyInstalled(missing_package="svix", install_extra="resend")
    )
    WebhookVerificationError = object()


class SvixWebhookValidationMixin(AnymailCoreWebhookView):
    """Mixin to validate Svix webhook signatures"""

    # Consuming classes can override (e.g., to use different secrets
    # for inbound and tracking webhooks).
    _secret_setting_name = "signing_secret"

    @classmethod
    def as_view(cls, **initkwargs):
        if not hasattr(cls, cls._secret_setting_name):
            # The attribute must exist on the class before View.as_view
            # will allow overrides via kwarg
            setattr(cls, cls._secret_setting_name, None)
        return super().as_view(**initkwargs)

    def __init__(self, **kwargs):
        self.signing_secret = get_anymail_setting(
            self._secret_setting_name,
            esp_name=self.esp_name,
            default=None,
            kwargs=kwargs,
        )
        if self.signing_secret is None:
            self._svix_webhook = None
            self.warn_if_no_basic_auth = True
        else:
            # This will raise an import error if svix isn't installed
            self._svix_webhook = SvixWebhook(self.signing_secret)
            # Basic auth is not required if validating signature
            self.warn_if_no_basic_auth = False
        super().__init__(**kwargs)

    def validate_request(self, request):
        if self._svix_webhook:
            # https://docs.svix.com/receiving/verifying-payloads/how
            try:
                # Note: if signature is valid, Svix also tries to parse
                # the json body, so this could raise other errors...
                self._svix_webhook.verify(request.body, request.headers)
            except WebhookVerificationError as error:
                setting_name = f"{self.esp_name}_{self._secret_setting_name}".upper()
                raise AnymailWebhookValidationFailure(
                    f"{self.esp_name} webhook called with incorrect signature"
                    f" (check Anymail {setting_name} setting)"
                ) from error


class ResendTrackingWebhookView(SvixWebhookValidationMixin, AnymailBaseWebhookView):
    """Handler for Resend.com status tracking webhooks"""

    esp_name = "Resend"
    signal = tracking

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        return [self.esp_to_anymail_event(esp_event, request)]

    # https://resend.com/docs/dashboard/webhooks/event-types
    event_types = {
        # Map Resend type: Anymail normalized type
        "email.sent": EventType.SENT,
        "email.delivered": EventType.DELIVERED,
        "email.delivery_delayed": EventType.DEFERRED,
        "email.complained": EventType.COMPLAINED,
        "email.bounced": EventType.BOUNCED,
        "email.opened": EventType.OPENED,
        "email.clicked": EventType.CLICKED,
    }

    def esp_to_anymail_event(self, esp_event, request):
        event_type = self.event_types.get(esp_event["type"], EventType.UNKNOWN)

        # event_id: HTTP header `svix-id` is unique for a particular event
        # (including across reposts due to errors)
        try:
            event_id = request.headers["svix-id"]
        except KeyError:
            event_id = None

        # timestamp: Payload created_at is unique for a particular event.
        # (Payload data.created_at is when the message was created, not the event.
        # HTTP header `svix-timestamp` changes for each repost of the same event.)
        try:
            timestamp = datetime.fromisoformat(
                # Must convert "Z" to timezone offset for Python 3.10 and earlier.
                esp_event["created_at"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError):
            timestamp = None

        try:
            message_id = esp_event["data"]["email_id"]
        except (KeyError, TypeError):
            message_id = None

        # Resend doesn't provide bounce reasons or SMTP responses,
        # but it's possible to distinguish some cases by examining
        # the human-readable message text:
        try:
            bounce_message = esp_event["data"]["bounce"]["message"]
        except (KeyError, ValueError):
            bounce_message = None
            reject_reason = None
        else:
            if "suppressed sending" in bounce_message:
                # "Resend has suppressed sending to this address ..."
                reject_reason = RejectReason.BLOCKED
            elif "bounce message" in bounce_message:
                # "The recipient's email provider sent a hard bounce message, ..."
                # "The recipient's email provider sent a general bounce message. ..."
                # "The recipient's email provider sent a bounce message because
                #    the recipient's inbox was full. ..."
                reject_reason = RejectReason.BOUNCED
            else:
                reject_reason = RejectReason.OTHER  # unknown

        # Recover tags and metadata from custom headers
        metadata = {}
        tags = []
        try:
            headers = esp_event["data"]["headers"]
        except KeyError:
            pass
        else:
            for header in headers:
                name = header["name"].lower()
                if name == "x-tags":
                    try:
                        tags = json.loads(header["value"])
                    except (ValueError, TypeError):
                        pass
                elif name == "x-metadata":
                    try:
                        metadata = json.loads(header["value"])
                    except (ValueError, TypeError):
                        pass

        # For multi-recipient emails (including cc and bcc), Resend generates events
        # for each recipient, but no indication of which recipient an event applies to.
        # Just report the first `to` recipient.
        try:
            first_to = esp_event["data"]["to"][0]
            recipient = parse_single_address(first_to).addr_spec
        except (KeyError, IndexError, TypeError, AnymailInvalidAddress):
            recipient = None

        try:
            click_data = esp_event["data"]["click"]
        except (KeyError, TypeError):
            click_url = None
            user_agent = None
        else:
            click_url = click_data.get("link")
            user_agent = click_data.get("userAgent")

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=event_id,
            recipient=recipient,
            reject_reason=reject_reason,
            description=bounce_message,
            mta_response=None,
            tags=tags,
            metadata=metadata,
            click_url=click_url,
            user_agent=user_agent,
            esp_event=esp_event,
        )
