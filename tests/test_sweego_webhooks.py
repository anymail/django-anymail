import hashlib
import hmac
import json
from datetime import datetime, timezone

from django.test import override_settings, tag

from anymail.signals import AnymailTrackingEvent, EventType, RejectReason
from anymail.webhooks.sweego import SweegoTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


def sweego_sign_webhook(payload, secret):
    """Generate Sweego webhook signature"""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


@tag("sweego")
class SweegoWebhookTestCase(WebhookTestCase):
    def setUp(self):
        super().setUp()
        self.webhook_secret = "test_webhook_secret_12345"
        self.view = SweegoTrackingWebhookView()
        self.view.webhook_secret = self.webhook_secret

    def build_request(self, payload, content_type="application/json", **headers):
        """Build a Django request object for testing parse_events directly"""
        from django.test import RequestFactory

        factory = RequestFactory()
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        request = factory.post(
            "/anymail/sweego/tracking/",
            data=payload,
            content_type=content_type,
            **headers
        )
        return request

    def get_signed_request(self, payload):
        """Return a request with proper signature"""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        signature = sweego_sign_webhook(payload, self.webhook_secret)
        return self.build_request(
            payload=payload,
            content_type="application/json",
            HTTP_X_SWEEGO_SIGNATURE=signature,
        )


