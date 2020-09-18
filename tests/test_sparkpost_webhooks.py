import json
from datetime import datetime

from django.test import override_settings, tag
from django.utils.timezone import utc
from mock import ANY

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.sparkpost import SparkPostTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


@tag('sparkpost')
class SparkPostWebhookSecurityTestCase(WebhookBasicAuthTestCase):
    def call_webhook(self):
        return self.client.post('/anymail/sparkpost/tracking/',
                                content_type='application/json', data=json.dumps([]))

    # Actual tests are in WebhookBasicAuthTestCase


@tag('sparkpost')
class SparkPostDeliveryTestCase(WebhookTestCase):

    def test_ping_event(self):
        raw_events = [{'msys': {}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.tracking_handler.called)  # no real events

    def test_injection_event(self):
        # Full event from SparkPost sample events API. (Later tests omit unused event fields.)
        raw_events = [{"msys": {"message_event": {
            "type": "injection",
            "campaign_id": "Example Campaign Name",
            "customer_id": "1",
            "event_id": "92356927693813856",
            "friendly_from": "sender@example.com",
            "ip_pool": "Example-Ip-Pool",
            "message_id": "000443ee14578172be22",
            "msg_from": "sender@example.com",
            "msg_size": "1337",
            "rcpt_meta": {"customKey": "customValue"},
            "rcpt_tags": ["male", "US"],
            "rcpt_to": "recipient@example.com",
            "raw_rcpt_to": "recipient@example.com",
            "rcpt_type": "cc",
            "routing_domain": "example.com",
            "sending_ip": "127.0.0.1",
            "sms_coding": "ASCII",
            "sms_dst": "7876712656",
            "sms_dst_npi": "E164",
            "sms_dst_ton": "International",
            "sms_segments": 5,
            "sms_src": "1234",
            "sms_src_npi": "E164",
            "sms_src_ton": "Unknown",
            "sms_text": "lol",
            "subaccount_id": "101",
            "subject": "Summer deals are here!",
            "template_id": "templ-1234",
            "template_version": "1",
            "timestamp": "1454442600",
            "transmission_id": "65832150921904138"
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "queued")
        self.assertEqual(event.timestamp, datetime(2016, 2, 2, 19, 50, 00, tzinfo=utc))
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "65832150921904138")  # actually transmission_id
        self.assertEqual(event.event_id, "92356927693813856")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["Example Campaign Name"])  # campaign_id (rcpt_tags not available at send)
        self.assertEqual(event.metadata, {"customKey": "customValue"})  # includes transmissions.send metadata

    def test_delivery_event(self):
        raw_events = [{"msys": {"message_event": {
            "type": "delivery",
            "event_id": "92356927693813856",
            "rcpt_to": "recipient@example.com",
            "raw_rcpt_to": "Recipient@example.com",
            "rcpt_meta": {},
            "timestamp": "1454442600",
            "transmission_id": "65832150921904138"
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.recipient, "Recipient@example.com")
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_bounce_event(self):
        raw_events = [{
            "msys": {"message_event": {
                "type": "bounce",
                "bounce_class": "10",
                "customer_id": "00000",
                "error_code": "550",
                "event_id": "84345317653491230",
                "message_id": "0004e3724f57753a3561",
                "raw_rcpt_to": "bounce@example.com",
                "raw_reason": "550 5.1.1 <bounce@example.com>: Recipient address rejected: User unknown",
                "rcpt_to": "bounce@example.com",
                "reason": "550 5.1.1 ...@... Recipient address rejected: ...",
                "timestamp": "1464824548",
                "transmission_id": "84345317650824116",
            }},
            "cust": {"id": "00000"}  # Included in real (non-example) event data
        }]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "84345317650824116")  # transmission_id
        self.assertEqual(event.event_id, "84345317653491230")
        self.assertEqual(event.recipient, "bounce@example.com")
        self.assertEqual(event.reject_reason, "invalid")
        self.assertEqual(event.mta_response,
                         "550 5.1.1 <bounce@example.com>: Recipient address rejected: User unknown")

    def test_delay_event(self):
        raw_events = [{"msys": {"message_event": {
            "type": "delay",
            "bounce_class": "21",
            "error_code": "454",
            "event_id": "84345317653675522",
            "message_id": "0004e3724f57753a3861",
            "num_retries": "1",
            "queue_time": "1200161",
            "raw_rcpt_to": "recipient@nomx.example.com",
            "raw_reason": "454 4.4.4 [internal] no MX or A for domain",
            "rcpt_to": "recipient@nomx.example.com",
            "reason": "454 4.4.4 [internal] no MX or A for domain",
            "timestamp": "1464825748",
            "transmission_id": "84345317650824116",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.recipient, "recipient@nomx.example.com")
        self.assertEqual(event.mta_response, "454 4.4.4 [internal] no MX or A for domain")

    def test_unsubscribe_event(self):
        raw_events = [{"msys": {"unsubscribe_event": {
            "type": "list_unsubscribe",
            "event_id": "66331590532986193",
            "message_id": "0004278150574660124d",
            "raw_rcpt_to": "recipient@example.com",
            "rcpt_to": "recipient@example.com",
            "timestamp": "1464894280",
            "transmission_id": "84345993965073285",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "unsubscribed")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_generation_rejection_event(self):
        # This is what you get if you try to send to a suppressed address
        raw_events = [{"msys": {"gen_event": {
            "type": "generation_rejection",
            "error_code": "554",
            "event_id": "102360394390563734",
            "message_id": "0005c29950577c61695d",
            "raw_rcpt_to": "suppressed@example.com",
            "raw_reason": "554 5.7.1 recipient address suppressed due to customer policy",
            "rcpt_to": "suppressed@example.com",
            "reason": "554 5.7.1 recipient address suppressed due to customer policy",
            "timestamp": "1464900034",
            "transmission_id": "102360394387646691",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.recipient, "suppressed@example.com")
        self.assertEqual(event.mta_response, "554 5.7.1 recipient address suppressed due to customer policy")

    def test_generation_failure_event(self):
        # This is what you get from a template rendering failure
        raw_events = [{"msys": {"message_event": {
            "type": "generation_failure",
            "error_code": "554",
            "event_id": "139013368081587254",
            "raw_rcpt_to": "recipient@example.com",
            "raw_reason": "554 5.3.3 [internal] Error while rendering part html: ...",
            "rcpt_subs": {"name": "Alice", "order_no": "12345"},
            "rcpt_to": "recipient@example.com",
            "reason": "554 5.3.3 [internal] Error while rendering part html: ...",
            "tdate": "2018-10-11T23:24:45.000Z",
            "template_id": "test-template",
            "template_version": "3",
            "transmission_id": "139013368081177607",
            "timestamp": "2018-10-11T23:24:45.000+00:00"
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "failed")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.mta_response, "554 5.3.3 [internal] Error while rendering part html: ...")

    def test_bounce_challenge_response(self):
        # Test for changing initial event_type based on bounce_class
        raw_events = [{"msys": {"message_event": {
            "type": "bounce",
            "bounce_class": "60",
            "raw_rcpt_to": "vacationing@example.com",
            "rcpt_to": "vacationing@example.com",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "autoresponded")
        self.assertEqual(event.reject_reason, "other")
        self.assertEqual(event.recipient, "vacationing@example.com")

    def test_open_event(self):
        raw_events = [{"msys": {"track_event": {
            "type": "open",
            "raw_rcpt_to": "recipient@example.com",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36")

    @override_settings(ANYMAIL_SPARKPOST_TRACK_INITIAL_OPEN_AS_OPENED=True)
    def test_initial_open_event_as_opened(self):
        # Mapping SparkPost "initial_open" to Anymail normalized "opened" is opt-in via a setting,
        # for backwards compatibility and to avoid reporting duplicate "opened" events when all
        # SparkPost event types are enabled.
        raw_events = [{"msys": {"track_event": {
            "type": "initial_open",
            "raw_rcpt_to": "recipient@example.com",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36")

    def test_initial_open_event_as_unknown(self):
        # By default, SparkPost "initial_open" is *not* mapped to Anymail "opened".
        raw_events = [{"msys": {"track_event": {
            "type": "initial_open",
            "raw_rcpt_to": "recipient@example.com",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "unknown")
        # Here's how to get the raw SparkPost event type:
        self.assertEqual(event.esp_event["msys"].get("track_event", {}).get("type"), "initial_open")
        # Note that other Anymail normalized event properties are still available:
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36")

    def test_click_event(self):
        raw_events = [{"msys": {"track_event": {
            "type": "amp_click",
            "raw_rcpt_to": "recipient@example.com",
            "target_link_name": "Example Link Name",
            "target_link_url": "http://example.com",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=SparkPostTrackingWebhookView,
                                                      event=ANY, esp_name='SparkPost')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_3) AppleWebKit/537.36")
        self.assertEqual(event.click_url, "http://example.com")

    def test_amp_events(self):
        raw_events = [{"msys": {"track_event": {
            "type": "amp_open",
        }}}, {"msys": {"track_event": {
            "type": "amp_initial_open",
        }}}, {"msys": {"track_event": {
            "type": "amp_click",
        }}}]
        response = self.client.post('/anymail/sparkpost/tracking/',
                                    content_type='application/json', data=json.dumps(raw_events))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.tracking_handler.call_count, 3)
        events = [kwargs["event"] for (args, kwargs) in self.tracking_handler.call_args_list]
        self.assertEqual(events[0].event_type, "opened")
        self.assertEqual(events[1].event_type, "unknown")  # amp_initial_open is mapped to "unknown" by default
        self.assertEqual(events[2].event_type, "clicked")
