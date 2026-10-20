import json
from datetime import datetime, timezone
from unittest.mock import ANY

from django.test import tag
from django.urls import reverse

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.smtp2go import SMTP2GOTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


@tag("smtp2go")
class SMTP2GOWebhookSecurityTests(WebhookBasicAuthTestCase):
    def call_webhook(self):
        return self.client.post(
            "/anymail/smtp2go/tracking/",
            content_type="application/json",
            data=json.dumps({"event": "processed"}),
        )


@tag("smtp2go")
class SMTP2GOTrackingWebhookTests(WebhookTestCase):
    def setUp(self):
        super().setUp()
        # Constructed from SMTP2GO's documented fields; not a live capture.
        self.raw_event = {
            "event": "delivered",
            "time": "2026-10-06 12:34:56",
            "sendtime": "2026-10-06 12:34:50",
            "sender": "from@example.com",
            "rcpt": "recipient@example.com",
            "recipients": "recipient@example.com,other@example.com",
            "email_id": "1u0SwL-B9zBpi9ffUq-JAB2",
            "id": "webhook-event-id",
            "message-id": "<different-mime-id@example.com>",
            "message": "250 2.0.0 OK",
            "context": "Additional provider information",
        }

    def post_event(self, event=None):
        return self.client.post(
            "/anymail/smtp2go/tracking/",
            content_type="application/json",
            data=json.dumps(self.raw_event if event is None else event),
        )

    def get_event(self):
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=SMTP2GOTrackingWebhookView,
            event=ANY,
            esp_name="SMTP2GO",
        )
        self.assertIsInstance(kwargs["event"], AnymailTrackingEvent)
        self.inbound_handler.assert_not_called()
        return kwargs["event"]

    def test_url_name(self):
        self.assertEqual(
            reverse("anymail:smtp2go_tracking_webhook"), "/anymail/smtp2go/tracking/"
        )

    def test_delivered(self):
        self.assertEqual(self.post_event().status_code, 200)
        event = self.get_event()
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(
            event.timestamp, datetime(2026, 10, 6, 12, 34, 56, tzinfo=timezone.utc)
        )
        self.assertEqual(event.message_id, "1u0SwL-B9zBpi9ffUq-JAB2")
        self.assertEqual(event.event_id, "webhook-event-id")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.mta_response, "250 2.0.0 OK")
        self.assertEqual(event.esp_event, self.raw_event)
        self.assertIsNone(event.reject_reason)
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_event_types(self):
        for esp_type, expected_type, reject_reason in [
            ("processed", "queued", None),
            ("delivered", "delivered", None),
            ("open", "opened", None),
            ("click", "clicked", None),
            ("bounce", "bounced", "bounced"),
            ("spam", "complained", "spam"),
            ("unsubscribe", "unsubscribed", "unsubscribed"),
            ("resubscribe", "subscribed", None),
            ("reject", "rejected", "other"),
            ("future-event", "unknown", None),
        ]:
            with self.subTest(esp_type=esp_type):
                self.tracking_handler.reset_mock()
                self.raw_event["event"] = esp_type
                self.assertEqual(self.post_event().status_code, 200)
                event = self.get_event()
                self.assertEqual(event.event_type, expected_type)
                self.assertEqual(event.reject_reason, reject_reason)

    def test_bounces(self):
        # Both bounce types are final bounces, not temporary delivery deferrals.
        for bounce_type in ["hard", "soft"]:
            with self.subTest(bounce_type=bounce_type):
                self.tracking_handler.reset_mock()
                self.raw_event.update(
                    event="bounce", bounce=bounce_type, message="550 Rejected"
                )
                self.assertEqual(self.post_event().status_code, 200)
                event = self.get_event()
                self.assertEqual(event.event_type, "bounced")
                self.assertEqual(event.reject_reason, "bounced")
                self.assertEqual(event.esp_event["bounce"], bounce_type)
                self.assertEqual(event.mta_response, "550 Rejected")

    def test_engagement_details_preserved(self):
        self.raw_event.update(
            {
                "event": "click",
                "user-agent": "Mozilla/5.0",
                "srchost": "192.0.2.1",
                "context": "https://example.com/",
                "x-custom": "custom value",
            }
        )
        self.assertEqual(self.post_event().status_code, 200)
        event = self.get_event()
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.user_agent, "Mozilla/5.0")
        self.assertEqual(event.esp_event["context"], "https://example.com/")
        self.assertEqual(event.esp_event["x-custom"], "custom value")

    def test_form_encoded(self):
        response = self.client.post("/anymail/smtp2go/tracking/", data=self.raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_event()
        self.assertEqual(event.esp_event, self.raw_event)
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(
            event.timestamp, datetime(2026, 10, 6, 12, 34, 56, tzinfo=timezone.utc)
        )

    def test_timestamps(self):
        expected = datetime(2026, 10, 6, 12, 34, 56, tzinfo=timezone.utc)
        for value in [
            "2026-10-06T12:34:56Z",
            "2026-10-06T14:34:56+02:00",
            expected.timestamp(),
            str(expected.timestamp()),
        ]:
            with self.subTest(value=value):
                self.tracking_handler.reset_mock()
                self.raw_event["time"] = value
                self.assertEqual(self.post_event().status_code, 200)
                self.assertEqual(self.get_event().timestamp, expected)

    def test_invalid_timestamp(self):
        for value in [None, "bad timestamp", "2026-02-30 12:34:56", 1e100, {}, []]:
            with self.subTest(value=value):
                self.tracking_handler.reset_mock()
                self.raw_event["time"] = value
                self.assertEqual(self.post_event().status_code, 200)
                self.assertIsNone(self.get_event().timestamp)

    def test_minimal_event(self):
        self.assertEqual(self.post_event({"event": "processed"}).status_code, 200)
        event = self.get_event()
        self.assertEqual(event.event_type, "queued")
        self.assertIsNone(event.timestamp)
        self.assertIsNone(event.message_id)
        self.assertIsNone(event.recipient)

    def test_invalid_payload(self):
        for payload in [{}, [], None, "text", {"event": 42}]:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/anymail/smtp2go/tracking/",
                    content_type="application/json",
                    data=json.dumps(payload),
                )
                self.assertEqual(response.status_code, 400)
        self.tracking_handler.assert_not_called()

    def test_invalid_json(self):
        response = self.client.post(
            "/anymail/smtp2go/tracking/",
            content_type="application/json",
            data="invalid JSON",
        )
        self.assertEqual(response.status_code, 400)
        self.tracking_handler.assert_not_called()

    def test_handler_failure_propagates(self):
        self.tracking_handler.side_effect = RuntimeError("Receiver failed")
        with self.assertRaisesMessage(RuntimeError, "Receiver failed"):
            self.post_event()
