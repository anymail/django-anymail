from datetime import datetime, timezone
from unittest.mock import ANY

from django.test import tag

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mailtrap import MailtrapTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


@tag("mailtrap")
class MailtrapWebhookSecurityTestCase(WebhookBasicAuthTestCase):
    def call_webhook(self):
        return self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data={},
        )

    # Actual tests are in WebhookBasicAuthTestCase


@tag("mailtrap")
class MailtrapDeliveryTestCase(WebhookTestCase):
    def test_sent_event(self):
        payload = {
            "events": [
                {
                    "event": "delivery",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "category": "password-reset",
                    "custom_variables": {"variable_a": "value", "variable_b": "value2"},
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(
            event.timestamp, datetime(2017, 6, 22, 1, 5, 27, tzinfo=timezone.utc)
        )
        self.assertEqual(event.esp_event, payload["events"][0])
        self.assertEqual(
            event.mta_response,
            None,
        )
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(event.tags, ["password-reset"])
        self.assertEqual(
            event.metadata, {"variable_a": "value", "variable_b": "value2"}
        )

    def test_open_event(self):
        payload = {
            "events": [
                {
                    "event": "open",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "ip": "192.168.1.42",
                    "user_agent": "Mozilla/5.0 (via ggpht.com GoogleImageProxy)",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(
            event.user_agent, "Mozilla/5.0 (via ggpht.com GoogleImageProxy)"
        )
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_click_event(self):
        payload = {
            "events": [
                {
                    "event": "click",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "category": "custom-value",
                    "custom_variables": {"testing": True},
                    "ip": "192.168.1.42",
                    "user_agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) Chrome/58.0.3029.110)"
                    ),
                    "url": "http://example.com/anymail",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(
            event.user_agent,
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) Chrome/58.0.3029.110)",
        )
        self.assertEqual(event.click_url, "http://example.com/anymail")
        self.assertEqual(event.tags, ["custom-value"])
        self.assertEqual(event.metadata, {"testing": True})

    def test_bounce_event(self):
        payload = {
            "events": [
                {
                    "event": "bounce",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "invalid@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "category": "custom-value",
                    "custom_variables": {"testing": True},
                    "response": (
                        "bounced (550 5.1.1 The email account that you tried to reach "
                        "does not exist. a67bc12345def.22 - gsmtp)"
                    ),
                    "response_code": 550,
                    "bounce_category": "hard",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "invalid@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(
            event.mta_response,
            (
                "bounced (550 5.1.1 The email account that you tried to reach does not exist. "
                "a67bc12345def.22 - gsmtp)"
            ),
        )

    def test_soft_bounce_event(self):
        payload = {
            "events": [
                {
                    "event": "soft bounce",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "response": (
                        "soft bounce (450 4.2.0 The email account that you tried to reach is "
                        "temporarily unavailable. a67bc12345def.22 - gsmtp)"
                    ),
                    "response_code": 450,
                    "bounce_category": "unavailable",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(event.reject_reason, "other")
        self.assertEqual(
            event.mta_response,
            (
                "soft bounce (450 4.2.0 The email account that you tried to reach is "
                "temporarily unavailable. a67bc12345def.22 - gsmtp)"
            ),
        )

    def test_spam_event(self):
        payload = {
            "events": [
                {
                    "event": "spam",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(event.reject_reason, "spam")

    def test_unsubscribe_event(self):
        payload = {
            "events": [
                {
                    "event": "unsubscribe",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "ip": "192.168.1.42",
                    "user_agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) Chrome/58.0.3029.110)"
                    ),
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "unsubscribed")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(event.reject_reason, "unsubscribed")
        self.assertEqual(
            event.user_agent,
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) Chrome/58.0.3029.110)",
        )

    def test_suspension_event(self):
        payload = {
            "events": [
                {
                    "event": "suspension",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "reason": "other",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(event.reject_reason, "other")

    def test_reject_event(self):
        payload = {
            "events": [
                {
                    "event": "reject",
                    "timestamp": 1498093527,
                    "sending_stream": "transactional",
                    "message_id": "1df37d17-0286-4d8b-8edf-bc4ec5be86e6",
                    "email": "receiver@example.com",
                    "event_id": "bede7236-2284-43d6-a953-1fdcafd0fdbc",
                    "reason": "unknown",
                },
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/tracking/",
            content_type="application/json",
            data=payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailtrapTrackingWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.message_id, "1df37d17-0286-4d8b-8edf-bc4ec5be86e6")
        self.assertEqual(event.recipient, "receiver@example.com")
        self.assertEqual(event.reject_reason, "blocked")
