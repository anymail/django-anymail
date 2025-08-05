from __future__ import annotations

import base64
import binascii
import json
import warnings
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as default_policy

from ..exceptions import (
    AnymailImproperlyInstalled,
    AnymailNotSupportedWarning,
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
from ..utils import get_anymail_setting
from .base import AnymailBaseWebhookView

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, types
except ImportError:
    # This module gets imported by anymail.urls, so don't complain about cryptography
    # missing unless one of the SendGrid webhook views is actually used and needs it
    error = _LazyError(
        AnymailImproperlyInstalled(
            missing_package="cryptography", install_extra="sendgrid"
        )
    )
    serialization = error
    hashes = error
    default_backend = error
    ec = error
    InvalidSignature = Exception


class SendGridBaseWebhookView(AnymailBaseWebhookView):
    # Derived classes must set to name of webhook verification key setting
    # (lowercase, don't include esp_name).
    key_setting_name: str

    # Loaded from key_setting_name; None -> signature verification is skipped
    webhook_verification_key: "types.PublicKeyTypes | None" = None

    @classmethod
    def as_view(cls, **initkwargs):
        if not hasattr(cls, cls.key_setting_name):
            # The attribute must exist on the class before View.as_view
            # will allow overrides via kwarg
            setattr(cls, cls.key_setting_name, None)
        return super().as_view(**initkwargs)

    def __init__(self, **kwargs):
        verification_key: str | None = get_anymail_setting(
            self.key_setting_name,
            esp_name=self.esp_name,
            default=None,
            kwargs=kwargs,
            allow_bare=True,
        )
        if verification_key:
            self.webhook_verification_key = serialization.load_pem_public_key(
                (
                    "-----BEGIN PUBLIC KEY-----\n"
                    + verification_key
                    + "\n-----END PUBLIC KEY-----"
                ).encode("utf-8"),
                backend=default_backend(),
            )
        if self.webhook_verification_key:
            # If the webhook key is successfully configured, then we don't need to warn about
            # missing basic auth
            self.warn_if_no_basic_auth = False
        else:
            # Purely defensive programming; should already be set to True
            self.warn_if_no_basic_auth = True

        super().__init__(**kwargs)
        warnings.warn(
            "django-anymail has dropped official support for SendGrid."
            " See https://github.com/anymail/django-anymail/issues/432.",
            AnymailNotSupportedWarning,
        )

    def validate_request(self, request):
        if self.webhook_verification_key:
            try:
                signature = request.headers["X-Twilio-Email-Event-Webhook-Signature"]
            except KeyError:
                raise AnymailWebhookValidationFailure(
                    "X-Twilio-Email-Event-Webhook-Signature header missing from webhook"
                )
            try:
                timestamp = request.headers["X-Twilio-Email-Event-Webhook-Timestamp"]
            except KeyError:
                raise AnymailWebhookValidationFailure(
                    "X-Twilio-Email-Event-Webhook-Timestamp header missing from webhook"
                )

            timestamped_payload = timestamp.encode("utf-8") + request.body

            try:
                decoded_signature = base64.b64decode(signature)
                self.webhook_verification_key.verify(
                    decoded_signature,
                    timestamped_payload,
                    ec.ECDSA(hashes.SHA256()),
                )
            # We intentionally respond the same to both of these issues, see below
            # binascii.Error may come from attempting to base64-decode the signature
            # InvalidSignature will come from self.webhook_key.verify(...)
            except (binascii.Error, InvalidSignature):
                # We intentionally don't give out too much information here, because that would
                # make it easier used to characterize the issue and workaround the signature
                # verification
                setting_name = f"{self.esp_name}_{self.key_setting_name}".upper()
                raise AnymailWebhookValidationFailure(
                    "SendGrid webhook called with incorrect signature"
                    f" (check Anymail {setting_name} setting)"
                )


class SendGridTrackingWebhookView(SendGridBaseWebhookView):
    """Handler for SendGrid delivery and engagement tracking webhooks"""

    esp_name = "SendGrid"
    key_setting_name = "tracking_webhook_verification_key"
    signal = tracking

    def parse_events(self, request):
        esp_events = json.loads(request.body.decode("utf-8"))
        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    event_types = {
        # Map SendGrid event: Anymail normalized type
        "bounce": EventType.BOUNCED,
        "deferred": EventType.DEFERRED,
        "delivered": EventType.DELIVERED,
        "dropped": EventType.REJECTED,
        "processed": EventType.QUEUED,
        "click": EventType.CLICKED,
        "open": EventType.OPENED,
        "spamreport": EventType.COMPLAINED,
        "unsubscribe": EventType.UNSUBSCRIBED,
        "group_unsubscribe": EventType.UNSUBSCRIBED,
        "group_resubscribe": EventType.SUBSCRIBED,
    }

    reject_reasons = {
        # Map SendGrid reason/type strings (lowercased)
        # to Anymail normalized reject_reason
        "invalid": RejectReason.INVALID,
        "unsubscribed address": RejectReason.UNSUBSCRIBED,
        "bounce": RejectReason.BOUNCED,
        "bounced address": RejectReason.BOUNCED,
        "blocked": RejectReason.BLOCKED,
        "expired": RejectReason.TIMED_OUT,
    }

    def esp_to_anymail_event(self, esp_event):
        event_type = self.event_types.get(esp_event["event"], EventType.UNKNOWN)
        try:
            timestamp = datetime.fromtimestamp(esp_event["timestamp"], tz=timezone.utc)
        except (KeyError, ValueError):
            timestamp = None

        if esp_event["event"] == "dropped":
            # message dropped at ESP before even getting to MTA:
            mta_response = None
            # cause could be in "type" or "reason":
            reason = esp_event.get("type", esp_event.get("reason", ""))
            reject_reason = self.reject_reasons.get(reason.lower(), RejectReason.OTHER)
        else:
            # MTA response is in "response" for delivered; "reason" for bounce
            mta_response = esp_event.get("response", esp_event.get("reason", None))
            reject_reason = None

        # SendGrid merges metadata ('unique_args') with the event.
        # We can (sort of) split metadata back out by filtering known
        # SendGrid event params, though this can miss metadata keys
        # that duplicate SendGrid params, and can accidentally include
        # non-metadata keys if SendGrid modifies their event records.
        metadata_keys = set(esp_event.keys()) - self.sendgrid_event_keys
        if len(metadata_keys) > 0:
            metadata = {key: esp_event[key] for key in metadata_keys}
        else:
            metadata = {}

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            # (smtp-id for backwards compatibility)
            message_id=esp_event.get("anymail_id", esp_event.get("smtp-id")),
            event_id=esp_event.get("sg_event_id", None),
            recipient=esp_event.get("email", None),
            reject_reason=reject_reason,
            mta_response=mta_response,
            tags=esp_event.get("category", []),
            metadata=metadata,
            click_url=esp_event.get("url", None),
            user_agent=esp_event.get("useragent", None),
            esp_event=esp_event,
        )

    # Known keys in SendGrid events (used to recover metadata above)
    sendgrid_event_keys = {
        "anymail_id",
        "asm_group_id",
        "attempt",  # MTA deferred count
        "category",
        "cert_err",
        "email",
        "event",
        "ip",
        "marketing_campaign_id",
        "marketing_campaign_name",
        "newsletter",  # ???
        "nlvx_campaign_id",
        "nlvx_campaign_split_id",
        "nlvx_user_id",
        "pool",
        "post_type",
        "reason",  # MTA bounce/drop reason; SendGrid suppression reason
        "response",  # MTA deferred/delivered message
        "send_at",
        "sg_event_id",
        "sg_message_id",
        "smtp-id",
        "status",  # SMTP status code
        "timestamp",
        "tls",
        "type",  # suppression reject reason ("bounce", "blocked", "expired")
        "url",  # click tracking
        "url_offset",  # click tracking
        "useragent",  # click/open tracking
    }


