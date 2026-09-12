import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import ANY

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings, tag

from anymail.exceptions import AnymailConfigurationError
from anymail.signals import AnymailTrackingEvent, RejectReason
from anymail.webhooks.mailersend import MailerSendTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase

TEST_WEBHOOK_SIGNING_SECRET = "TEST_WEBHOOK_SIGNING_SECRET"


def mailersend_signature(data, secret):
    """Generate a MailerSend webhook signature for data with secret"""
    # https://developers.mailersend.com/api/v1/webhooks.html#security
    return hmac.new(
        key=secret.encode("ascii"),
        msg=data,
        digestmod=hashlib.sha256,
    ).hexdigest()


class MailerSendWebhookTestCase(WebhookTestCase):
    def client_post_signed(self, url, json_data, secret=TEST_WEBHOOK_SIGNING_SECRET):
        """Return self.client.post(url, serialized json_data) signed with secret"""
        # MailerSend for some reason backslash-escapes all forward slashes ("/")
        # in its webhook payloads ("https:\/\/www..."). This is unnecessary, but
        # harmless. We emulate it here to make sure it won't cause problems.
        data = json.dumps(json_data).replace("/", "\\/").encode("ascii")
        signature = mailersend_signature(data, secret)
        return self.client.post(
            url,
            content_type="application/json",
            data=data,
            headers={"Signature": signature},
        )


