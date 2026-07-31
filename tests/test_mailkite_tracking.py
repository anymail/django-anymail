import json
from datetime import datetime, timezone
from unittest.mock import ANY

from django.test import override_settings, tag

from anymail.exceptions import AnymailConfigurationError
from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mailkite import MailKiteTrackingWebhookView

from .test_mailkite_inbound import TEST_WEBHOOK_SECRET, MailKiteWebhookTestCase
from .webhook_cases import WebhookBasicAuthTestCase


def sample_tracking_event(event_type="email.sent", **data_overrides):
    """A representative MailKite tracking-event webhook payload"""
    data = {
        "messageId": "msg_2Hk9QpVn4tLd",
        "providerMessageId": None,
        "from": "from@example.com",
        "to": "recipient@example.com",
        "subject": "Test subject",
    }
    data.update(data_overrides)
    return {
        "id": "evt_5Vp2RqWm8xNc",
        "type": event_type,
        "createdAt": 1785196800000,
        "createdAtIso": "2026-07-28T00:00:00.000Z",
        "data": data,
    }


@tag("mailkite")
@override_settings(ANYMAIL_MAILKITE_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET)
class MailKiteTrackingSecurityTestCase(
    MailKiteWebhookTestCase, WebhookBasicAuthTestCase
):
    should_warn_if_no_auth = False  # because we check webhook signature

    def call_webhook(self):
        return self.client_post_signed(
            "/anymail/mailkite/tracking/",
            sample_tracking_event(),
            secret=TEST_WEBHOOK_SECRET,
        )

    # Additional tests are in WebhookBasicAuthTestCase

    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/mailkite/tracking/",
            content_type="application/json",
            data=json.dumps(sample_tracking_event()),
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_bad_signature(self):
        with self.assertLogs() as logs:
            response = self.client_post_signed(
                "/anymail/mailkite/tracking/",
                sample_tracking_event(),
                secret="wrong webhook secret",
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("check Anymail MAILKITE_WEBHOOK_SECRET", logs.output[0])


@tag("mailkite")
@override_settings(ANYMAIL_MAILKITE_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET)
class MailKiteTrackingTestCase(MailKiteWebhookTestCase):
    def assert_tracking_event(self, payload):
        response = self.client_post_signed("/anymail/mailkite/tracking/", payload)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailKiteTrackingWebhookView,
            event=ANY,
            esp_name="MailKite",
        )
        return kwargs["event"]

    def test_sent_event(self):
        event = self.assert_tracking_event(sample_tracking_event("email.sent"))
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "sent")
        self.assertEqual(
            event.timestamp, datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(event.event_id, "evt_5Vp2RqWm8xNc")
        self.assertEqual(event.message_id, "msg_2Hk9QpVn4tLd")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertIsNone(event.reject_reason)
        self.assertEqual(event.esp_event["type"], "email.sent")

    def test_bounced_event(self):
        # Provider bounce notifications can't be correlated to a stored
        # message: messageId is null, recipient is the reliable key.
        event = self.assert_tracking_event(
            sample_tracking_event(
                "email.bounced",
                messageId=None,
                providerMessageId="0100019fb…-000000",
                bounce={"type": "hard", "diagnostic": "550 5.1.1 user unknown"},
            )
        )
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.mta_response, "550 5.1.1 user unknown")
        self.assertEqual(event.description, "550 5.1.1 user unknown")
        self.assertIsNone(event.message_id)
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_complained_event(self):
        event = self.assert_tracking_event(
            sample_tracking_event(
                "email.complained",
                messageId=None,
                complaint={"feedbackType": "abuse"},
            )
        )
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.reject_reason, "spam")
        self.assertEqual(event.description, "abuse")

    def test_opened_event(self):
        event = self.assert_tracking_event(
            sample_tracking_event(
                "email.opened",
                open={
                    "machine": False,
                    "machineKind": None,
                    "userAgent": "Mozilla/5.0 (Macintosh) AppleWebKit/605",
                    "client": "Apple Mail",
                    "os": "macOS",
                    "device": "desktop",
                    "country": "US",
                },
            )
        )
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh) AppleWebKit/605")
        self.assertIsNone(event.click_url)

    def test_clicked_event(self):
        event = self.assert_tracking_event(
            sample_tracking_event(
                "email.clicked",
                click={
                    "url": "https://example.com/landing?x=1",
                    "machine": False,
                    "machineKind": None,
                    "userAgent": "Mozilla/5.0 Chrome/126",
                    "client": "Chrome",
                    "os": "macOS",
                    "device": "desktop",
                    "country": "US",
                },
            )
        )
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.click_url, "https://example.com/landing?x=1")
        self.assertEqual(event.user_agent, "Mozilla/5.0 Chrome/126")

    def test_unknown_event_type(self):
        # A future event type maps to "unknown" rather than erroring.
        event = self.assert_tracking_event(
            sample_tracking_event("email.delivery_delayed")
        )
        self.assertEqual(event.event_type, "unknown")

    def test_misconfigured_inbound(self):
        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set MailKite's *inbound* webhook"
            " to Anymail's MailKite *tracking* webhook URL.",
        ):
            self.client_post_signed(
                "/anymail/mailkite/tracking/",
                {"id": "msg_1", "type": "email.received"},
            )
