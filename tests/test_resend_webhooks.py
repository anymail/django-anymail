import base64
import json
from datetime import datetime, timezone
from unittest import skipIf, skipUnless
from unittest.mock import ANY

from django.test import override_settings, tag

from anymail.exceptions import AnymailImproperlyInstalled, AnymailInsecureWebhookWarning
from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.resend import ResendTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase

# These tests are run both with and without 'svix' installed.
try:
    from svix import Webhook
except ImportError:
    SVIX_INSTALLED = False
    Webhook = None
else:
    SVIX_INSTALLED = True


def svix_secret(secret):
    return f"whsec_{base64.b64encode(secret.encode('ascii')).decode('ascii')}"


TEST_SIGNING_SECRET = svix_secret("TEST_SIGNING_SECRET") if SVIX_INSTALLED else None
TEST_WEBHOOK_MESSAGE_ID = "msg_abcdefghijklmnopqrst12345"


class ResendWebhookTestCase(WebhookTestCase):
    def client_post_signed(self, url, json_data, svix_id=None, secret=None):
        """Return self.client.post(url, serialized json_data) signed with secret"""
        svix_id = svix_id or TEST_WEBHOOK_MESSAGE_ID
        secret = secret or TEST_SIGNING_SECRET
        data = json.dumps(json_data)
        headers = {
            "svix-id": svix_id,
        }

        if SVIX_INSTALLED:
            timestamp = datetime.now(tz=timezone.utc)
            signature = Webhook(secret).sign(
                msg_id=svix_id, timestamp=timestamp, data=data
            )
            headers.update(
                {
                    "svix-timestamp": timestamp.timestamp(),
                    "svix-signature": signature,
                }
            )

        return self.client.post(
            url,
            content_type="application/json",
            data=data.encode("utf-8"),
            # Django 4.2+ test Client allows headers=headers;
            # before that, must convert to HTTP_ args:
            **{
                f"HTTP_{header.upper().replace('-', '_')}": value
                for header, value in headers.items()
            },
        )


@tag("resend")
@override_settings(ANYMAIL={})  # clear WEBHOOK_SECRET from base class
class ResendWebhookSettingsTestCase(ResendWebhookTestCase):
    @skipIf(SVIX_INSTALLED, "test covers behavior when 'svix' package missing")
    @override_settings(ANYMAIL_RESEND_SIGNING_SECRET=svix_secret("settings secret"))
    def test_secret_requires_svix_installed(self):
        """If webhook secret is specified, error if svix not available to verify"""
        with self.assertRaisesMessage(AnymailImproperlyInstalled, "svix"):
            self.client_post_signed("/anymail/resend/tracking/", {"type": "email.sent"})

    # Test with and without SVIX_INSTALLED
    def test_basic_auth_required_without_secret(self):
        with self.assertWarns(AnymailInsecureWebhookWarning):
            self.client_post_signed("/anymail/resend/tracking/", {"type": "email.sent"})

    # Test with and without SVIX_INSTALLED
    @override_settings(ANYMAIL={"WEBHOOK_SECRET": "username:password"})
    def test_signing_secret_optional_with_basic_auth(self):
        """Secret verification is optional if using basic auth"""
        response = self.client_post_signed(
            "/anymail/resend/tracking/", {"type": "email.sent"}
        )
        self.assertEqual(response.status_code, 200)

    @skipUnless(SVIX_INSTALLED, "secret verification requires 'svix' package")
    @override_settings(ANYMAIL_RESEND_SIGNING_SECRET=svix_secret("settings secret"))
    def test_signing_secret_view_params(self):
        """Webhook signing secret can be provided as a view param"""
        view_secret = svix_secret("view-level secret")
        view = ResendTrackingWebhookView.as_view(signing_secret=view_secret)
        view_instance = view.view_class(**view.view_initkwargs)
        self.assertEqual(view_instance.signing_secret, view_secret)