class SendGridInboundWebhookView(AnymailBaseWebhookView):
    """Handler for SendGrid inbound webhook"""

    esp_name = "SendGrid"
    signal = inbound

    # The inbound webhook does not currently implement signature validation
    # because we don't have access to a SendGrid account that could test it.
    # It *should* only require changing to SendGridBaseWebhookView and
    # providing the setting name:
    #
    #     class SendGridInboundWebhookView(SendGridBaseWebhookView):
    #         key_setting_name = "inbound_webhook_verification_key"
    #
    # and then setting SENDGRID_INBOUND_WEBHOOK_VERIFICATION_KEY.

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        warnings.warn(
            "django-anymail has dropped official support for SendGrid."
            " See https://github.com/anymail/django-anymail/issues/432.",
            AnymailNotSupportedWarning,
        )

    def parse_events(self, request):
        return [self.esp_to_anymail_event(request)]

    def esp_to_anymail_event(self, request):
        # Inbound uses the entire Django request as esp_event, because we need
        # POST and FILES. Note that request.POST is case-sensitive (unlike
        # email.message.Message headers).
        esp_event = request
        # Must access body before any POST fields, or it won't be available if we need
        # it later (see text_charset and html_charset handling below).
        _ensure_body_is_available_later = request.body  # noqa: F841
        if "headers" in request.POST:
            # Default (not "Send Raw") inbound fields
            message = self.message_from_sendgrid_parsed(esp_event)
        elif "email" in request.POST:
            # "Send Raw" full MIME
            message = AnymailInboundMessage.parse_raw_mime(request.POST["email"])
        else:
            raise KeyError(
                "Invalid SendGrid inbound event data"
                " (missing both 'headers' and 'email' fields)"
            )

        try:
            envelope = json.loads(request.POST["envelope"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            message.envelope_sender = envelope["from"]
            message.envelope_recipient = envelope["to"][0]

        # no simple boolean spam; would need to parse the spam_report
        message.spam_detected = None
        try:
            message.spam_score = float(request.POST["spam_score"])
        except (KeyError, TypeError, ValueError):
            pass

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            # SendGrid doesn't provide an inbound event timestamp:
            timestamp=None,
            # SendGrid doesn't provide an idempotent inbound message event id:
            event_id=None,
            esp_event=esp_event,
            message=message,
        )

    def message_from_sendgrid_parsed(self, request):
        """Construct a Message from SendGrid's "default" (non-raw) fields"""

        try:
            charsets = json.loads(request.POST["charsets"])
        except (KeyError, ValueError):
            charsets = {}

        try:
            attachment_info = json.loads(request.POST["attachment-info"])
        except (KeyError, ValueError):
            attachments = None
        else:
            # Load attachments from posted files
            attachments = []
            for attachment_id in sorted(attachment_info.keys()):
                try:
                    file = request.FILES[attachment_id]
                except KeyError:
                    # Django's multipart/form-data handling drops FILES with certain
                    # filenames (for security) or with empty filenames (Django ticket
                    # 15879). (To avoid this problem, enable SendGrid's "raw, full MIME"
                    # inbound option.)
                    pass
                else:
                    # (This deliberately ignores
                    # attachment_info[attachment_id]["filename"],
                    # which has not passed through Django's filename sanitization.)
                    content_id = attachment_info[attachment_id].get("content-id")
                    attachment = (
                        AnymailInboundMessage.construct_attachment_from_uploaded_file(
                            file, content_id=content_id
                        )
                    )
                    attachments.append(attachment)

        default_charset = request.POST.encoding.lower()  # (probably utf-8)
        text = request.POST.get("text")
        text_charset = charsets.get("text", default_charset).lower()
        html = request.POST.get("html")
        html_charset = charsets.get("html", default_charset).lower()
        if (text and text_charset != default_charset) or (
            html and html_charset != default_charset
        ):
            # Django has parsed text and/or html fields using the wrong charset.
            # We need to re-parse the raw form data and decode each field separately,
            # using the indicated charsets. The email package parses multipart/form-data
            # retaining bytes content. (In theory, we could instead just change
            # request.encoding and access the POST fields again, per Django docs,
            # but that seems to be have bugs around the cached request._files.)
            raw_data = b"".join(
                [
                    b"Content-Type: ",
                    request.META["CONTENT_TYPE"].encode("ascii"),
                    b"\r\n\r\n",
                    request.body,
                ]
            )
            parsed_parts = (
                BytesParser(policy=default_policy).parsebytes(raw_data).get_payload()
            )
            for part in parsed_parts:
                name = part.get_param("name", header="content-disposition")
                if name == "text":
                    text = part.get_payload(decode=True).decode(text_charset)
                elif name == "html":
                    html = part.get_payload(decode=True).decode(html_charset)
                # (subject, from, to, etc. are parsed from raw headers field,
                # so no need to worry about their separate POST field charsets)

        return AnymailInboundMessage.construct(
            # POST["headers"] includes From, To, Cc, Subject, etc.
            raw_headers=request.POST.get("headers", ""),
            text=text,
            html=html,
            attachments=attachments,
        )