@tag("mailersend")
class MailerSendWebhookSettingsTestCase(MailerSendWebhookTestCase):
    def test_requires_signing_secret(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "MAILERSEND_SIGNING_SECRET"
        ):
            self.client_post_signed(
                "/anymail/mailersend/tracking/", {"data": {"type": "sent"}}
            )

    @override_settings(
        ANYMAIL={
            "MAILERSEND_SIGNING_SECRET": "webhook secret",
            "MAILERSEND_INBOUND_SECRET": "inbound secret",
        }
    )
    def test_inbound_secret_is_different(self):
        response = self.client_post_signed(
            "/anymail/mailersend/tracking/",
            {"data": {"type": "sent"}},
            secret="webhook secret",
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(ANYMAIL_MAILERSEND_SIGNING_SECRET="settings secret")
    def test_signing_secret_view_params(self):
        """Webhook signing secret can be provided as a view param"""
        view = MailerSendTrackingWebhookView.as_view(signing_secret="view-level secret")
        view_instance = view.view_class(**view.view_initkwargs)
        self.assertEqual(view_instance.signing_secret, b"view-level secret")


@tag("mailersend")
@override_settings(ANYMAIL_MAILERSEND_SIGNING_SECRET=TEST_WEBHOOK_SIGNING_SECRET)
class MailerSendWebhookSecurityTestCase(
    MailerSendWebhookTestCase, WebhookBasicAuthTestCase
):
    should_warn_if_no_auth = False  # because we check webhook signature

    def call_webhook(self):
        return self.client_post_signed(
            "/anymail/mailersend/tracking/",
            {"data": {"type": "sent"}},
            secret=TEST_WEBHOOK_SIGNING_SECRET,
        )

    # Additional tests are in WebhookBasicAuthTestCase

    def test_verifies_correct_signature(self):
        response = self.client_post_signed(
            "/anymail/mailersend/tracking/",
            {"data": {"type": "sent"}},
            secret=TEST_WEBHOOK_SIGNING_SECRET,
        )
        self.assertEqual(response.status_code, 200)

    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/mailersend/tracking/",
            content_type="application/json",
            data=json.dumps({"data": {"type": "sent"}}),
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_bad_signature(self):
        # This also verifies that the error log references the correct setting to check.
        with self.assertLogs() as logs:
            response = self.client_post_signed(
                "/anymail/mailersend/tracking/",
                {"data": {"type": "sent"}},
                secret="wrong signing key",
            )
        # SuspiciousOperation causes 400 response (even in test client):
        self.assertEqual(response.status_code, 400)
        self.assertIn("check Anymail MAILERSEND_SIGNING_SECRET", logs.output[0])


@tag("mailersend")
@override_settings(ANYMAIL_MAILERSEND_SIGNING_SECRET=TEST_WEBHOOK_SIGNING_SECRET)
class MailerSendV1TrackingTestCase(MailerSendWebhookTestCase):
    """Test cases for legacy webhook payloads.

    These tests can be removed after v1 webhooks are retired in 12/2026.
    """

    def test_sent_event(self):
        # This is an actual, complete (sanitized) "sent" event as received from
        # MailerSend. (For brevity, later tests omit several payload fields that
        # Anymail doesn't use.)
        raw_event = {
            "type": "activity.sent",
            "domain_id": "[domain-id-redacted]",
            "created_at": "2023-02-27T21:09:49.520507Z",
            "webhook_id": "[webhook-id-redacted]",
            "url": "https://test.anymail.dev/anymail/mailersend/tracking/",
            "data": {
                "object": "activity",
                "id": "63fd1c1d31b9c750540fe85c",
                "type": "sent",
                "created_at": "2023-02-27T21:09:49.506000Z",
                "email": {
                    "object": "email",
                    "id": "63fd1c1de225707fa905f0a8",
                    "created_at": "2023-02-27T21:09:49.141000Z",
                    "from": "sender@mailersend.anymail.dev",
                    "subject": "Test webhooks",
                    "status": "sent",
                    "tags": ["tag1", "Tag 2"],
                    "message": {
                        "object": "message",
                        "id": "63fd1c1d5f010335ed07066b",
                        "created_at": "2023-02-27T21:09:49.061000Z",
                    },
                    "recipient": {
                        "object": "recipient",
                        "id": "63f3bb1965d98aa98c07d6b7",
                        "email": "recipient@example.com",
                        "created_at": "2023-02-20T18:25:29.162000Z",
                    },
                },
                "morph": None,
                "template_id": "",
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "sent")
        # event.timestamp comes from data.created_at:
        self.assertEqual(
            event.timestamp,
            # "2023-02-27T21:09:49.506000Z"
            datetime(2023, 2, 27, 21, 9, 49, microsecond=506000, tzinfo=timezone.utc),
        )
        # event.message_id matches the message.anymail_status.message_id when the
        # message was sent. It comes from data.email.message.id:
        self.assertEqual(event.message_id, "63fd1c1d5f010335ed07066b")
        # event.event_id is unique for each event, and comes from data.id:
        self.assertEqual(event.event_id, "63fd1c1d31b9c750540fe85c")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["tag1", "Tag 2"])
        self.assertEqual(event.metadata, {})  # MailerSend doesn't support metadata
        self.assertEqual(event.esp_event, raw_event)

        # You can construct the sent Message-ID header (which is different from the
        # event.message_id, and is unique per recipient) from esp_event.data.email.id:
        sent_message_id = f"<{event.esp_event['data']['email']['id']}@mailersend.net>"
        self.assertEqual(sent_message_id, "<63fd1c1de225707fa905f0a8@mailersend.net>")

    def test_delivered_event(self):
        raw_event = {
            "type": "activity.delivered",
            "data": {
                "object": "activity",
                "id": "63fd1c1fcfbe46145d003a7b",
                "type": "delivered",
                "created_at": "2023-02-27T21:09:51.865000Z",
                "email": {
                    "status": "delivered",
                    "message": {
                        "id": "63fd1c1d5f010335ed07066b",
                    },
                    "recipient": {
                        "email": "recipient@example.com",
                    },
                },
                "morph": None,
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(
            event.timestamp,
            # "2023-02-27T21:09:51.865000Z"
            datetime(2023, 2, 27, 21, 9, 51, microsecond=865000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.message_id, "63fd1c1d5f010335ed07066b")
        self.assertEqual(event.event_id, "63fd1c1fcfbe46145d003a7b")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_hard_bounced_event(self):
        raw_event = {
            "type": "activity.hard_bounced",
            "data": {
                "id": "63fd251d5c00f8e52001fce6",
                "type": "hard_bounced",
                "created_at": "2023-02-27T21:48:13.593000Z",
                "email": {
                    "status": "rejected",
                    "message": {
                        "id": "63fd25194d5edba3da09e044",
                    },
                    "recipient": {
                        "email": "invalid@example.com",
                    },
                },
                "morph": {
                    "object": "recipient_bounce",
                    "reason": "Host or domain name not found",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.recipient, "invalid@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description, "Host or domain name not found")
        self.assertIsNone(event.mta_response)  # raw MTA info not provided

    def test_soft_bounced_event(self):
        raw_event = {
            "type": "activity.soft_bounced",
            "data": {
                "object": "activity",
                "id": "62f114f8165fe0d8db0288e5",
                "type": "soft_bounced",
                "created_at": "2022-08-08T13:51:52.747000Z",
                "email": {
                    "status": "rejected",
                    "tags": None,
                    "message": {
                        "id": "62fb66bef54a112e920b5493",
                    },
                    "recipient": {
                        "email": "notauser@example.com",
                    },
                },
                "morph": {
                    "object": "recipient_bounce",
                    "reason": "Unknown reason",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.recipient, "notauser@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description, "Unknown reason")
        self.assertIsNone(event.mta_response)  # raw MTA info not provided

    def test_spam_complaint_event(self):
        raw_event = {
            "type": "activity.spam_complaint",
            "data": {
                "id": "62f114f8165fe0d8db0288e5",
                "type": "spam_complaint",
                "created_at": "2022-08-08T13:51:52.747000Z",
                "email": {
                    "status": "delivered",
                    "message": {
                        "id": "62fb66bef54a112e920b5493",
                    },
                    "recipient": {
                        "email": "recipient@example.com",
                    },
                },
                "morph": {
                    "object": "spam_complaint",
                    "reason": None,
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_unsubscribed_event(self):
        raw_event = {
            "type": "activity.unsubscribed",
            "data": {
                "id": "63fd21c23f2bdd360e07d6b2",
                "type": "unsubscribed",
                "created_at": "2023-02-27T21:33:54.791000Z",
                "email": {
                    "status": "delivered",
                    "message": {
                        "id": "63fd1c1d5f010335ed07066b",
                    },
                    "recipient": {
                        "email": "recipient@example.com",
                    },
                },
                "morph": {
                    "object": "recipient_unsubscribe",
                    "reason": "option_3",
                    "readable_reason": "I get too many emails",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "unsubscribed")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.description, "I get too many emails")

    def test_opened_event(self):
        raw_event = {
            "type": "activity.opened",
            "data": {
                "id": "63fd1e05532bd6cc700a793b",
                "type": "opened",
                "created_at": "2023-02-27T21:17:57.025000Z",
                "email": {
                    "status": "delivered",
                    "message": {
                        "id": "63fd1c1d5f010335ed07066b",
                    },
                    "recipient": {
                        "email": "recipient@example.com",
                    },
                },
                "morph": {
                    "object": "open",
                    "id": "63fd1e05532bd6cc700a793a",
                    "created_at": "2023-02-27T21:17:57.018000Z",
                    "ip": "10.10.10.10",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_clicked_event(self):
        raw_event = {
            "type": "activity.clicked",
            "data": {
                "id": "63fd1d23afa3c770b00da7d3",
                "type": "clicked",
                "created_at": "2023-02-27T21:14:11.691000Z",
                "email": {
                    "status": "delivered",
                    "message": {
                        "id": "63fd1c1d5f010335ed07066b",
                    },
                    "recipient": {
                        "email": "recipient@example.com",
                    },
                },
                "morph": {
                    "object": "click",
                    "id": "63fd1d23afa3c770b00da7d2",
                    "created_at": "2023-02-27T21:14:11.679000Z",
                    "ip": "10.10.10.10",
                    "url": "https://example.com/test",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.click_url, "https://example.com/test")


@tag("mailersend")
@override_settings(ANYMAIL_MAILERSEND_SIGNING_SECRET=TEST_WEBHOOK_SIGNING_SECRET)
class MailerSendTrackingTestCase(MailerSendWebhookTestCase):
    """Test cases for MailerSend's v2 webhook format."""

    # https://developers.mailersend.com/api/v1/account/webhooks#payload-example

    def get_tracking_event(self):
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailerSendTrackingWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        return kwargs["event"]

    def test_webhook_ping(self):
        # Should ignore "ping" MailerSend generates during webhook setup
        response = self.client_post_signed(
            "/anymail/mailersend/tracking/",
            {
                "type": "webhook.test",
                "message": "This is a ping test message",
                "created_at": "2026-09-12T18:39:57.604840Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.tracking_handler.call_count, 0)

    def test_sent_event(self):
        # This is an actual, complete (sanitized) "sent" event as received from
        # MailerSend. (For brevity, later tests omit several payload fields that
        # Anymail doesn't use.)
        raw_event = {
            "type": "activity.sent",
            "created_at": "2026-09-12T18:42:56.000000Z",
            "data": {
                "id": "6aa59d304ab3f14ef03ccf50",
                "domain_id": "[domain-id-redacted]",
                "message_id": "6aa59d2fbf35297925087058",
                "email_id": "6aa59d3037403a10c4d4d18e",
                "type": "sent",
                "subject": "Test webhooks",
                "recipient": "recipient@example.com",
                "tags": ["tag1", "Tag 2"],
                "meta": [],
            },
            "webhook_id": "[webhook-id-redacted]",
        }

        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "sent")
        # event.timestamp comes from data.created_at:
        self.assertEqual(
            event.timestamp,
            # "2026-09-12T18:42:56.000000Z"
            datetime(2026, 9, 12, 18, 42, 56, tzinfo=timezone.utc),
        )
        # event.message_id matches the message.anymail_status.message_id when the
        # message was sent. It comes from data.message_id:
        self.assertEqual(event.message_id, "6aa59d2fbf35297925087058")
        # event.event_id is unique for each event, and comes from data.id:
        self.assertEqual(event.event_id, "6aa59d304ab3f14ef03ccf50")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["tag1", "Tag 2"])
        self.assertEqual(event.metadata, {})  # MailerSend doesn't support metadata
        self.assertEqual(event.esp_event, raw_event)

        # You can construct the sent Message-ID header (which is different from the
        # event.data.message_id, and is unique per recipient) from esp_event.data.email_id:
        sent_message_id = f"<{event.esp_event['data']['email_id']}@mailersend.net>"
        self.assertEqual(sent_message_id, "<6aa59d3037403a10c4d4d18e@mailersend.net>")

    def test_delivered_event(self):
        raw_event = {
            "type": "activity.delivered",
            "created_at": "2026-09-12T18:43:00.000000Z",
            "data": {
                "id": "6aa59d4a531434d718ec48a0",
                "message_id": "6aa59d2fbf35297925087058",
                "email_id": "6aa59d3037403a10c4d4d18e",
                "type": "delivered",
                "recipient": "recipient@example.com",
                "meta": [],
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")

    def test_hard_bounced_event(self):
        raw_event = {
            "type": "activity.hard_bounced",
            "created_at": "2025-08-05T21:24:02.000000Z",
            "data": {
                "id": "6892766a5b66e2daf3dc9158",
                "message_id": "6892766ae78995a317577aa1",
                "email_id": "6892766a8d52ba62543d5e71",
                "type": "hard_bounced",
                "recipient": "invalid@example.com",
                "meta": {
                    "bounce_reason": "Host or domain name not found",
                    "bounce_code": 550,
                    "bounce_type": "hard",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.recipient, "invalid@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description, "Host or domain name not found")
        self.assertEqual(event.mta_response, "550")  # bounce_code

    def test_soft_bounced_event(self):
        raw_event = {
            "type": "activity.soft_bounced",
            "created_at": "2025-08-05T21:24:02.000000Z",
            "data": {
                "id": "6892766a5b66e2daf3dc9157",
                "message_id": "6892766ae78995a317577aa1",
                "email_id": "6892766a8d52ba62543d5e71",
                "type": "soft_bounced",
                "recipient": "notauser@example.com",
                "meta": {
                    "bounce_reason": "Mailbox full",
                    "bounce_code": 452,
                    "bounce_type": "soft",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.recipient, "notauser@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description, "Mailbox full")
        self.assertEqual(event.mta_response, "452")

    def test_deferred_event(self):
        raw_event = {
            "type": "activity.deferred",
            "created_at": "2025-08-05T21:23:58.000000Z",
            "data": {
                "id": "6892766a5b66e2daf3dc9159",
                "message_id": "6892766ae78995a317577aa1",
                "email_id": "6892766a8d52ba62543d5e71",
                "type": "deferred",
                "recipient": "recipient@example.com",
                "meta": [],
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertIsNone(event.mta_response)

    def test_spam_complaint_event(self):
        raw_event = {
            "type": "activity.spam_complaint",
            "created_at": "2025-08-05T21:36:40.000000Z",
            "data": {
                "id": "6892766a5b66e2daf3dc915d",
                "message_id": "6892766ae78995a317577aa1",
                "email_id": "6892766a8d52ba62543d5e71",
                "type": "spam_complaints",
                "recipient": "recipient@example.com",
                "meta": [],
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.reject_reason, RejectReason.SPAM)

    def test_unsubscribed_event(self):
        raw_event = {
            "type": "activity.unsubscribed",
            "created_at": "2025-08-05T21:35:20.000000Z",
            "data": {
                "id": "6892766a5b66e2daf3dc915c",
                "message_id": "6892766ae78995a317577aa1",
                "email_id": "6892766a8d52ba62543d5e71",
                "type": "unsubscribed",
                "recipient": "recipient@example.com",
                "tags": ["test", "test2"],
                "meta": {"unsubscribe_reason": "NO_LONGER_WANT"},
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "unsubscribed")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.description, "NO_LONGER_WANT")
        self.assertEqual(event.reject_reason, RejectReason.UNSUBSCRIBED)

    def test_opened_event(self):
        raw_event = {
            "type": "activity.opened",
            "created_at": "2026-09-12T18:45:01.000000Z",
            "data": {
                "id": "6aa59dad05e8ec525fe6ef95",
                "message_id": "6aa59d2fbf35297925087058",
                "email_id": "6aa59d3037403a10c4d4d18e",
                "type": "opened",
                "recipient": "recipient@example.com",
                "meta": {
                    "ip": "333.1.2.3",
                    "country": "US",
                    "user_agent": "Mozilla/5.0 (via ggpht.com GoogleImageProxy)",
                    "device_type": "webmail",
                    "browser": "Gmail Image Proxy",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(
            event.user_agent, "Mozilla/5.0 (via ggpht.com GoogleImageProxy)"
        )

    def test_opened_unique_event(self):
        # opened_unique is normalized to opened
        raw_event = {
            "type": "activity.opened_unique",
            "data": {
                "type": "opened",
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "opened")

    def test_clicked_event(self):
        raw_event = {
            "type": "activity.clicked",
            "created_at": "2026-09-12T18:45:05.000000Z",
            "data": {
                "id": "6aa59db1c8ba039cd6d68435",
                "message_id": "6aa59d2fbf35297925087058",
                "email_id": "6aa59d3037403a10c4d4d18e",
                "type": "clicked",
                "recipient": "recipient@example.com",
                "meta": {
                    "ip": "333.1.2.3",
                    "country": "US",
                    "user_agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36",
                    "device_type": "desktop",
                    "browser": "Chrome",
                    "url": "https://example.com/test",
                },
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.click_url, "https://example.com/test")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Macintosh) AppleWebKit/537.36")

    def test_clicked_unique_event(self):
        # clicked_unique is normalized to clicked
        raw_event = {
            "type": "activity.clicked_unique",
            "data": {
                "type": "clicked",
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "clicked")

    def test_suppressed_event(self):
        raw_event = {
            "type": "activity.suppressed",
            "created_at": "2025-08-05T21:23:54.000000Z",
            "data": {
                "id": "6892766a5b66e2daf3dc915f",
                "domain_id": "yv69oxl5kl785kw2",
                "message_id": "6892766ae78995a317577aa1",
                "email_id": "6892766a8d52ba62543d5e71",
                "type": "suppressed",
                "subject": "Test email",
                "recipient": "recipient@example.com",
                "meta": {"suppression_reason": "on_hold"},
            },
        }
        response = self.client_post_signed("/anymail/mailersend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        event = self.get_tracking_event()
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.reject_reason, RejectReason.BLOCKED)

    def test_misconfigured_inbound(self):
        errmsg = (
            "You seem to have set MailerSend's *inbound* route endpoint"
            " to Anymail's MailerSend *activity tracking* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client_post_signed(
                "/anymail/mailersend/tracking/",
                {
                    "type": "inbound.message",
                    "data": {"object": "message", "raw": "..."},
                },
            )
