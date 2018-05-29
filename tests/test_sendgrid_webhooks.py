import json
from datetime import datetime

from django.utils.timezone import utc
from mock import ANY

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.sendgrid import SendGridTrackingWebhookView
from .webhook_cases import WebhookBasicAuthTestsMixin, WebhookTestCase


class SendGridWebhookSecurityTestCase(WebhookTestCase, WebhookBasicAuthTestsMixin):
    def call_webhook(self):
        return self.client.post('/anymail/sendgrid/tracking/',
                                content_type='application/json', data=json.dumps([]))

    # Actual tests are in WebhookBasicAuthTestsMixin


class SendGridDeliveryTestCase(WebhookTestCase):

    def test_processed_event(self):
        raw_events = [{
            "email": "recipient@example.com",
            "timestamp": 1461095246,
            "anymail_id": "<wrfRRvF7Q0GgwUo2CvDmEA@example.com>",
            "sg_event_id": "ZyjAM5rnQmuI1KFInHQ3Nw",
            "sg_message_id": "wrfRRvF7Q0GgwUo2CvDmEA.filter0425p1mdw1.13037.57168B4A1D.0",
            "event": "processed",
            "category": ["tag1", "tag2"],
            "custom1": "value1",
            "custom2": "value2",
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "queued")
        self.assertEqual(event.timestamp, datetime(2016, 4, 19, 19, 47, 26, tzinfo=utc))
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<wrfRRvF7Q0GgwUo2CvDmEA@example.com>")
        self.assertEqual(event.event_id, "ZyjAM5rnQmuI1KFInHQ3Nw")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["tag1", "tag2"])
        self.assertEqual(event.metadata, {"custom1": "value1", "custom2": "value2"})

    def test_delivered_event(self):
        raw_events = [{
            "ip": "167.89.17.173",
            "response": "250 2.0.0 OK 1461095248 m143si2210036ioe.159 - gsmtp ",
            "sg_event_id": "nOSv8m0eTQ-vxvwNwt3fZQ",
            "sg_message_id": "wrfRRvF7Q0GgwUo2CvDmEA.filter0425p1mdw1.13037.57168B4A1D.0",
            "tls": 1,
            "event": "delivered",
            "email": "recipient@example.com",
            "timestamp": 1461095250,
            "anymail_id": "<wrfRRvF7Q0GgwUo2CvDmEA@example.com>"
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.timestamp, datetime(2016, 4, 19, 19, 47, 30, tzinfo=utc))
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<wrfRRvF7Q0GgwUo2CvDmEA@example.com>")
        self.assertEqual(event.event_id, "nOSv8m0eTQ-vxvwNwt3fZQ")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.mta_response, "250 2.0.0 OK 1461095248 m143si2210036ioe.159 - gsmtp ")
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_dropped_invalid_event(self):
        raw_events = [{
            "email": "invalid@invalid",
            "anymail_id": "<YZkwwo_vQUidhSh7sCzkvQ@example.com>",
            "timestamp": 1461095250,
            "sg_event_id": "3NPOePGOTkeM_U3fgWApfg",
            "sg_message_id": "filter0093p1las1.9128.5717FB8127.0",
            "reason": "Invalid",
            "event": "dropped"
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<YZkwwo_vQUidhSh7sCzkvQ@example.com>")
        self.assertEqual(event.event_id, "3NPOePGOTkeM_U3fgWApfg")
        self.assertEqual(event.recipient, "invalid@invalid")
        self.assertEqual(event.reject_reason, "invalid")
        self.assertEqual(event.mta_response, None)

    def test_dropped_unsubscribed_event(self):
        raw_events = [{
            "email": "unsubscribe@example.com",
            "anymail_id": "<Kwx3gAIKQOG7Nd5XEO7guQ@example.com>",
            "timestamp": 1461095250,
            "sg_event_id": "oxy9OLwMTAy5EsuZn1qhIg",
            "sg_message_id": "filter0199p1las1.4745.5717FB6F5.0",
            "reason": "Unsubscribed Address",
            "event": "dropped"
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<Kwx3gAIKQOG7Nd5XEO7guQ@example.com>")
        self.assertEqual(event.event_id, "oxy9OLwMTAy5EsuZn1qhIg")
        self.assertEqual(event.recipient, "unsubscribe@example.com")
        self.assertEqual(event.reject_reason, "unsubscribed")
        self.assertEqual(event.mta_response, None)

    def test_bounce_event(self):
        raw_events = [{
            "ip": "167.89.17.173",
            "status": "5.1.1",
            "sg_event_id": "lC0Rc-FuQmKbnxCWxX1jRQ",
            "reason": "550 5.1.1 The email account that you tried to reach does not exist.",
            "sg_message_id": "Lli-03HcQ5-JLybO9fXsJg.filter0077p1las1.21536.5717FC482.0",
            "tls": 1,
            "event": "bounce",
            "email": "noreply@example.com",
            "timestamp": 1461095250,
            "anymail_id": "<Lli-03HcQ5-JLybO9fXsJg@example.com>",
            "type": "bounce"
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<Lli-03HcQ5-JLybO9fXsJg@example.com>")
        self.assertEqual(event.event_id, "lC0Rc-FuQmKbnxCWxX1jRQ")
        self.assertEqual(event.recipient, "noreply@example.com")
        self.assertEqual(event.mta_response, "550 5.1.1 The email account that you tried to reach does not exist.")

    def test_deferred_event(self):
        raw_events = [{
            "response": "Email was deferred due to the following reason(s): [IPs were throttled by recipient server]",
            "sg_event_id": "b_syL5UiTvWC_Ky5L6Bs5Q",
            "sg_message_id": "u9Gvi3mzT6iC2poAb58_qQ.filter0465p1mdw1.8054.5718271B40.0",
            "event": "deferred",
            "email": "recipient@example.com",
            "attempt": "1",
            "timestamp": 1461200990,
            "anymail_id": "<20160421010427.2847.6797@example.com>",
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<20160421010427.2847.6797@example.com>")
        self.assertEqual(event.event_id, "b_syL5UiTvWC_Ky5L6Bs5Q")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.mta_response,
                         "Email was deferred due to the following reason(s): [IPs were throttled by recipient server]")

    def test_open_event(self):
        raw_events = [{
            "email": "recipient@example.com",
            "timestamp": 1461095250,
            "ip": "66.102.6.229",
            "sg_event_id": "MjIwNDg5NTgtZGE3OC00NDI1LWFiMmMtMDUyZTU2ZmFkOTFm",
            "sg_message_id": "wrfRRvF7Q0GgwUo2CvDmEA.filter0425p1mdw1.13037.57168B4A1D.0",
            "anymail_id": "<20160421010427.2847.6797@example.com>",
            "useragent": "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0",
            "event": "open"
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<20160421010427.2847.6797@example.com>")
        self.assertEqual(event.event_id, "MjIwNDg5NTgtZGE3OC00NDI1LWFiMmMtMDUyZTU2ZmFkOTFm")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0")

    def test_click_event(self):
        raw_events = [{
            "ip": "24.130.34.103",
            "sg_event_id": "OTdlOGUzYjctYjc5Zi00OWE4LWE4YWUtNjIxNjk2ZTJlNGVi",
            "sg_message_id": "_fjPjuJfRW-IPs5SuvYotg.filter0590p1mdw1.2098.57168CFC4B.0",
            "useragent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_4) AppleWebKit/537.36",
            "anymail_id": "<20160421010427.2847.6797@example.com>",
            "event": "click",
            "url_offset": {"index": 0, "type": "html"},
            "email": "recipient@example.com",
            "timestamp": 1461095250,
            "url": "http://www.example.com"
        }]
        response = self.client.post('/anymail/sendgrid/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SendGridTrackingWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "<20160421010427.2847.6797@example.com>")
        self.assertEqual(event.event_id, "OTdlOGUzYjctYjc5Zi00OWE4LWE4YWUtNjIxNjk2ZTJlNGVi")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_4) AppleWebKit/537.36")
        self.assertEqual(event.click_url, "http://www.example.com")
