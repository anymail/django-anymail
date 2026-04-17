import json
from datetime import datetime
from urllib.parse import urljoin

import requests

from ..exceptions import (
    AnymailConfigurationError,
    AnymailImproperlyInstalled,
    AnymailInvalidAddress,
    AnymailWebhookValidationFailure,
    _LazyError,
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
        secret = get_anymail_setting(
            self._secret_setting_name,
            esp_name=self.esp_name,
            default=None,
            kwargs=kwargs,
        )
        setattr(self, self._secret_setting_name, secret)
        if secret is None:
            self._svix_webhook = None
            self.warn_if_no_basic_auth = True
        else:
            # This will raise an import error if svix isn't installed
            self._svix_webhook = SvixWebhook(secret)
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


class ResendInboundWebhookView(SvixWebhookValidationMixin, AnymailBaseWebhookView):
    """Handler for Resend.com inbound email webhooks"""

    # https://resend.com/docs/webhooks/emails/received

    esp_name = "Resend"
    signal = inbound
    _secret_setting_name = "inbound_secret"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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
            default="https://api.resend.com/",
        )
        if not self.api_url.endswith("/"):
            self.api_url += "/"

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        if esp_event.get("type") != "email.received":
            raise AnymailConfigurationError(
                f"You seem to have set Resend's"
                f" *{esp_event.get('type', 'tracking')}* webhook"
                f" to Anymail's Resend *inbound* webhook URL."
            )
        return [self.esp_to_anymail_event(esp_event, request)]

    def esp_to_anymail_event(self, esp_event, request):
        try:
            event_id = request.headers["svix-id"]
        except KeyError:
            event_id = None

        try:
            timestamp = datetime.fromisoformat(
                esp_event["created_at"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError):
            timestamp = None

        email_id = esp_event.get("data", {}).get("email_id")
        if email_id:
            message = self._fetch_inbound_email(email_id)
        else:
            message = None

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timestamp,
            event_id=event_id,
            esp_event=esp_event,
            message=message,
        )

    def _fetch_inbound_email(self, email_id):
        """Fetch full email content from Resend API and return AnymailInboundMessage."""
        url = urljoin(self.api_url, f"emails/receiving/{email_id}")
        response = requests.get(
            url, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        response.raise_for_status()
        data = response.json()

        # Prefer raw MIME when available (more complete representation)
        raw = data.get("raw") or {}
        raw_url = raw.get("download_url")
        if raw_url:
            raw_response = requests.get(raw_url)
            raw_response.raise_for_status()
            return AnymailInboundMessage.parse_raw_mime_bytes(raw_response.content)

        # Fall back to constructing from parsed fields
        headers = []
        esp_headers = data.get("headers") or {}
        if isinstance(esp_headers, dict):
            for name, value in esp_headers.items():
                if isinstance(value, list):
                    for v in value:
                        headers.append((name, v))
                else:
                    headers.append((name, value))
        elif isinstance(esp_headers, list):
            # Handle list-of-dicts format (e.g., [{"name": ..., "value": ...}])
            headers = [(h["name"], h["value"]) for h in esp_headers]

        attachments = [
            self._fetch_attachment(att) for att in data.get("attachments") or []
        ]

        message = AnymailInboundMessage.construct(
            from_email=data.get("from"),
            to=", ".join(data.get("to") or []) or None,
            cc=", ".join(data.get("cc") or []) or None,
            bcc=", ".join(data.get("bcc") or []) or None,
            subject=data.get("subject"),
            headers=headers,
            text=data.get("text"),
            html=data.get("html"),
            attachments=attachments,
        )

        if data.get("reply_to") and "Reply-To" not in message:
            message["Reply-To"] = ", ".join(data["reply_to"])
        if data.get("message_id") and "Message-ID" not in message:
            message["Message-ID"] = data["message_id"]

        return message

    def _fetch_attachment(self, attachment):
        """Download attachment content and return as AnymailInboundMessage attachment."""
        url = attachment["download_url"]
        response = requests.get(url)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type") or attachment.get(
            "content_type", "application/octet-stream"
        )
        return AnymailInboundMessage.construct_attachment(
            content_type=content_type,
            content=response.content,
            filename=attachment.get("filename"),
            content_id=attachment.get("content_id"),
        )