@tag("resend")
@override_settings(ANYMAIL_RESEND_SIGNING_SECRET=TEST_SIGNING_SECRET)
class ResendWebhookSecurityTestCase(ResendWebhookTestCase, WebhookBasicAuthTestCase):
    should_warn_if_no_auth = TEST_SIGNING_SECRET is None

    def call_webhook(self):
        return self.client_post_signed(
            "/anymail/resend/tracking/",
            {"type": "email.sent"},
            secret=TEST_SIGNING_SECRET,
        )

    # Additional tests are in WebhookBasicAuthTestCase

    @skipUnless(SVIX_INSTALLED, "signature verification requires 'svix' package")
    def test_verifies_correct_signature(self):
        response = self.client_post_signed(
            "/anymail/resend/tracking/",
            {"type": "email.sent"},
            secret=TEST_SIGNING_SECRET,
        )
        self.assertEqual(response.status_code, 200)

    @skipUnless(SVIX_INSTALLED, "signature verification requires 'svix' package")
    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/resend/tracking/",
            content_type="application/json",
            data={"type": "email.sent"},
        )
        self.assertEqual(response.status_code, 400)

    @skipUnless(SVIX_INSTALLED, "signature verification requires 'svix' package")
    def test_verifies_bad_signature(self):
        # This also verifies that the error log references the correct setting to check.
        with self.assertLogs() as logs:
            response = self.client_post_signed(
                "/anymail/resend/tracking/",
                {"type": "email.sent"},
                secret=svix_secret("wrong signing key"),
            )
        # SuspiciousOperation causes 400 response (even in test client):
        self.assertEqual(response.status_code, 400)
        self.assertIn("check Anymail RESEND_SIGNING_SECRET", logs.output[0])


