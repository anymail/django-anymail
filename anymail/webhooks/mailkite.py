import hashlib
import hmac
import json
from datetime import datetime, timezone
from email.utils import formataddr

import requests

from ..exceptions import AnymailWebhookValidationFailure
from ..inbound import AnymailInboundMessage
from ..signals import AnymailInboundEvent, EventType, inbound
from ..utils import get_anymail_setting
from .base import AnymailBaseWebhookView

# Reject signatures whose timestamp is too far from the current time.
# (Matches the default tolerance in MailKite's own SDK webhook verifiers.
# MailKite re-signs every automatic retry and manual replay at delivery
# time, so a legitimate delivery is never outside this window.)
SIGNATURE_TOLERANCE_MS = 5 * 60 * 1000


class MailKiteInboundWebhookView(AnymailBaseWebhookView):
    """Handler for MailKite inbound webhook (``email.received`` events)"""

    esp_name = "MailKite"
    signal = inbound
    warn_if_no_basic_auth = False  # because we validate against the signature

    # (Declaring class attr allows override by kwargs in View.as_view.)
    webhook_secret = None

    def __init__(self, **kwargs):
        webhook_secret = get_anymail_setting(
            "webhook_secret", esp_name=self.esp_name, kwargs=kwargs
        )
        # hmac.new requires bytes key:
        self.webhook_secret = webhook_secret.encode("ascii")
        super().__init__(**kwargs)

    def validate_request(self, request):
        # MailKite signs each delivery with
        # ``x-mailkite-signature: t=<ms-epoch>,v1=<hex>``
        # where v1 = HMAC-SHA256(webhook_secret, "{t}.{raw_body}").
        try:
            signature_header = request.headers["X-MailKite-Signature"]
        except KeyError:
            raise AnymailWebhookValidationFailure(
                "MailKite webhook called without signature"
            ) from None

        parts = {}
        for segment in signature_header.split(","):
            name, _, value = segment.partition("=")
            parts[name.strip()] = value.strip()
        timestamp = parts.get("t", "")
        signature = parts.get("v1", "")
        if not timestamp.isdigit() or not signature:
            raise AnymailWebhookValidationFailure(
                "MailKite webhook called with malformed signature"
            )

        expected_signature = hmac.new(
            key=self.webhook_secret,
            msg=timestamp.encode("ascii") + b"." + request.body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise AnymailWebhookValidationFailure(
                "MailKite webhook called with incorrect signature"
                " (check Anymail MAILKITE_WEBHOOK_SECRET setting)"
            )

        now_ms = datetime.now(timezone.utc).timestamp() * 1000.0
        if abs(now_ms - int(timestamp)) > SIGNATURE_TOLERANCE_MS:
            raise AnymailWebhookValidationFailure(
                "MailKite webhook called with expired signature"
            )

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        if esp_event.get("type") != "email.received":
            # Ignore any future event types MailKite may add to the same
            # webhook, rather than erroring on every delivery of them.
            return []
        return [self.esp_to_anymail_event(esp_event)]

    def esp_to_anymail_event(self, esp_event):
        # Payload documented in MailKite's email.received event schema:
        # id, from {address, name?}, to [{address, name?}], subject, text,
        # html, threadId, receivedAt (ms), auth {spf, dkim, dmarc, spam},
        # attachments [{filename, contentType, size, url | content}].
        message = AnymailInboundMessage.construct(
            from_email=self._formataddr(esp_event.get("from")),
            to=", ".join(
                self._formataddr(recipient) for recipient in esp_event.get("to", [])
            ),
            subject=esp_event.get("subject"),
            text=esp_event.get("text"),
            html=esp_event.get("html"),
            attachments=[
                self._construct_attachment(attachment)
                for attachment in esp_event.get("attachments", [])
            ],
        )
        message.envelope_sender = esp_event.get("from", {}).get("address")
        recipients = esp_event.get("to", [])
        message.envelope_recipient = recipients[0]["address"] if recipients else None
        # auth.spam passes the receiving edge's verdict through: "ham"/"spam"
        # typically; edges running rspamd may report its action name instead.
        spam = (esp_event.get("auth") or {}).get("spam")
        if spam in ("ham", "no action"):
            message.spam_detected = False
        elif spam in ("spam", "reject"):
            message.spam_detected = True

        try:
            timestamp = datetime.fromtimestamp(
                esp_event["receivedAt"] / 1000.0, tz=timezone.utc
            )
        except (KeyError, TypeError):
            timestamp = None

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timestamp,
            event_id=esp_event.get("id"),
            esp_event=esp_event,
            message=message,
        )

    @staticmethod
    def _formataddr(address):
        """{address, name?} dict -> RFC 5322 name-addr string"""
        if not address:
            return None
        return formataddr((address.get("name"), address["address"]))

    def _construct_attachment(self, attachment):
        # Each attachment carries exactly one of `content` (base64 bytes,
        # inlined on zero-retention/encrypted domains) or `url` (a signed,
        # credential-free GET link, valid 7 days -- the normal case).
        content = attachment.get("content")
        if content is None:
            response = requests.get(attachment["url"], timeout=30)
            response.raise_for_status()
            content = response.content
            base64_encoded = False
        else:
            base64_encoded = True
        return AnymailInboundMessage.construct_attachment(
            content_type=attachment.get("contentType") or "application/octet-stream",
            content=content,
            filename=attachment.get("filename"),
            base64=base64_encoded,
        )
