import json
import unittest
from base64 import b64encode
from datetime import datetime
from unittest.mock import ANY

from django.test import tag
from django.utils.timezone import utc

from anymail.exceptions import AnymailConfigurationError
from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.postal import PostalTrackingWebhookView
from .utils_postal import ClientWithPostalSignature, make_key
from .webhook_cases import WebhookTestCase


@tag('postal')
@unittest.skipUnless(ClientWithPostalSignature, "Install 'cryptography' to run postal webhook tests")
class PostalWebhookSecurityTestCase(WebhookTestCase):
    client_class = ClientWithPostalSignature

    def setUp(self):
        super().setUp()
        self.clear_basic_auth()

        self.client.set_private_key(make_key())

    def test_failed_signature_check(self):
        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps({'some': 'data'}),
                                    HTTP_X_POSTAL_SIGNATURE=b64encode('invalid'.encode('utf-8')))
        self.assertEqual(response.status_code, 400)

        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps({'some': 'data'}),
                                    HTTP_X_POSTAL_SIGNATURE='garbage')
        self.assertEqual(response.status_code, 400)

        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps({'some': 'data'}),
                                    HTTP_X_POSTAL_SIGNATURE='')
        self.assertEqual(response.status_code, 400)


@tag('postal')
@unittest.skipUnless(ClientWithPostalSignature, "Install 'cryptography' to run postal webhook tests")
class PostalDeliveryTestCase(WebhookTestCase):
    client_class = ClientWithPostalSignature

    def setUp(self):
        super().setUp()
        self.clear_basic_auth()

        self.client.set_private_key(make_key())

    def test_bounce_event(self):
        raw_event = {
            "event": "MessageDelayed",
            "timestamp": 1606753101.961181,
            "payload": {
                "original_message": {
                    "id": 233843,
                    "token": "McC2tuqg7mhx",
                    "direction": "outgoing",
                    "message_id": "7b82aac4-5d63-41b8-8e35-9faa31a892dc@rp.postal.example.com",
                    "to": "bounce@example.com",
                    "from": "sender@example.com",
                    "subject": "...",
                    "timestamp": 1606436187.8883688,
                    "spam_status": "NotChecked",
                    "tag": None
                },
                "bounce": {
                    "id": 233864,
                    "token": "nII5p0Cp8onV",
                    "direction": "incoming",
                    "message_id": "E1kiRR8-0001ay-Iq@example.com",
                    "to": "bk87jw@psrp.postal.example.com",
                    "from": None,
                    "subject": "Mail delivery failed: returning message to sender",
                    "timestamp": 1606436523.6060522,
                    "spam_status": "NotChecked",
                    "tag": None
                },
                "details": "details",
                "output": "server output",
                "sent_with_ssl": None,
                "timestamp": 1606753101.9110143,
                "time": None
            },
            "uuid": "0fcc831f-92b9-4e2b-97f2-d873abc77fab"
        }

        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=PostalTrackingWebhookView,
                                                      event=ANY, esp_name='Postal')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.timestamp, datetime.fromtimestamp(1606753101, tz=utc))
        self.assertEqual(event.message_id, 233843)
        self.assertEqual(event.event_id, "0fcc831f-92b9-4e2b-97f2-d873abc77fab")
        self.assertEqual(event.recipient, "bounce@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description,
                         "details")
        self.assertEqual(event.mta_response,
                         "server output")

    def test_deferred_event(self):
        raw_event = {
            "event": "MessageDelayed",
            "timestamp": 1606753101.961181,
            "payload": {
                "message": {
                    "id": 1564,
                    "token": "Kmo8CRdjuM7B",
                    "direction": "outgoing",
                    "message_id": "7b095c0e-2c98-4e68-a41f-7bd217a83925@rp.postal.example.com",
                    "to": "deferred@example.com",
                    "from": "test@postal.example.com",
                    "subject": "Test Message at November 30, 2020 16:03",
                    "timestamp": 1606752235.195664,
                    "spam_status": "NotChecked",
                    "tag": None
                },
                "status": "SoftFail",
                "details": "details",
                "output": "server output",
                "sent_with_ssl": None,
                "timestamp": 1606753101.9110143,
                "time": None
            },
            "uuid": "0fcc831f-92b9-4e2b-97f2-d873abc77fab"
        }
        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=PostalTrackingWebhookView,
                                                      event=ANY, esp_name='Postal')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.timestamp, datetime.fromtimestamp(1606753101, tz=utc))
        self.assertEqual(event.message_id, 1564)
        self.assertEqual(event.event_id, "0fcc831f-92b9-4e2b-97f2-d873abc77fab")
        self.assertEqual(event.recipient, "deferred@example.com")
        self.assertEqual(event.reject_reason, None)
        self.assertEqual(event.description,
                         "details")
        self.assertEqual(event.mta_response,
                         "server output")

    def test_queued_event(self):
        raw_event = {
            "event": "MessageHeld",
            "timestamp": 1606753101.330977,
            "payload": {
                "message": {
                    "id": 1568,
                    "token": "VRvQMS20Bb4Y",
                    "direction": "outgoing",
                    "message_id": "ec7b6375-4045-451a-9503-2a23a607c1c1@rp.postal.example.com",
                    "to": "suppressed@example.com",
                    "from": "test@example.com",
                    "subject": "Test Message at November 30, 2020 16:12",
                    "timestamp": 1606752750.993815,
                    "spam_status": "NotChecked",
                    "tag": None
                },
                "status": "Held",
                "details": "Recipient (suppressed@example.com) is on the suppression list",
                "output": "server output",
                "sent_with_ssl": None,
                "timestamp": 1606752751.8933666,
                "time": None
            },
            "uuid": "9be13015-2e54-456c-bf66-eacbe33da824"
        }
        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=PostalTrackingWebhookView,
                                                      event=ANY, esp_name='Postal')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "queued")
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.timestamp, datetime.fromtimestamp(1606753101, tz=utc))
        self.assertEqual(event.message_id, 1568)
        self.assertEqual(event.event_id, "9be13015-2e54-456c-bf66-eacbe33da824")
        self.assertEqual(event.recipient, "suppressed@example.com")
        self.assertEqual(event.reject_reason, None)
        self.assertEqual(event.description,
                         "Recipient (suppressed@example.com) is on the suppression list")
        self.assertEqual(event.mta_response,
                         "server output")

    def test_failed_event(self):
        raw_event = {
            "event": "MessageDeliveryFailed",
            "timestamp": 1606753101.084981,
            "payload": {
                "message": {
                    "id": 1571,
                    "token": "MzWWQPubXXWz",
                    "direction": "outgoing",
                    "message_id": "cfb29da8ed1e4ed5a6c8a0f24d7a9ef3@rp.postal.example.com",
                    "to": "failed@example.com",
                    "from": "test@example.com",
                    "subject": "Message delivery failed...",
                    "timestamp": 1606753318.072171,
                    "spam_status": "NotChecked",
                    "tag": None
                },
                "status": "HardFail",
                "details": "Could not deliver",
                "output": "server output",
                "sent_with_ssl": None,
                "timestamp": 1606753318.7010343,
                "time": None
            },
            "uuid": "5fec5077-dae7-4989-94d5-e1963f3e9181"
        }
        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=PostalTrackingWebhookView,
                                                      event=ANY, esp_name='Postal')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "failed")
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.timestamp, datetime.fromtimestamp(1606753101, tz=utc))
        self.assertEqual(event.message_id, 1571)
        self.assertEqual(event.event_id, "5fec5077-dae7-4989-94d5-e1963f3e9181")
        self.assertEqual(event.recipient, "failed@example.com")
        self.assertEqual(event.reject_reason, None)
        self.assertEqual(event.description,
                         "Could not deliver")
        self.assertEqual(event.mta_response,
                         "server output")

    def test_delivered_event(self):
        raw_event = {
            "event": "MessageSent",
            "timestamp": 1606753101.354368,
            "payload": {
                "message": {
                    "id": 1563,
                    "token": "zw6psSlgo6ki",
                    "direction": "outgoing",
                    "message_id": "c462ad36-be49-469c-b7b2-dfd317eb40fa@rp.postal.example.com",
                    "to": "recipient@example.com",
                    "from": "test@example.com",
                    "subject": "Test Message at November 30, 2020 16:01",
                    "timestamp": 1606752104.699201,
                    "spam_status": "NotChecked",
                    "tag": "welcome-email"
                },
                "status": "Sent",
                "details": "Message for recipient@example.com accepted",
                "output": "250 2.0.0 OK\n",
                "sent_with_ssl": False,
                "timestamp": 1606752106.9858062,
                "time": 0.89
            },
            "uuid": "58e8d7ee-2cd5-4db2-9af3-3f436105795a"
        }
        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=PostalTrackingWebhookView,
                                                      event=ANY, esp_name='Postal')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.timestamp, datetime.fromtimestamp(1606753101, tz=utc))
        self.assertEqual(event.message_id, 1563)
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["welcome-email"])
        self.assertEqual(event.metadata, None)

    def test_ignore_incoming_events(self):
        raw_event = {
            "event": "MessageDeliveryFailed",
            "timestamp": 1606756014.694645,
            "payload": {
                "message": {
                    "id": 1575,
                    "token": "lPDuNhHfV8aU",
                    "direction": "incoming",
                    "message_id": "asdf@other-mta.example.com",
                    "to": "incoming@example.com",
                    "from": "sender@example.com",
                    "subject": "test",
                    "timestamp": 1606756008.718169,
                    "spam_status": "NotSpam",
                    "tag": None
                },
                "status": "HardFail",
                "details": "Received a 400 from https://anymail.example.com/anymail/postal/tracking/.",
                "output": "Not found",
                "sent_with_ssl": False,
                "timestamp": 1606756014.1078613,
                "time": 0.15
            },
            "uuid": "a01724c0-0d1a-4090-89aa-c3da5a683375"
        }
        response = self.client.post('/anymail/postal/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.tracking_handler.call_count, 0)

    def test_misconfigured_inbound(self):
        errmsg = "You seem to have set Postal's *inbound* webhook to Anymail's Postal *tracking* webhook URL."
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client.post('/anymail/postal/tracking/', content_type='application/json',
                             data=json.dumps({"rcpt_to": "to@example.org"}))
