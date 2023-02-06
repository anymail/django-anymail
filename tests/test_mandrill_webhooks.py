import hashlib
import hmac
import json
from base64 import b64encode
from datetime import datetime, timezone
from unittest.mock import ANY
from urllib.parse import urljoin

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings, tag

from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mandrill import (
    MandrillCombinedWebhookView,
    MandrillTrackingWebhookView,
)

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase

TEST_WEBHOOK_KEY = "TEST_WEBHOOK_KEY"


def mandrill_args(
    events=None,
    host="http://testserver/",  # Django test-client default
    path="/anymail/mandrill/",  # Anymail urlconf default
    auth="username:password",  # WebhookTestCase default
    key=TEST_WEBHOOK_KEY,
):
    """Returns TestClient.post kwargs for Mandrill webhook call with events

    Computes correct signature.
    """
    if events is None:
        events = []
    test_client_path = urljoin(host, path)  # https://testserver/anymail/mandrill/
    if auth:
        # we can get away with this simplification in these controlled tests,
        # but don't ever construct urls like this in production code -- it's not safe!
        full_url = test_client_path.replace("://", "://" + auth + "@")
    else:
        full_url = test_client_path
    mandrill_events = json.dumps(events)
    signed_data = full_url + "mandrill_events" + mandrill_events
    signature = b64encode(
        hmac.new(
            key=key.encode("ascii"),
            msg=signed_data.encode("utf-8"),
            digestmod=hashlib.sha1,
        ).digest()
    )
    return {
        "path": test_client_path,
        "data": {"mandrill_events": mandrill_events},
        "HTTP_X_MANDRILL_SIGNATURE": signature,
    }


@tag("mandrill")
class MandrillWebhookSettingsTestCase(WebhookTestCase):
    def test_requires_webhook_key(self):
        with self.assertRaisesRegex(ImproperlyConfigured, r"MANDRILL_WEBHOOK_KEY"):
            self.client.post("/anymail/mandrill/", data={"mandrill_events": "[]"})

    def test_head_does_not_require_webhook_key(self):
        # Mandrill issues an unsigned HEAD request to verify the wehbook url.
        # Only *after* that succeeds will Mandrill will tell you the webhook key.
        # So make sure that HEAD request will go through without any key set:
        response = self.client.head("/anymail/mandrill/")
        self.assertEqual(response.status_code, 200)


@tag("mandrill")
@override_settings(ANYMAIL_MANDRILL_WEBHOOK_KEY=TEST_WEBHOOK_KEY)
class MandrillWebhookSecurityTestCase(WebhookBasicAuthTestCase):
    should_warn_if_no_auth = False  # because we check webhook signature

    def call_webhook(self):
        kwargs = mandrill_args([{"event": "send"}])
        return self.client.post(**kwargs)

    # Additional tests are in WebhookBasicAuthTestCase

    def test_verifies_correct_signature(self):
        kwargs = mandrill_args([{"event": "send"}])
        response = self.client.post(**kwargs)
        self.assertEqual(response.status_code, 200)

    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/mandrill/", data={"mandrill_events": '[{"event":"send"}]'}
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_bad_signature(self):
        kwargs = mandrill_args([{"event": "send"}], key="wrong API key")
        response = self.client.post(**kwargs)
        self.assertEqual(response.status_code, 400)

    @override_settings(ANYMAIL={})  # clear WEBHOOK_SECRET from WebhookTestCase
    def test_no_basic_auth(self):
        # Signature validation should work properly if you're not using basic auth
        self.clear_basic_auth()
        kwargs = mandrill_args([{"event": "send"}], auth="")
        response = self.client.post(**kwargs)
        self.assertEqual(response.status_code, 200)

    @override_settings(
        ALLOWED_HOSTS=["127.0.0.1", ".example.com"],
        ANYMAIL={
            "MANDRILL_WEBHOOK_URL": "https://abcde:12345@example.com/anymail/mandrill/",
            "WEBHOOK_SECRET": "abcde:12345",
        },
    )
    def test_webhook_url_setting(self):
        # If Django can't build_absolute_uri correctly (e.g., because your proxy
        # frontend isn't setting the proxy headers correctly), you must set
        # MANDRILL_WEBHOOK_URL to the actual public url where Mandrill calls
        # the webhook.
        self.set_basic_auth("abcde", "12345")
        kwargs = mandrill_args(
            [{"event": "send"}], host="https://example.com/", auth="abcde:12345"
        )
        response = self.client.post(SERVER_NAME="127.0.0.1", **kwargs)
        self.assertEqual(response.status_code, 200)

    # override WebhookBasicAuthTestCase version of this test
    @override_settings(ANYMAIL={"WEBHOOK_SECRET": ["cred1:pass1", "cred2:pass2"]})
    def test_supports_credential_rotation(self):
        """You can supply a list of basic auth credentials, and any is allowed"""
        self.set_basic_auth("cred1", "pass1")
        response = self.client.post(**mandrill_args(auth="cred1:pass1"))
        self.assertEqual(response.status_code, 200)

        self.set_basic_auth("cred2", "pass2")
        response = self.client.post(**mandrill_args(auth="cred2:pass2"))
        self.assertEqual(response.status_code, 200)

        self.set_basic_auth("baduser", "wrongpassword")
        response = self.client.post(**mandrill_args(auth="baduser:wrongpassword"))
        self.assertEqual(response.status_code, 400)