@tag("sweego")
class SweegoWebhookSecurityTestCase(SweegoWebhookTestCase):
    """Test Sweego webhook signature validation"""

    @override_settings(ANYMAIL_SWEEGO_WEBHOOK_SECRET="test_webhook_secret_12345")
    def test_verifies_correct_signature(self):
        payload = {
            "event_type": "delivered",
            "swg_uid": "01-f1491565-39b6-4160-bc45-f5b27a277ca9",
            "recipient": "test@example.com",
            "timestamp": "2024-09-02T08:45:08+00:00",
        }
        response = self.client.post(
            "/anymail/sweego/tracking/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_SWEEGO_SIGNATURE=sweego_sign_webhook(
                json.dumps(payload), "test_webhook_secret_12345"
            ),
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(ANYMAIL_SWEEGO_WEBHOOK_SECRET="test_webhook_secret_12345")
    def test_verifies_missing_signature(self):
        payload = {"event_type": "delivered", "swg_uid": "msg_test123"}
        response = self.client.post(
            "/anymail/sweego/tracking/",
            data=json.dumps(payload),
            content_type="application/json",
            # Missing signature header
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(ANYMAIL_SWEEGO_WEBHOOK_SECRET="test_webhook_secret_12345")
    def test_verifies_bad_signature(self):
        payload = {"event_type": "delivered", "swg_uid": "msg_test123"}
        response = self.client.post(
            "/anymail/sweego/tracking/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_SWEEGO_SIGNATURE="bad_signature",
        )
        self.assertEqual(response.status_code, 400)


@tag("sweego")
class SweegoDeliveryTestCase(SweegoWebhookTestCase):
    """Test Sweego delivery/tracking webhook events based on real Sweego payloads"""

    def test_email_sent_event(self):
        """Test email_sent event - email accepted by Sweego"""
        payload = {
            "event_type": "email_sent",
            "timestamp": "2024-09-02T08:45:05+00:00",
            "swg_uid": "01-47d3e283-1afb-4b9e-bd45-bfbf32ba251f",
            "event_id": "3e42ea83-f6a5-40cc-a1fa-8745669454",
            "channel": "email",
            "transaction_id": "861aad97-e4e8-4aaf-9322-1b64835760b9",
            "headers": {
                "x-campaign-type": "default",
                "x-swg-uid": "01-47d3ekdpj-1fdb-4bde-bsd5-bfbf32sdgf54f",
                "x-mailer": "Sweego",
                "x-campaign-id": "default",
                "x-client-id": "0c8cc711c85e45b79189456644166sj",
                "x-originating-ip": "185.255.28.207",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "default",
            "recipient": "mymail@mydomain.com",
            "domain_from": "send.sweego.io",
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, EventType.SENT)
        self.assertEqual(event.message_id, "01-47d3e283-1afb-4b9e-bd45-bfbf32ba251f")
        self.assertEqual(event.recipient, "mymail@mydomain.com")
        self.assertEqual(event.event_id, "3e42ea83-f6a5-40cc-a1fa-8745669454")
        self.assertEqual(
            event.timestamp,
            datetime(2024, 9, 2, 8, 45, 5, tzinfo=timezone.utc)
        )

    def test_delivered_event(self):
        """Test delivered event - email delivered to recipient's server"""
        payload = {
            "event_type": "delivered",
            "timestamp": "2024-09-02T08:45:08+00:00",
            "swg_uid": "01-f1491565-39b6-4160-bc45-f5b27a277ca9",
            "event_id": "7ebba9ce-3742-45fe-866a-a0699a5a8042",
            "channel": "email",
            "transaction_id": "861aad97-e4e8-4aaf-9322-1b64835760b9",
            "headers": {
                "x-campaign-type": "default",
                "x-mailer": "Sweego",
                "x-campaign-id": "default",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "default",
            "recipient": "myemail@mydomain.com",
            "domain_from": "send.sweego.io",
            "details": "ACCEPTED (250 2.0.0 OK)",
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, EventType.DELIVERED)
        self.assertEqual(event.message_id, "01-f1491565-39b6-4160-bc45-f5b27a277ca9")
        self.assertEqual(event.recipient, "myemail@mydomain.com")

    def test_soft_bounce_event(self):
        """Test soft-bounce event - temporary delivery failure"""
        payload = {
            "event_type": "soft-bounce",
            "timestamp": "2024-08-20T08:38:27+00:00",
            "swg_uid": "01-4f5qsdqsd3-b5e1-4012-a350-2e3d0d176ef1",
            "event_id": "82ebfgbfgb-0fgbfg-4190-967c-2e8484212f1c0f",
            "channel": "email",
            "transaction_id": "861aad97-e4e8-4aaf-9322-1b64835760b9",
            "headers": {
                "x-campaign-type": "default",
                "x-mailer": "Sweego",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "default",
            "recipient": "myemail@mydomain.com",
            "domain_from": "send.sweego.io",
            "details": "REJECTED[capacity] (452 User quota exceeded)",
            "response_code": 452,
            "status": None,
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.DEFERRED)
        self.assertEqual(event.reject_reason, RejectReason.BOUNCED)
        self.assertIn("REJECTED", event.mta_response)
        self.assertEqual(event.description, "SMTP 452")

    def test_hard_bounce_event(self):
        """Test hard_bounce event - permanent delivery failure"""
        payload = {
            "event_type": "hard_bounce",
            "timestamp": "2024-08-20T08:48:35+00:00",
            "swg_uid": "01-68d20f85-253e-4986-b7f0-0e4229df4d61",
            "event_id": "88eaff9a-5087-47d9-afdd-6eeaddfb11ae",
            "channel": "email",
            "transaction_id": "861aad97-e4e8-4aaf-9322-1b64835760b9",
            "headers": {
                "x-swg-uid": "01-68d20f85-253e-4986-b7f0-0e4229df4d61",
                "x-client-id": "myid",
                "x-campaign-type": "default",
                "x-mailer": "Sweego",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "default",
            "recipient": "invalid@domain.com",
            "domain_from": "my_domain.from",
            "details": "REJECTED[other] (550 Invalid Recipient)",
            "response_code": 550,
            "status": None,
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.BOUNCED)
        self.assertEqual(event.reject_reason, RejectReason.BOUNCED)
        self.assertIn("550 Invalid Recipient", event.mta_response)
        self.assertEqual(event.description, "SMTP 550")

    def test_list_unsub_event(self):
        """Test list_unsub event - unsubscribe via List-Unsubscribe header"""
        payload = {
            "event_type": "list_unsub",
            "timestamp": "2024-09-02T12:55:09.416380+00:00",
            "swg_uid": "02-5898484-484f2-841d-84ea-a33351589aabc0",
            "event_id": "0a190ab5-aad8-4874-9c32-0848484f8fc",
            "channel": "email",
            "transaction_id": "861aad97-e4e8-4aaf-9322-1b64835760b9",
            "headers": {
                "x-campaign-id": "42",
                "x-campaign-tags": "billing",
                "x-campaign-type": "transac",
                "x-client-id": "d6b1222eb484fb8f4g8d4fg8cd4",
            },
            "campaign_tags": "billing",
            "campaign_type": "transac",
            "campaign_id": "transac",
            "recipient": "myemail@mydomain.com",
            "domain_from": "sweego.mydomain.com",
            "one_click": False,
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.UNSUBSCRIBED)
        self.assertEqual(event.recipient, "myemail@mydomain.com")
        # campaign_tags as string should become list
        self.assertEqual(event.tags, ["billing"])

    def test_complaint_event(self):
        """Test complaint event - spam complaint (FBL)"""
        payload = {
            "event_type": "complaint",
            "timestamp": "2024-09-02T10:00:00+00:00",
            "swg_uid": "01-abc12345-1234-5678-abcd-1234567890ab",
            "event_id": "complaint-event-123",
            "channel": "email",
            "transaction_id": "861aad97-e4e8-4aaf-9322-1b64835760b9",
            "headers": {
                "x-campaign-type": "default",
                "x-mailer": "Sweego",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "default",
            "recipient": "complainer@example.com",
            "domain_from": "send.sweego.io",
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.COMPLAINED)
        self.assertEqual(event.reject_reason, RejectReason.SPAM)
        self.assertEqual(event.recipient, "complainer@example.com")

    def test_email_clicked_event(self):
        """Test email_clicked event - link clicked"""
        payload = {
            "event_type": "email_clicked",
            "timestamp": "2024-12-10T17:35:39",
            "swg_uid": "02-6e5dbe48-e6f4-4af3-8fb4-bf125e75776b",
            "event_id": "3e434a94-628c-4cbd-92b5-ed6be715aa2c",
            "channel": "email",
            "transaction_id": "568c5678-2d03-40f8-89e0-22ffb5cfe63d",
            "headers": {
                "x-mailer": "Sweego",
                "x-swg-uid": "02-6e5dbe48-e6f4-4af3-8fb4-bf125e75776b",
                "x-client-id": "f8367456332369298d050cf4bc83e058",
                "x-campaign-id": "fake_campaign",
                "x-campaign-type": "default",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "fake_campaign",
            "recipient": "random@domain.com",
            "domain_from": "my.domain.from",
            "subject": "Test webhook 2024-01-01",
            "click": {
                "ip_address": "1.2.3.4",
                "url": "https://google.com",
                "user_agent": "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0",
                "proxy": False,
            },
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.CLICKED)
        self.assertEqual(event.click_url, "https://google.com")
        self.assertEqual(
            event.user_agent,
            "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0"
        )
        self.assertEqual(event.recipient, "random@domain.com")

    def test_email_opened_event(self):
        """Test email_opened event - email opened (pixel tracking)"""
        payload = {
            "event_type": "email_opened",
            "timestamp": "2024-01-01T00:00:00",
            "swg_uid": "02-6e5dbe48-e6f4-4af3-8fb4-bf125e75776b",
            "event_id": "3e434a94-628c-4cbd-92b5-ed6be715aa2c",
            "channel": "email",
            "transaction_id": "568c5678-2d03-40f8-89e0-22ffb5cfe63d",
            "headers": {
                "x-mailer": "Sweego",
                "x-swg-uid": "02-6e5dbe48-e6f4-4af3-8fb4-bf125e75776b",
                "x-client-id": "f8367456332593298d050cf4bc83e0ab",
                "x-campaign-id": "fake_campaign",
                "x-campaign-type": "default",
            },
            "campaign_tags": None,
            "campaign_type": "default",
            "campaign_id": "fake_campaign",
            "recipient": "opener@example.com",
            "domain_from": "my_domain.from",
            "subject": "Test webhook",
            "open": {
                "ip_address": "1.2.3.4",
                "user_agent": "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0 (via ggpht.com GoogleImageProxy)",
                "proxy": True,
            },
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.OPENED)
        self.assertIn("GoogleImageProxy", event.user_agent)
        self.assertEqual(event.recipient, "opener@example.com")

    def test_metadata_extraction(self):
        """Test that metadata is extracted from X-Metadata-* headers"""
        payload = {
            "event_type": "delivered",
            "timestamp": "2024-09-02T08:45:08+00:00",
            "swg_uid": "01-test-uid",
            "event_id": "test-event-id",
            "channel": "email",
            "recipient": "recipient@example.com",
            "headers": {
                "x-mailer": "Sweego",
                "X-Metadata-user_id": "12345",
                "X-Metadata-order_id": "67890",
                "x-campaign-id": "default",
            },
            "campaign_tags": None,
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.metadata, {"user_id": "12345", "order_id": "67890"})

    def test_tags_as_array(self):
        """Test campaign_tags as array"""
        payload = {
            "event_type": "delivered",
            "timestamp": "2024-09-02T08:45:08+00:00",
            "swg_uid": "01-test-uid",
            "event_id": "test-event-id",
            "channel": "email",
            "recipient": "recipient@example.com",
            "headers": {},
            "campaign_tags": ["tag1", "tag2", "important"],
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.tags, ["tag1", "tag2", "important"])

    def test_tags_as_string(self):
        """Test campaign_tags as single string"""
        payload = {
            "event_type": "delivered",
            "timestamp": "2024-09-02T08:45:08+00:00",
            "swg_uid": "01-test-uid",
            "event_id": "test-event-id",
            "channel": "email",
            "recipient": "recipient@example.com",
            "headers": {},
            "campaign_tags": "billing",
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.tags, ["billing"])

    def test_batch_events(self):
        """Test handling multiple events in one webhook call"""
        payload = [
            {
                "event_type": "email_sent",
                "swg_uid": "msg_1",
                "recipient": "recipient1@example.com",
                "timestamp": "2024-09-02T08:45:05+00:00",
                "event_id": "evt_1",
                "headers": {},
                "campaign_tags": None,
            },
            {
                "event_type": "delivered",
                "swg_uid": "msg_2",
                "recipient": "recipient2@example.com",
                "timestamp": "2024-09-02T08:45:08+00:00",
                "event_id": "evt_2",
                "headers": {},
                "campaign_tags": None,
            },
        ]
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, EventType.SENT)
        self.assertEqual(events[0].message_id, "msg_1")
        self.assertEqual(events[1].event_type, EventType.DELIVERED)
        self.assertEqual(events[1].message_id, "msg_2")

    def test_unknown_event(self):
        """Test handling of unknown event types"""
        payload = {
            "event_type": "unknown_event_type",
            "swg_uid": "msg_abc123",
            "recipient": "recipient@example.com",
            "timestamp": "2024-09-02T08:45:05+00:00",
            "event_id": "evt_unknown",
            "headers": {},
            "campaign_tags": None,
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.UNKNOWN)
        self.assertEqual(event.message_id, "msg_abc123")

    def test_proxy_open_detection(self):
        """Test that proxy field is available in esp_event for proxy opens"""
        payload = {
            "event_type": "email_opened",
            "timestamp": "2024-01-01T00:00:00",
            "swg_uid": "02-proxy-test",
            "event_id": "proxy-event-id",
            "channel": "email",
            "recipient": "opener@example.com",
            "headers": {},
            "campaign_tags": None,
            "open": {
                "ip_address": "66.249.84.1",
                "user_agent": "GoogleImageProxy",
                "proxy": True,
            },
        }
        request = self.get_signed_request(payload)
        events = self.view.parse_events(request)
        event = events[0]
        self.assertEqual(event.event_type, EventType.OPENED)
        # Proxy info available in esp_event for advanced processing
        self.assertTrue(event.esp_event["open"]["proxy"])


# =============================================================================
# Inbound Webhook Tests
# =============================================================================


@tag("sweego")
class SweegoInboundWebhookTestCase(WebhookTestCase):
    """Test Sweego inbound email webhook handling"""

    def setUp(self):
        super().setUp()
        self.webhook_secret = "test_inbound_webhook_secret_12345"

    def build_request(self, payload, content_type="application/json", **headers):
        """Build a Django request object for testing parse_events directly"""
        from django.test import RequestFactory
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        factory = RequestFactory()
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        request = factory.post(
            "/anymail/sweego/inbound/",
            data=payload,
            content_type=content_type,
            **headers
        )
        return request

    def get_signed_request(self, payload):
        """Return a request with proper signature"""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        signature = sweego_sign_webhook(payload, self.webhook_secret)
        return self.build_request(
            payload=payload,
            content_type="application/json",
            HTTP_X_SWEEGO_SIGNATURE=signature,
        )


@tag("sweego")
class SweegoInboundSecurityTestCase(SweegoInboundWebhookTestCase):
    """Test Sweego inbound webhook signature validation"""

    @override_settings(ANYMAIL_SWEEGO_WEBHOOK_SECRET="test_inbound_webhook_secret_12345")
    def test_verifies_correct_signature(self):
        payload = {
            "event_type": "email_inbound",
            "swg_uid": "test-inbound-msg-uuid-aaaa-bbbb-aaaaaaaabbbb",
            "from_": {"email": "sender@example.com", "name": "Sender"},
            "to": [{"email": "recipient@inbound.example.com", "name": ""}],
            "subject": "Test inbound",
            "text": "Hello world",
            "timestamp": "2024-12-19T13:49:28.849638+00:00",
            "event_id": "10c072f1-7821-4f30-9574-f13e3890701a",
        }
        response = self.client.post(
            "/anymail/sweego/inbound/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_SWEEGO_SIGNATURE=sweego_sign_webhook(
                json.dumps(payload), "test_inbound_webhook_secret_12345"
            ),
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(ANYMAIL_SWEEGO_WEBHOOK_SECRET="test_inbound_webhook_secret_12345")
    def test_verifies_missing_signature(self):
        payload = {
            "event_type": "email_inbound",
            "swg_uid": "msg_test123",
            "from_": {"email": "sender@example.com", "name": ""},
            "to": [{"email": "recipient@example.com", "name": ""}],
        }
        response = self.client.post(
            "/anymail/sweego/inbound/",
            data=json.dumps(payload),
            content_type="application/json",
            # Missing signature header
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(ANYMAIL_SWEEGO_WEBHOOK_SECRET="test_inbound_webhook_secret_12345")
    def test_verifies_bad_signature(self):
        payload = {
            "event_type": "email_inbound",
            "swg_uid": "msg_test123",
            "from_": {"email": "sender@example.com", "name": ""},
            "to": [{"email": "recipient@example.com", "name": ""}],
        }
        response = self.client.post(
            "/anymail/sweego/inbound/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_SWEEGO_SIGNATURE="bad_signature",
        )
        self.assertEqual(response.status_code, 400)


@tag("sweego")
class SweegoInboundEventTestCase(SweegoInboundWebhookTestCase):
    """Test Sweego inbound event parsing based on real Sweego payloads"""

    def test_basic_inbound_email(self):
        """Test basic inbound email parsing - based on Sweego documentation"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T13:49:28.849638+00:00",
            "swg_uid": "test-inbound-msg-uuid-aaaa-bbbb-aaaaaaaabbbb",
            "from_": {
                "email": "johndoe@swee.go",
                "name": "John Doe"
            },
            "to": [
                {
                    "email": "parse@invoices.sweego.io",
                    "name": ""
                }
            ],
            "cc": [],
            "text": "Invoice 42",
            "html": None,
            "subject": "Invoice 42",
            "inbound_domain": "invoices.sweego.io",
            "event_id": "10c072f1-7821-4f30-9574-f13e3890701a",
            "channel": "email",
            "transaction_id": None
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.event_type, EventType.INBOUND)
        self.assertEqual(event.event_id, "10c072f1-7821-4f30-9574-f13e3890701a")
        self.assertEqual(
            event.timestamp,
            datetime(2024, 12, 19, 13, 49, 28, 849638, tzinfo=timezone.utc)
        )

        # Check message fields
        message = event.message
        self.assertEqual(message["Subject"], "Invoice 42")
        self.assertIn("johndoe@swee.go", message["From"])
        self.assertIn("John Doe", message["From"])
        self.assertIn("parse@invoices.sweego.io", message["To"])

        # Check body
        self.assertEqual(message.text, "Invoice 42")
        self.assertIsNone(message.html)

        # Check envelope
        self.assertEqual(message.envelope_sender, "johndoe@swee.go")
        self.assertEqual(message.envelope_recipient, "parse@invoices.sweego.io")

    def test_inbound_with_html_body(self):
        """Test inbound email with HTML body"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T14:00:00+00:00",
            "swg_uid": "04-html-test-uid",
            "from_": {"email": "sender@example.com", "name": "HTML Sender"},
            "to": [{"email": "inbox@inbound.example.com", "name": ""}],
            "cc": [],
            "text": "Plain text version",
            "html": "<html><body><h1>Hello</h1><p>This is HTML content</p></body></html>",
            "subject": "HTML Email Test",
            "inbound_domain": "inbound.example.com",
            "event_id": "html-event-id",
            "channel": "email",
            "transaction_id": None
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message
        self.assertEqual(message.text, "Plain text version")
        self.assertIn("<h1>Hello</h1>", message.html)
        self.assertEqual(message["Subject"], "HTML Email Test")

    def test_inbound_with_cc_recipients(self):
        """Test inbound email with CC recipients"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T14:00:00+00:00",
            "swg_uid": "04-cc-test-uid",
            "from_": {"email": "sender@example.com", "name": "Sender"},
            "to": [
                {"email": "primary@inbound.example.com", "name": "Primary"}
            ],
            "cc": [
                {"email": "cc1@example.com", "name": "CC One"},
                {"email": "cc2@example.com", "name": ""}
            ],
            "text": "Message with CC",
            "html": None,
            "subject": "CC Test",
            "inbound_domain": "inbound.example.com",
            "event_id": "cc-event-id",
            "channel": "email",
            "transaction_id": None
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message
        self.assertIn("Primary", message["To"])
        self.assertIn("cc1@example.com", message["Cc"])
        self.assertIn("CC One", message["Cc"])
        self.assertIn("cc2@example.com", message["Cc"])

    def test_inbound_with_multiple_to_recipients(self):
        """Test inbound email with multiple To recipients"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T14:00:00+00:00",
            "swg_uid": "04-multi-to-uid",
            "from_": {"email": "sender@example.com", "name": ""},
            "to": [
                {"email": "first@inbound.example.com", "name": "First"},
                {"email": "second@inbound.example.com", "name": "Second"}
            ],
            "cc": [],
            "text": "Multiple recipients",
            "html": None,
            "subject": "Multi To Test",
            "inbound_domain": "inbound.example.com",
            "event_id": "multi-to-event-id",
            "channel": "email",
            "transaction_id": None
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message
        self.assertIn("first@inbound.example.com", message["To"])
        self.assertIn("second@inbound.example.com", message["To"])
        # envelope_recipient should be the first To address
        self.assertEqual(message.envelope_recipient, "first@inbound.example.com")

    def test_inbound_with_attachments(self):
        """Test inbound email with lazy-loaded attachments"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView
        from unittest.mock import patch, Mock

        # Real Sweego webhook payload format - only metadata, no content
        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T14:00:00+00:00",
            "swg_uid": "04-attachment-uid",
            "from_": {"email": "sender@example.com", "name": "Sender"},
            "to": [{"email": "inbox@inbound.example.com", "name": ""}],
            "cc": [],
            "text": "Please see attachment",
            "html": None,
            "subject": "Document Attached",
            "inbound_domain": "inbound.example.com",
            "event_id": "attachment-event-id",
            "channel": "email",
            "transaction_id": None,
            "attachments": [
                {
                    "uuid": "test-attach-uuid-1111-2222-111111112222",
                    "name": "document.txt",
                    "content_type": "text/plain",
                    "size": 23
                }
            ]
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        view.api_key = "test-api-key"
        view.client_uuid = "test-client-uuid-aaaa-bbbb-aaaaaaaaabbbb"
        view.api_url = "https://api.sweego.io"
        
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message

        # Check attachments via the message API
        attachments = message.attachments
        self.assertEqual(len(attachments), 1)
        att = attachments[0]
        self.assertEqual(att.get_filename(), "document.txt")
        self.assertEqual(att.get_content_type(), "text/plain")
        
        # Check that attachment is lazy (not fetched yet)
        self.assertFalse(att._fetched)
        
        # Mock the API call to fetch attachment content
        mock_response = Mock()
        mock_response.content = b"Test attachment content"
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response) as mock_get:
            # Access content triggers lazy load
            content = att.get_content_bytes()
            
            # Verify API was called correctly
            mock_get.assert_called_once_with(
                "https://api.sweego.io/clients/test-client-uuid-aaaa-bbbb-aaaaaaaaabbbb/domains/inbound/attachments/test-attach-uuid-1111-2222-111111112222",
                headers={
                    "Api-Key": "test-api-key",
                    "Accept": "application/octet-stream",
                },
                timeout=30,
            )
            
            # Verify content is correct
            self.assertEqual(content, b"Test attachment content")
            
            # Verify attachment is now fetched
            self.assertTrue(att._fetched)
            
            # Second access should not trigger another API call
            content2 = att.get_content_bytes()
            self.assertEqual(content2, b"Test attachment content")
            mock_get.assert_called_once()  # Still only one call

    def test_inbound_attachments_without_api_credentials(self):
        """Test that attachments are skipped if API credentials are not configured"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T14:00:00+00:00",
            "swg_uid": "04-attachment-uid",
            "from_": {"email": "sender@example.com", "name": "Sender"},
            "to": [{"email": "inbox@inbound.example.com", "name": ""}],
            "cc": [],
            "text": "Please see attachment",
            "html": None,
            "subject": "Document Attached",
            "inbound_domain": "inbound.example.com",
            "event_id": "attachment-event-id",
            "channel": "email",
            "transaction_id": None,
            "attachments": [
                {
                    "uuid": "test-attach-uuid-3333-4444-333333334444",
                    "name": "document.txt",
                    "content_type": "text/plain",
                    "size": 23
                }
            ]
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        # Deliberately not setting api_key and client_uuid
        
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message

        # Without API credentials, attachments should not be created
        attachments = message.attachments
        self.assertEqual(len(attachments), 0)

    def test_inbound_ignores_non_inbound_events(self):
        """Test that non-inbound events are filtered out"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = [
            {
                "event_type": "email_inbound",
                "timestamp": "2024-12-19T14:00:00+00:00",
                "swg_uid": "04-inbound-uid",
                "from_": {"email": "sender@example.com", "name": ""},
                "to": [{"email": "inbox@inbound.example.com", "name": ""}],
                "cc": [],
                "text": "Inbound message",
                "html": None,
                "subject": "Inbound",
                "event_id": "inbound-id",
            },
            {
                # This is a tracking event, should be ignored
                "event_type": "delivered",
                "timestamp": "2024-12-19T14:00:00+00:00",
                "swg_uid": "01-tracking-uid",
                "recipient": "recipient@example.com",
                "event_id": "tracking-id",
            }
        ]

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        # Only inbound event should be returned
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EventType.INBOUND)
        self.assertEqual(events[0].event_id, "inbound-id")

    def test_inbound_minimal_payload(self):
        """Test inbound with minimal required fields"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "from_": {"email": "sender@example.com", "name": ""},
            "to": [{"email": "inbox@example.com", "name": ""}],
            "text": "Minimal content",
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message
        self.assertEqual(message.text, "Minimal content")
        self.assertEqual(message.envelope_sender, "sender@example.com")

    def test_inbound_spam_fields_are_none(self):
        """Test that spam detection fields are None (not provided by Sweego)"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = {
            "event_type": "email_inbound",
            "timestamp": "2024-12-19T14:00:00+00:00",
            "swg_uid": "04-spam-test-uid",
            "from_": {"email": "sender@example.com", "name": ""},
            "to": [{"email": "inbox@example.com", "name": ""}],
            "text": "Test message",
            "event_id": "spam-test-id",
        }

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 1)
        message = events[0].message
        self.assertIsNone(message.spam_detected)
        self.assertIsNone(message.spam_score)

    def test_inbound_batch_events(self):
        """Test handling multiple inbound events in a single webhook call"""
        from anymail.webhooks.sweego import SweegoInboundWebhookView

        payload = [
            {
                "event_type": "email_inbound",
                "timestamp": "2024-12-19T14:00:00+00:00",
                "swg_uid": "04-first-uid",
                "from_": {"email": "first@example.com", "name": ""},
                "to": [{"email": "inbox@example.com", "name": ""}],
                "text": "First message",
                "event_id": "first-event-id",
            },
            {
                "event_type": "email_inbound",
                "timestamp": "2024-12-19T14:01:00+00:00",
                "swg_uid": "04-second-uid",
                "from_": {"email": "second@example.com", "name": ""},
                "to": [{"email": "inbox@example.com", "name": ""}],
                "text": "Second message",
                "event_id": "second-event-id",
            }
        ]

        view = SweegoInboundWebhookView()
        view.webhook_secret = self.webhook_secret
        request = self.get_signed_request(payload)
        events = view.parse_events(request)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_id, "first-event-id")
        self.assertEqual(events[0].message.envelope_sender, "first@example.com")
        self.assertEqual(events[1].event_id, "second-event-id")
        self.assertEqual(events[1].message.envelope_sender, "second@example.com")
