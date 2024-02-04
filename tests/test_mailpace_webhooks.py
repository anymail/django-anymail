import json
import unittest
from base64 import b64encode
from unittest.mock import ANY

from django.test import tag

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mailpace import MailPaceTrackingWebhookView

from .utils_mailpace import ClientWithMailPaceSignature, make_key
from .webhook_cases import WebhookTestCase

# These tests are triggered both with and without 'pynacl' installed,
# without the ability to generate a signing key, there is no way to test
# the webhook signature validation.
try:
    from nacl.signing import SigningKey

    PYNACL_INSTALLED = bool(SigningKey)
except ImportError:
    PYNACL_INSTALLED = False


@tag("mailpace")
@unittest.skipUnless(PYNACL_INSTALLED, "pynacl is not installed")
class MailPaceWebhookSecurityTestCase(WebhookTestCase):
    client_class = ClientWithMailPaceSignature

    def setUp(self):
        super().setUp()
        self.clear_basic_auth()
        self.client.set_private_key(make_key())

    def test_failed_signature_check(self):
        response = self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps({"some": "data"}),
            headers={"X-MailPace-Signature": b64encode("invalid".encode("utf-8"))},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps({"some": "data"}),
            headers={"X-MailPace-Signature": "garbage"},
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/anymail/mailpace/tracking/",
            content_type="application/json",
            data=json.dumps({"some": "data"}),
            headers={"X-MailPace-Signature": ""},
        )
        self.assertEqual(response.status_code, 400)


@tag("mailpace")
@unittest.skipUnless(PYNACL_INSTALLED, "pynacl is not installed")
class MailPaceDeliveryTestCase(WebhookTestCase):
    client_class = ClientWithMailPaceSignature

    def setUp(self):
        super().setUp()
        self.clear_basic_auth()
        self.client.set_private_key(make_key())

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
                "tags": ["string", "string"],
            },
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
            },
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
            },
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