@tag("mandrill")
@override_settings(ANYMAIL_MANDRILL_WEBHOOK_KEY=TEST_WEBHOOK_KEY)
class MandrillTrackingTestCase(WebhookTestCase):
    def test_head_request(self):
        # Mandrill verifies webhooks at config time with a HEAD request
        # (See MandrillWebhookSettingsTestCase above for equivalent
        # without the key yet set)
        response = self.client.head("/anymail/mandrill/tracking/")
        self.assertEqual(response.status_code, 200)

    def test_post_request_invalid_json(self):
        kwargs = mandrill_args()
        kwargs["data"] = {"mandrill_events": "GARBAGE DATA"}
        response = self.client.post(**kwargs)
        self.assertEqual(response.status_code, 400)

    def test_send_event(self):
        raw_events = [
            {
                "event": "send",
                "msg": {
                    "ts": 1461095211,  # time send called
                    "subject": "Webhook Test",
                    "email": "recipient@example.com",
                    "sender": "sender@example.com",
                    "tags": ["tag1", "tag2"],
                    "metadata": {"custom1": "value1", "custom2": "value2"},
                    "_id": "abcdef012345789abcdef012345789",
                },
                "_id": "abcdef012345789abcdef012345789",
                "ts": 1461095246,  # time of event
            }
        ]
        response = self.client.post(**mandrill_args(events=raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MandrillCombinedWebhookView,
            event=ANY,
            esp_name="Mandrill",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "sent")
        self.assertEqual(
            event.timestamp, datetime(2016, 4, 19, 19, 47, 26, tzinfo=timezone.utc)
        )
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "abcdef012345789abcdef012345789")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["tag1", "tag2"])
        self.assertEqual(event.metadata, {"custom1": "value1", "custom2": "value2"})

    def test_hard_bounce_event(self):
        raw_events = [
            {
                "event": "hard_bounce",
                "msg": {
                    "ts": 1461095211,  # time send called
                    "subject": "Webhook Test",
                    "email": "bounce@example.com",
                    "sender": "sender@example.com",
                    "bounce_description": "bad_mailbox",
                    "bgtools_code": 10,
                    "diag": "smtp;550 5.1.1 The email account that you tried"
                    " to reach does not exist.",
                    "_id": "abcdef012345789abcdef012345789",
                },
                "_id": "abcdef012345789abcdef012345789",
                "ts": 1461095246,  # time of event
            }
        ]
        response = self.client.post(**mandrill_args(events=raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MandrillCombinedWebhookView,
            event=ANY,
            esp_name="Mandrill",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.message_id, "abcdef012345789abcdef012345789")
        self.assertEqual(event.recipient, "bounce@example.com")
        self.assertEqual(
            event.mta_response,
            "smtp;550 5.1.1 The email account that you tried to reach does not exist.",
        )

    def test_click_event(self):
        raw_events = [
            {
                "event": "click",
                "msg": {
                    "ts": 1461095211,  # time send called
                    "subject": "Webhook Test",
                    "email": "recipient@example.com",
                    "sender": "sender@example.com",
                    "opens": [{"ts": 1461095242}],
                    "clicks": [{"ts": 1461095246, "url": "http://example.com"}],
                    "_id": "abcdef012345789abcdef012345789",
                },
                "user_agent": "Mozilla/5.0 (Windows NT 5.1; rv:11.0)"
                " Gecko Firefox/11.0",
                "url": "http://example.com",
                "_id": "abcdef012345789abcdef012345789",
                "ts": 1461095246,  # time of event
            }
        ]
        response = self.client.post(**mandrill_args(events=raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MandrillCombinedWebhookView,
            event=ANY,
            esp_name="Mandrill",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.esp_event, raw_events[0])
        self.assertEqual(event.click_url, "http://example.com")
        self.assertEqual(
            event.user_agent, "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0"
        )

    def test_sync_event(self):
        # Mandrill sync events use a different format from other events
        # https://mandrill.zendesk.com/hc/en-us/articles/205583297-Sync-Event-Webhook-format
        raw_events = [
            {
                "type": "blacklist",
                "action": "add",
                "reject": {"email": "recipient@example.com", "reason": "manual edit"},
            }
        ]
        response = self.client.post(**mandrill_args(events=raw_events))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MandrillCombinedWebhookView,
            event=ANY,
            esp_name="Mandrill",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "unknown")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.description, "manual edit")

    def test_old_tracking_url(self):
        # Earlier versions of Anymail used /mandrill/tracking/ (and didn't support
        # inbound); make sure that URL continues to work.
        raw_events = [
            {
                "event": "send",
                "msg": {
                    "ts": 1461095211,  # time send called
                    "subject": "Webhook Test",
                    "email": "recipient@example.com",
                    "sender": "sender@example.com",
                    "tags": ["tag1", "tag2"],
                    "metadata": {"custom1": "value1", "custom2": "value2"},
                    "_id": "abcdef012345789abcdef012345789",
                },
                "_id": "abcdef012345789abcdef012345789",
                "ts": 1461095246,  # time of event
            }
        ]
        response = self.client.post(
            **mandrill_args(events=raw_events, path="/anymail/mandrill/tracking/")
        )
        self.assertEqual(response.status_code, 200)
        self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MandrillTrackingWebhookView,
            event=ANY,
            esp_name="Mandrill",
        )
