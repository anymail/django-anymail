import json
from datetime import datetime, timezone
from unittest.mock import ANY

from django.test import tag

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mailjet import MailjetTrackingWebhookView
from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


@tag('mailjet')
class MailjetWebhookSecurityTestCase(WebhookBasicAuthTestCase):
    def call_webhook(self):
        return self.client.post('/anymail/mailjet/tracking/',
                                content_type='application/json', data=json.dumps([]))

    # Actual tests are in WebhookBasicAuthTestCase


@tag('mailjet')
class MailjetDeliveryTestCase(WebhookTestCase):

    def test_sent_event(self):
        # Mailjet's "sent" event indicates receiving MTA has accepted message; Anymail calls this "delivered"
        raw_events = [{
            "event": "sent",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "recipient@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "tag1",
            "mj_message_id": "12345678901234567",
            "smtp_reply": "sent (250 2.0.0 OK 1498093527 a67bc12345def.22 - gsmtp)",
            "Payload": "{\"meta1\": \"simple string\", \"meta2\": 2}",
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.timestamp, datetime(2017, 6, 22, 1, 5, 27, tzinfo=timezone.utc))
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.mta_response, "sent (250 2.0.0 OK 1498093527 a67bc12345def.22 - gsmtp)")
        self.assertEqual(event.message_id, "12345678901234567")  # converted to str (matching backend status)
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["tag1"])
        self.assertEqual(event.metadata, {"meta1": "simple string", "meta2": 2})

    def test_open_event(self):
        raw_events = [{
            "event": "open",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "recipient@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "ip": "192.168.100.100",
            "geo": "US",
            "agent": "Mozilla/5.0 (via ggpht.com GoogleImageProxy)",
            "Payload": "",
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (via ggpht.com GoogleImageProxy)")
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_click_event(self):
        raw_events = [{
            "event": "open",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "recipient@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "url": "http://example.com",
            "ip": "192.168.100.100",
            "geo": "US",
            "agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) Chrome/58.0.3029.110",
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_5) Chrome/58.0.3029.110")
        self.assertEqual(event.click_url, "http://example.com")
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_bounce_event(self):
        raw_events = [{
            "event": "bounce",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "invalid@invalid",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "blocked": True,
            "hard_bounce": True,
            "error_related_to": "domain",
            "error": "invalid domain"
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "invalid@invalid")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.mta_response, None)

    def test_blocked_event(self):
        raw_events = [{
            "event": "blocked",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "bad@example.com",
            "mj_campaign_id": 0,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "error_related_to": "domain",
            "error": "typofix",
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "bad@example.com")
        self.assertEqual(event.reject_reason, "invalid")
        self.assertEqual(event.mta_response, None)

    def test_spam_event(self):
        raw_events = [{
            "event": "spam",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "spam@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "source": "greylisted"
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "spam@example.com")

    def test_unsub_event(self):
        raw_events = [{
            "event": "unsub",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "recipient@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "mj_list_id": 0,
            "ip": "127.0.0.4",
            "geo": "",
            "agent": "List-Unsubscribe"
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "unsubscribed")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_bounced_greylist_event(self):
        # greylist "bounce" should be reported as "deferred" (will be retried later)
        raw_events = [{
            "event": "bounce",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "protected@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "blocked": True,
            "hard_bounce": False,
            "error_related_to": "domain",
            "error": "greylisted"
        }]
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.message_id, "12345678901234567")
        self.assertEqual(event.recipient, "protected@example.com")
        self.assertEqual(event.reject_reason, "other")

    def test_non_grouped_event(self):
        # If you don't enable "group events" on a webhook, Mailjet sends a single bare event
        # (not a list of one event, despite what the docs say).
        raw_event = {
            "event": "sent",
            "time": 1498093527,
            "MessageID": 12345678901234567,
            "email": "recipient@example.com",
            "mj_campaign_id": 1234567890,
            "mj_contact_id": 9876543210,
            "customcampaign": "",
            "mj_message_id": "12345678901234567",
            "smtp_reply": "sent (250 2.0.0 OK 1498093527 a67bc12345def.22 - gsmtp)",
            "Payload": "",
        }
        response = self.client.post('/anymail/mailjet/tracking/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=MailjetTrackingWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.timestamp, datetime(2017, 6, 22, 1, 5, 27, tzinfo=timezone.utc))
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.mta_response, "sent (250 2.0.0 OK 1498093527 a67bc12345def.22 - gsmtp)")
        self.assertEqual(event.message_id, "12345678901234567")  # converted to str (matching backend status)
        self.assertEqual(event.recipient, "recipient@example.com")
