import json
from unittest.mock import ANY

from django.test import tag

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mailpace import MailPaceTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


@tag("mailpace")
class MailPaceWebhookSecurityTestCase(WebhookBasicAuthTestCase):
    def call_webhook(self):
        return self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps({ "event": "email.queued", "payload": {
                "created_at": "2021-11-16T14:50:15.445Z",
                "id": "1",
                "message_id": "string",
                "to": "example@test.com",
            }})
        )

    # Actual tests are in WebhookBasicAuthTestCase
    # TODO: add tests for MailPace webhook signing


@tag("mailpace")
class MailPaceDeliveryTestCase(WebhookTestCase):
    def test_queued_event(self):
        raw_event = {
            "event": "email.queued",
            "payload": {
                "status": "queued",
                "id": 1,
                "domain_id": 1,
                "created_at": "2021-11-16T14:50:15.445Z",
                "updated_at": "2021-11-16T14:50:15.445Z",
                "from": "sender@example.com",
                "to": "queued@example.com",
                "htmlbody": "string",
                "textbody": "string",
                "cc": "string",
                "bcc": "string",
                "subject": "string",
                "replyto": "string",
                "message_id": "string",
                "list_unsubscribe": "string",
                "tags": ["string", "string"]
            }
        }
        response = self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailPaceTrackingWebhookView,
            event=ANY,
            esp_name="MailPace",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "queued")
        self.assertEqual(event.message_id, "string")
        self.assertEqual(event.recipient, "queued@example.com")

    def test_delivered_event_no_tags(self):
        raw_event = {
            "event": "email.delivered",
            "payload": {
                "status": "delivered",
                "id": 1,
                "domain_id": 1,
                "created_at": "2021-11-16T14:50:15.445Z",
                "updated_at": "2021-11-16T14:50:15.445Z",
                "from": "sender@example.com",
                "to": "queued@example.com",
                "htmlbody": "string",
                "textbody": "string",
                "cc": "string",
                "bcc": "string",
                "subject": "string",
                "replyto": "string",
                "message_id": "string",
                "list_unsubscribe": "string",
            }
        }
        response = self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailPaceTrackingWebhookView,
            event=ANY,
            esp_name="MailPace",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.tags, [])

    def test_rejected_event_reason(self):
        raw_event = {
            "event": "email.spam",
            "payload": {
                "status": "spam",
                "id": 1,
                "domain_id": 1,
                "created_at": "2021-11-16T14:50:15.445Z",
                "updated_at": "2021-11-16T14:50:15.445Z",
                "from": "sender@example.com",
                "to": "queued@example.com",
                "htmlbody": "string",
                "textbody": "string",
                "cc": "string",
                "bcc": "string",
                "subject": "string",
                "replyto": "string",
                "message_id": "string",
                "list_unsubscribe": "string",
            }
        }
        response = self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailPaceTrackingWebhookView,
            event=ANY,
            esp_name="MailPace",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.reject_reason, "spam")
