import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import ANY

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings, tag

from anymail.exceptions import AnymailConfigurationError
from anymail.signals import AnymailTrackingEvent
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
            url, content_type="application/json", data=data, HTTP_SIGNATURE=signature
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
class MailerSendTestCase(MailerSendWebhookTestCase):
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
