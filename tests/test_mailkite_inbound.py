import hashlib
import hmac
import json
from base64 import b64encode
from datetime import datetime, timezone
from unittest.mock import ANY, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings, tag

from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailkite import MailKiteInboundWebhookView

from .utils import sample_image_content
from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase

TEST_WEBHOOK_SECRET = "TEST_WEBHOOK_SECRET"


def mailkite_signature_header(data, secret, timestamp_ms=None):
    """Generate a MailKite x-mailkite-signature header value for data"""
    if timestamp_ms is None:
        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    signature = hmac.new(
        key=secret.encode("ascii"),
        msg=b"%d." % timestamp_ms + data,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return "t=%d,v1=%s" % (timestamp_ms, signature)


class MailKiteWebhookTestCase(WebhookTestCase):
    def client_post_signed(
        self, url, json_data, secret=TEST_WEBHOOK_SECRET, timestamp_ms=None
    ):
        """Return self.client.post(url, serialized json_data) signed with secret"""
        data = json.dumps(json_data).encode("utf-8")
        return self.client.post(
            url,
            content_type="application/json",
            data=data,
            headers={
                "X-MailKite-Signature": mailkite_signature_header(
                    data, secret, timestamp_ms
                )
            },
        )


def sample_inbound_event(**overrides):
    """A representative MailKite email.received webhook payload"""
    event = {
        "id": "msg_2Hk9QpVn4tLd",
        "type": "email.received",
        "from": {"address": "envelope-from@example.org", "name": "Sender Name"},
        "to": [{"address": "test@inbound.example.com", "name": "Recipient"}],
        "subject": "Test subject",
        "text": "Test body plain",
        "html": "<div>Test body html</div>",
        "threadId": "<origin@example.org>",
        "receivedAt": 1785196800000,
        "receivedAtIso": "2026-07-28T00:00:00.000Z",
        "auth": {"spf": "pass", "dkim": "pass", "dmarc": "pass", "spam": "ham"},
        "attachments": [],
    }
    event.update(overrides)
    return event


@tag("mailkite")
@override_settings(ANYMAIL_MAILKITE_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET)
class MailKiteInboundSecurityTestCase(
    MailKiteWebhookTestCase, WebhookBasicAuthTestCase
):
    should_warn_if_no_auth = False  # because we check webhook signature

    def call_webhook(self):
        return self.client_post_signed(
            "/anymail/mailkite/inbound/",
            sample_inbound_event(),
            secret=TEST_WEBHOOK_SECRET,
        )

    # Additional tests are in WebhookBasicAuthTestCase

    def test_verifies_correct_signature(self):
        response = self.client_post_signed(
            "/anymail/mailkite/inbound/",
            sample_inbound_event(),
            secret=TEST_WEBHOOK_SECRET,
        )
        self.assertEqual(response.status_code, 200)

    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/mailkite/inbound/",
            content_type="application/json",
            data=json.dumps(sample_inbound_event()),
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_bad_signature(self):
        # This also verifies that the error log references the correct setting to check.
        with self.assertLogs() as logs:
            response = self.client_post_signed(
                "/anymail/mailkite/inbound/",
                sample_inbound_event(),
                secret="wrong webhook secret",
            )
        # SuspiciousOperation causes 400 response (even in test client):
        self.assertEqual(response.status_code, 400)
        self.assertIn("check Anymail MAILKITE_WEBHOOK_SECRET", logs.output[0])

    def test_verifies_expired_signature(self):
        ten_minutes_ago_ms = (
            int(datetime.now(timezone.utc).timestamp() * 1000) - 10 * 60 * 1000
        )
        response = self.client_post_signed(
            "/anymail/mailkite/inbound/",
            sample_inbound_event(),
            timestamp_ms=ten_minutes_ago_ms,
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_malformed_signature(self):
        response = self.client.post(
            "/anymail/mailkite/inbound/",
            content_type="application/json",
            data=json.dumps(sample_inbound_event()),
            headers={"X-MailKite-Signature": "not-a-signature"},
        )
        self.assertEqual(response.status_code, 400)


@tag("mailkite")
class MailKiteInboundSettingsTestCase(MailKiteWebhookTestCase):
    def test_requires_webhook_secret(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "MAILKITE_WEBHOOK_SECRET"):
            self.client_post_signed(
                "/anymail/mailkite/inbound/", sample_inbound_event()
            )


@tag("mailkite")
@override_settings(ANYMAIL_MAILKITE_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET)
class MailKiteInboundTestCase(MailKiteWebhookTestCase):
    def test_inbound_basics(self):
        response = self.client_post_signed(
            "/anymail/mailkite/inbound/", sample_inbound_event()
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailKiteInboundWebhookView,
            event=ANY,
            esp_name="MailKite",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(event.event_id, "msg_2Hk9QpVn4tLd")
        self.assertIsInstance(event.esp_event, dict)
        self.assertEqual(event.esp_event["type"], "email.received")

        message = event.message
        self.assertIsInstance(message, AnymailInboundMessage)
        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "test@inbound.example.com")
        self.assertEqual(
            str(message.from_email), "Sender Name <envelope-from@example.org>"
        )
        self.assertEqual(len(message.to), 1)
        self.assertEqual(str(message.to[0]), "Recipient <test@inbound.example.com>")
        self.assertEqual(message.subject, "Test subject")
        self.assertEqual(message.text, "Test body plain")
        self.assertEqual(message.html, "<div>Test body html</div>")
        self.assertIs(message.spam_detected, False)

    def test_spam_detected(self):
        event_data = sample_inbound_event(
            auth={"spf": "fail", "dkim": None, "dmarc": "fail", "spam": "spam"}
        )
        self.client_post_signed("/anymail/mailkite/inbound/", event_data)
        kwargs = self.get_kwargs(self.inbound_handler)
        self.assertIs(kwargs["event"].message.spam_detected, True)

    def test_unknown_spam_verdict(self):
        # An unrecognized (or missing) verdict must read as "unknown", not "ham"
        event_data = sample_inbound_event(
            auth={"spf": None, "dkim": None, "dmarc": None, "spam": None}
        )
        self.client_post_signed("/anymail/mailkite/inbound/", event_data)
        kwargs = self.get_kwargs(self.inbound_handler)
        self.assertIsNone(kwargs["event"].message.spam_detected)

    def test_no_display_names(self):
        # from.name/to[].name are omitted when the message carried none
        event_data = sample_inbound_event(
            **{
                "from": {"address": "sender@example.org"},
                "to": [{"address": "test@inbound.example.com"}],
                "subject": None,
                "text": None,
                "html": None,
            }
        )
        self.client_post_signed("/anymail/mailkite/inbound/", event_data)
        kwargs = self.get_kwargs(self.inbound_handler)
        message = kwargs["event"].message
        self.assertEqual(str(message.from_email), "sender@example.org")
        self.assertEqual(str(message.to[0]), "test@inbound.example.com")
        self.assertIsNone(message.subject)
        self.assertIsNone(message.text)
        self.assertIsNone(message.html)

    def test_attachment_inline_content(self):
        # Zero-retention/encrypted domains inline the bytes as base64 `content`
        image_content = sample_image_content()
        event_data = sample_inbound_event(
            attachments=[
                {
                    "filename": "sample_image.png",
                    "contentType": "image/png",
                    "size": len(image_content),
                    "content": b64encode(image_content).decode("ascii"),
                }
            ]
        )
        self.client_post_signed("/anymail/mailkite/inbound/", event_data)
        kwargs = self.get_kwargs(self.inbound_handler)
        attachments = kwargs["event"].message.attachments
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "sample_image.png")
        self.assertEqual(attachments[0].get_content_type(), "image/png")
        self.assertEqual(attachments[0].as_uploaded_file().read(), image_content)

    def test_attachment_url(self):
        # The normal case: a signed, credential-free GET link, fetched on receipt
        attachment_url = "https://api.mailkite.dev/att/2Hk9QpVn4tLd/0?exp=1&sig=abc"
        event_data = sample_inbound_event(
            attachments=[
                {
                    "id": "msg_2Hk9QpVn4tLd:0",
                    "filename": "report.pdf",
                    "contentType": "application/pdf",
                    "size": 15,
                    "url": attachment_url,
                }
            ]
        )
        with patch("anymail.webhooks.mailkite.requests.get") as mock_get:
            mock_get.return_value.content = b"%PDF-1.4 sample"
            mock_get.return_value.raise_for_status.return_value = None
            self.client_post_signed("/anymail/mailkite/inbound/", event_data)
        mock_get.assert_called_once_with(attachment_url, timeout=30)
        kwargs = self.get_kwargs(self.inbound_handler)
        attachments = kwargs["event"].message.attachments
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "report.pdf")
        self.assertEqual(attachments[0].get_content_type(), "application/pdf")
        self.assertEqual(attachments[0].as_uploaded_file().read(), b"%PDF-1.4 sample")

    def test_ignores_unknown_event_types(self):
        # Non-email.* payloads must not error or fire signals
        response = self.client_post_signed(
            "/anymail/mailkite/inbound/",
            {"id": "evt_1", "type": "ping"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.inbound_handler.call_count, 0)

    def test_misconfigured_tracking(self):
        # A tracking event arriving on the inbound URL means the webhook URLs
        # are swapped -- surface a configuration hint rather than dropping it.
        from anymail.exceptions import AnymailConfigurationError

        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set MailKite's *tracking-event* webhook"
            " to Anymail's MailKite *inbound* webhook URL.",
        ):
            self.client_post_signed(
                "/anymail/mailkite/inbound/", {"type": "email.bounced"}
            )