@tag("resend")
@override_settings(ANYMAIL_RESEND_SIGNING_SECRET=TEST_SIGNING_SECRET)
class ResendTestCase(ResendWebhookTestCase):
    def test_sent_event(self):
        raw_event = {
            "created_at": "2023-09-28T17:19:43.736Z",
            "data": {
                "created_at": "2023-09-28T17:19:43.982Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "headers": [
                    {"name": "Reply-To", "value": "reply@example.com"},
                    {"name": "X-Tags", "value": '["tag1", "Tag 2"]'},
                    {
                        "name": "X-Metadata",
                        "value": '{"cohort": "2018-08-B", "user_id": 123456}',
                    },
                    {"name": "Cc", "value": "cc1@example.org, Cc 2 <cc2@example.org>"},
                ],
                "subject": "Sending test",
                "tags": {"tag1": "Tag_1_value", "tag2": "Tag_2_value"},
                "to": ["Recipient <to@example.org>", "to2@example.org"],
            },
            "type": "email.sent",
        }
        response = self.client_post_signed(
            "/anymail/resend/tracking/",
            raw_event,
            svix_id="msg_2W2D3qXLS5fOaPja1GDg7rF2CwB",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "sent")
        # event.timestamp comes from root-level created_at:
        self.assertEqual(
            event.timestamp,
            # "2023-09-28T17:19:43.736Z"
            datetime(2023, 9, 28, 17, 19, 43, microsecond=736000, tzinfo=timezone.utc),
        )
        # event.message_id matches the message.anymail_status.message_id when the
        # message was sent. It comes from data.email_id:
        self.assertEqual(event.message_id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        # event.event_id is unique for each event, and comes from svix-id header:
        self.assertEqual(event.event_id, "msg_2W2D3qXLS5fOaPja1GDg7rF2CwB")
        # event.recipient is always the first "to" addr:
        self.assertEqual(event.recipient, "to@example.org")
        self.assertEqual(event.tags, ["tag1", "Tag 2"])
        self.assertEqual(event.metadata, {"cohort": "2018-08-B", "user_id": 123456})
        self.assertEqual(event.esp_event, raw_event)

        # You can retrieve Resend native tags (which are different from Anymail tags)
        # from esp_event:
        resend_tags = event.esp_event["data"].get("tags", {})
        self.assertEqual(resend_tags, {"tag1": "Tag_1_value", "tag2": "Tag_2_value"})

    def test_delivered_event(self):
        raw_event = {
            "created_at": "2023-09-28T17:19:44.823Z",
            "data": {
                "created_at": "2023-09-28T17:19:43.982Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "subject": "Sending test",
                "to": ["to@example.org"],
            },
            "type": "email.delivered",
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.recipient, "to@example.org")
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_hard_bounced_event(self):
        raw_event = {
            "created_at": "2023-10-02T18:11:26.101Z",
            "data": {
                "bounce": {
                    "message": (
                        "The recipient's email provider sent a hard bounce message, but"
                        " didn't specify the reason for the hard bounce. We recommend"
                        " removing the recipient's email address from your mailing list."
                        " Sending messages to addresses that produce hard bounces can"
                        " have a negative impact on your reputation as a sender."
                    )
                },
                "created_at": "2023-10-02T18:11:25.729Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "subject": "Sending test",
                "to": ["bounced@resend.dev"],
            },
            "type": "email.bounced",
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertRegex(
            event.description,
            r"^The recipient's email provider sent a hard bounce message.*",
        )
        self.assertIsNone(event.mta_response)  # raw MTA info not provided

    def test_suppressed_event(self):
        raw_event = {
            "created_at": "2023-10-01T20:01:01.598Z",
            "data": {
                "bounce": {
                    "message": (
                        "Resend has suppressed sending to this address because it is"
                        " on the account-level suppression list. This does not count"
                        " toward your bounce rate metric"
                    )
                },
                "created_at": "2023-10-01T20:01:01.339Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "subject": "Sending test",
                "to": ["blocked@example.org"],
            },
            "type": "email.bounced",
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.reject_reason, "blocked")
        self.assertRegex(
            event.description, r"^Resend has suppressed sending to this address.*"
        )
        self.assertIsNone(event.mta_response)  # raw MTA info not provided

    def test_delivery_delayed_event(self):
        # Haven't been able to trigger a real-world version of this event
        # (even with SMTP reply 450, status 4.0.0 "temporary failure").
        # This is the sample payload from Resend's docs, but correcting the type
        # from "email.delivered_delayed" to "email.delivery_delayed" to match
        # docs and configuration UI.
        raw_event = {
            "type": "email.delivery_delayed",  # "email.delivered_delayed",
            "created_at": "2023-02-22T23:41:12.126Z",
            "data": {
                "created_at": "2023-02-22T23:41:11.894719+00:00",
                "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
                "from": "Acme <onboarding@resend.dev>",
                "to": ["delivered@resend.dev"],
                "subject": "Sending this example",
            },
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "deferred")
        self.assertIsNone(event.reject_reason)
        self.assertIsNone(event.description)
        self.assertIsNone(event.mta_response)  # raw MTA info not provided

    def test_complained_event(self):
        raw_event = {
            "created_at": "2023-10-02T18:10:03.690Z",
            "data": {
                "created_at": "2023-10-02T18:10:03.241Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "subject": "Sending test",
                "to": ["complained@resend.dev"],
            },
            "type": "email.complained",
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "complained")

    def test_opened_event(self):
        raw_event = {
            "created_at": "2023-09-28T17:20:38.990Z",
            "data": {
                "created_at": "2023-09-28T17:19:43.982Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "subject": "Sending test",
                "to": ["to@example.org"],
            },
            "type": "email.opened",
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "opened")

    def test_clicked_event(self):
        raw_event = {
            "created_at": "2023-09-28T17:21:35.257Z",
            "data": {
                "click": {
                    "ipAddress": "192.168.1.101",
                    "link": "https://example.com/test",
                    "timestamp": "2023-09-28T17:21:35.257Z",
                    "userAgent": "Mozilla/5.0 ...",
                },
                "created_at": "2023-09-28T17:19:43.982Z",
                "email_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "from": "Sender <from@example.com>",
                "subject": "Sending test",
                "to": ["to@example.org"],
            },
            "type": "email.clicked",
        }
        response = self.client_post_signed("/anymail/resend/tracking/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=ResendTrackingWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.click_url, "https://example.com/test")
        self.assertEqual(event.user_agent, "Mozilla/5.0 ...")
