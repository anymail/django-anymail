import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import ANY

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings, tag

from anymail.exceptions import AnymailConfigurationError
from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.mailgun import MailgunTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase

TEST_WEBHOOK_SIGNING_KEY = "TEST_WEBHOOK_SIGNING_KEY"


def mailgun_signature(timestamp, token, webhook_signing_key):
    """Generates a Mailgun webhook signature"""
    # https://documentation.mailgun.com/en/latest/user_manual.html#securing-webhooks
    return hmac.new(
        key=webhook_signing_key.encode("ascii"),
        msg="{timestamp}{token}".format(timestamp=timestamp, token=token).encode(
            "ascii"
        ),
        digestmod=hashlib.sha256,
    ).hexdigest()


def mailgun_sign_payload(data, webhook_signing_key=TEST_WEBHOOK_SIGNING_KEY):
    """Add or complete Mailgun webhook signature block in data dict"""
    # Modifies the dict in place
    event_data = data.get("event-data", {})
    signature = data.setdefault("signature", {})
    token = signature.setdefault("token", "1234567890abcdef1234567890abcdef")
    timestamp = signature.setdefault(
        "timestamp", str(int(float(event_data.get("timestamp", "1234567890.123"))))
    )
    signature["signature"] = mailgun_signature(
        timestamp, token, webhook_signing_key=webhook_signing_key
    )
    return data


def mailgun_sign_legacy_payload(data, webhook_signing_key=TEST_WEBHOOK_SIGNING_KEY):
    """Add a Mailgun webhook signature to data dict"""
    # Modifies the dict in place
    data.setdefault("timestamp", "1234567890")
    data.setdefault("token", "1234567890abcdef1234567890abcdef")
    data["signature"] = mailgun_signature(
        data["timestamp"], data["token"], webhook_signing_key=webhook_signing_key
    )
    return data


def querydict_to_postdict(qd):
    """Converts a Django QueryDict to a TestClient.post(data)-style dict

    Single-value fields appear as normal
    Multi-value fields appear as a list (differs from QueryDict.dict)
    """
    return {key: values if len(values) > 1 else values[0] for key, values in qd.lists()}


@tag("mailgun")
class MailgunWebhookSettingsTestCase(WebhookTestCase):
    def test_requires_webhook_signing_key(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "MAILGUN_WEBHOOK_SIGNING_KEY"
        ):
            self.client.post(
                "/anymail/mailgun/tracking/",
                content_type="application/json",
                data=json.dumps(
                    mailgun_sign_payload({"event-data": {"event": "delivered"}})
                ),
            )

    @override_settings(
        ANYMAIL_MAILGUN_API_KEY="TEST_API_KEY",
        ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY="TEST_WEBHOOK_SIGNING_KEY",
    )
    def test_webhook_signing_is_different_from_api_key(self):
        """
        Webhooks should use MAILGUN_WEBHOOK_SIGNING_KEY,
        not MAILGUN_API_KEY, if both provided
        """
        payload = json.dumps(
            mailgun_sign_payload(
                {"event-data": {"event": "delivered"}},
                webhook_signing_key="TEST_WEBHOOK_SIGNING_KEY",
            )
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/", content_type="application/json", data=payload
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(ANYMAIL_MAILGUN_API_KEY="TEST_API_KEY")
    def test_defaults_webhook_signing_to_api_key(self):
        """
        Webhooks should default to MAILGUN_API_KEY
        if MAILGUN_WEBHOOK_SIGNING_KEY not provided
        """
        payload = json.dumps(
            mailgun_sign_payload(
                {"event-data": {"event": "delivered"}},
                webhook_signing_key="TEST_API_KEY",
            )
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/", content_type="application/json", data=payload
        )
        self.assertEqual(response.status_code, 200)

    def test_webhook_signing_key_view_params(self):
        """Webhook signing key can be provided as a view param"""
        view = MailgunTrackingWebhookView.as_view(
            webhook_signing_key="VIEW_SIGNING_KEY"
        )
        view_instance = view.view_class(**view.view_initkwargs)
        self.assertEqual(view_instance.webhook_signing_key, b"VIEW_SIGNING_KEY")

        # Can also use `api_key` param for backwards compatibility
        # with earlier Anymail versions
        view = MailgunTrackingWebhookView.as_view(api_key="VIEW_API_KEY")
        view_instance = view.view_class(**view.view_initkwargs)
        self.assertEqual(view_instance.webhook_signing_key, b"VIEW_API_KEY")


@tag("mailgun")
@override_settings(ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY=TEST_WEBHOOK_SIGNING_KEY)
class MailgunWebhookSecurityTestCase(WebhookBasicAuthTestCase):
    should_warn_if_no_auth = False  # because we check webhook signature

    def call_webhook(self):
        return self.client.post(
            "/anymail/mailgun/tracking/",
            content_type="application/json",
            data=json.dumps(
                mailgun_sign_payload({"event-data": {"event": "delivered"}})
            ),
        )

    # Additional tests are in WebhookBasicAuthTestCase

    def test_verifies_correct_signature(self):
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            content_type="application/json",
            data=json.dumps(
                mailgun_sign_payload({"event-data": {"event": "delivered"}})
            ),
        )
        self.assertEqual(response.status_code, 200)

    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            content_type="application/json",
            data=json.dumps({"event-data": {"event": "delivered"}}),
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_bad_signature(self):
        data = mailgun_sign_payload(
            {"event-data": {"event": "delivered"}},
            webhook_signing_key="wrong signing key",
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            content_type="application/json",
            data=json.dumps(data),
        )
        self.assertEqual(response.status_code, 400)


@tag("mailgun")
@override_settings(ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY=TEST_WEBHOOK_SIGNING_KEY)
class MailgunTestCase(WebhookTestCase):
    # Tests for Mailgun's new webhooks (announced 2018-06-29)

    def test_delivered_event(self):
        # This is an actual, complete (sanitized) "delivered" event as received from
        # Mailgun. (For brevity, later tests omit several payload fields that aren't
        # used by Anymail.)
        raw_event = mailgun_sign_payload(
            {
                "signature": {
                    "timestamp": "1534108637",
                    "token": "651869375b9df3c98fc15c4889b102119add1235c38fc92824",
                    "signature": "...",
                },
                "event-data": {
                    "tags": [],
                    "timestamp": 1534108637.153125,
                    "storage": {
                        "url": "https://sw.api.mailgun.net/v3/domains/"
                        "example.org/messages/eyJwI...",
                        "key": "eyJwI...",
                    },
                    "recipient-domain": "example.com",
                    "id": "hTWCTD81RtiDN-...",
                    "campaigns": [],
                    "user-variables": {},
                    "flags": {
                        "is-routed": False,
                        "is-authenticated": True,
                        "is-system-test": False,
                        "is-test-mode": False,
                    },
                    "log-level": "info",
                    "envelope": {
                        "sending-ip": "333.123.123.200",
                        "sender": "test@example.org",
                        "transport": "smtp",
                        "targets": "recipient@example.com",
                    },
                    "message": {
                        "headers": {
                            "to": "recipient@example.com",
                            "message-id": "20180812211713.1.DF5966851B4BAA99"
                            "@example.org",
                            "from": "test@example.org",
                            "subject": "Testing",
                        },
                        "attachments": [],
                        "size": 809,
                    },
                    "recipient": "recipient@example.com",
                    "event": "delivered",
                    "delivery-status": {
                        "tls": True,
                        "mx-host": "smtp-in.example.com",
                        "attempt-no": 1,
                        "description": "",
                        "session-seconds": 3.5700838565826416,
                        "utf8": True,
                        "code": 250,
                        "message": "OK",
                        "certificate-verified": True,
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(
            event.timestamp,
            datetime(2018, 8, 12, 21, 17, 17, microsecond=153125, tzinfo=timezone.utc),
        )
        self.assertEqual(
            event.message_id, "<20180812211713.1.DF5966851B4BAA99@example.org>"
        )
        # Note that Anymail uses the "token" as its normalized event_id:
        self.assertEqual(
            event.event_id, "651869375b9df3c98fc15c4889b102119add1235c38fc92824"
        )
        # ... if you want the Mailgun "event id",
        # that's available through the raw esp_event:
        self.assertEqual(event.esp_event["event-data"]["id"], "hTWCTD81RtiDN-...")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.esp_event, raw_event)
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_failed_permanent_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "failed",
                    "severity": "permanent",
                    "reason": "bounce",
                    "recipient": "invalid@example.com",
                    "timestamp": 1534110422.389832,
                    "log-level": "error",
                    "message": {
                        "headers": {
                            "to": "invalid@example.com",
                            "message-id": "20180812214658.1.0DF563D0B3597700"
                            "@example.org",
                            "from": "Test Sender ",
                        },
                    },
                    "delivery-status": {
                        "tls": True,
                        "mx-host": "aspmx.l.example.org",
                        "attempt-no": 1,
                        "description": "",
                        "session-seconds": 2.952177047729492,
                        "utf8": True,
                        "code": 550,
                        "message": "5.1.1 The email account that you tried to reach"
                        " does not exist. Please try\n"
                        "5.1.1 double-checking the recipient's email address for typos",
                        "certificate-verified": True,
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.recipient, "invalid@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description, "")
        self.assertEqual(
            event.mta_response,
            "5.1.1 The email account that you tried to reach does not exist."
            " Please try\n"
            "5.1.1 double-checking the recipient's email address for typos",
        )

    def test_failed_temporary_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "failed",
                    "severity": "temporary",
                    "reason": "generic",
                    "timestamp": 1534111899.659519,
                    "log-level": "warn",
                    "message": {
                        "headers": {
                            "to": "undeliverable@nomx.example.com",
                            "message-id": "20180812214638.1.4A7D468E9BC18C5D"
                            "@example.org",
                            "from": "Test Sender ",
                            "subject": "Testing",
                        },
                    },
                    "recipient": "undeliverable@nomx.example.com",
                    "delivery-status": {
                        "attempt-no": 3,
                        "description": "No MX for nomx.example.com",
                        "session-seconds": 0.0,
                        "retry-seconds": 1800,
                        "code": 498,
                        "message": "No MX for nomx.example.com",
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.recipient, "undeliverable@nomx.example.com")
        self.assertEqual(event.reject_reason, "other")
        self.assertEqual(event.description, "No MX for nomx.example.com")
        self.assertEqual(event.mta_response, "No MX for nomx.example.com")

    def test_failed_greylisted_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "failed",
                    "severity": "temporary",
                    "reason": "greylisted",
                    "timestamp": 1534111899.659519,
                    "log-level": "warn",
                    "message": {
                        "headers": {
                            "to": "undeliverable@nomx.example.com",
                            "message-id": "20180812214638.1.4A7D468E9BC18C5D"
                            "@example.org",
                            "from": "Test Sender ",
                            "subject": "Testing",
                        },
                    },
                    "recipient": "undeliverable@mx.example.com",
                    "delivery-status": {
                        "mx-host": "mx.example.com",
                        "attempt-no": 1,
                        "description": "Recipient address rejected: Greylisted",
                        "session-seconds": 0.0,
                        "retry-seconds": 300,
                        "code": 450,
                        "message": "Recipient address rejected: Greylisted",
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "deferred")
        self.assertEqual(event.recipient, "undeliverable@mx.example.com")
        self.assertEqual(event.reject_reason, "other")
        self.assertEqual(event.description, "Recipient address rejected: Greylisted")
        self.assertEqual(event.mta_response, "Recipient address rejected: Greylisted")

    def test_rejected_event(self):
        # (The "rejected" event is documented and appears in Mailgun dashboard logs,
        # but it doesn't appear to be delivered through webhooks as of 8/2018.)
        # Note that this payload lacks the recipient field present in all other events.
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "rejected",
                    "timestamp": 1529704976.104692,
                    "log-level": "warn",
                    "reject": {
                        "reason": "Sandbox subdomains are for test purposes only.",
                        "description": "",
                    },
                    "message": {
                        "headers": {
                            "to": "Recipient Name <recipient@example.org>",
                            "message-id": "20180622220256.1.B31A451A2E5422BB"
                            "@sandbox55887.mailgun.org",
                            "from": "test@sandbox55887.mailgun.org",
                            "subject": "Test Subject",
                        },
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.reject_reason, "other")
        self.assertEqual(
            event.description, "Sandbox subdomains are for test purposes only."
        )
        self.assertEqual(event.recipient, "recipient@example.org")

    def test_complained_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "complained",
                    "id": "ncV2XwymRUKbPek_MIM-Gw",
                    "timestamp": 1377214260.049634,
                    "log-level": "warn",
                    "recipient": "recipient@example.com",
                    "message": {
                        "headers": {
                            "to": "foo@recipient.com",
                            "message-id": "20130718032413.263EE2E0926@example.org",
                            "from": "Sender Name <sender@example.org>",
                            "subject": "We are not spammer",
                        },
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_unsubscribed_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "unsubscribed",
                    "id": "W3X4JOhFT-OZidZGKKr9iA",
                    "timestamp": 1377213791.421473,
                    "log-level": "info",
                    "recipient": "recipient@example.com",
                    "message": {
                        "headers": {
                            "message-id": "20130822232216.13966.79700"
                            "@samples.mailgun.org"
                        }
                    },
                },
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "unsubscribed")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_opened_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "opened",
                    "timestamp": 1534109600.089676,
                    "recipient": "recipient@example.com",
                    "tags": ["welcome", "variation-A"],
                    "user-variables": {"cohort": "2018-08-B", "user_id": "123456"},
                    "message": {
                        # Mailgun *only* includes the message-id header
                        # for opened, clicked events...
                        "headers": {
                            "message-id": "20180812213139.1"
                            ".BC6694A917BB7E6A@example.org"
                        }
                    },
                    "geolocation": {
                        "country": "US",
                        "region": "CA",
                        "city": "San Francisco",
                    },
                    "ip": "888.222.444.111",
                    "client-info": {
                        "client-type": "browser",
                        "client-os": "OS X",
                        "device-type": "desktop",
                        "client-name": "Chrome",
                        "user-agent": "Mozilla/5.0"
                        " (Macintosh; Intel Mac OS X 10_13_6)...",
                    },
                }
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, ["welcome", "variation-A"])
        self.assertEqual(event.metadata, {"cohort": "2018-08-B", "user_id": "123456"})

    def test_clicked_event(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "clicked",
                    "timestamp": 1534109600.089676,
                    "recipient": "recipient@example.com",
                    "url": "https://example.com/test",
                }
            }
        )
        response = self.client.post(
            "/anymail/mailgun/tracking/",
            data=json.dumps(raw_event),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.click_url, "https://example.com/test")


@tag("mailgun")
@override_settings(ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY=TEST_WEBHOOK_SIGNING_KEY)
class MailgunLegacyTestCase(WebhookTestCase):
    # Tests for Mailgun's "legacy" webhooks
    # (which were the only webhooks available prior to Anymail 4.0)

    def test_delivered_event(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "domain": "example.com",
                "message-headers": json.dumps(
                    [
                        ["Sender", "from=example.com"],
                        ["Date", "Thu, 21 Apr 2016 17:55:29 +0000"],
                        [
                            "X-Mailgun-Sid",
                            "WyIxZmY4ZSIsICJtZWRtdW5kc0BnbWFpbC5jb20iLCAiZjFjNzgyIl0=",
                        ],
                        [
                            "Received",
                            "by luna.mailgun.net with HTTP;"
                            " Thu, 21 Apr 2016 17:55:29 +0000",
                        ],
                        [
                            "Message-Id",
                            "<20160421175529.19495.89030.B3AE3728@example.com>",
                        ],
                        ["To", "recipient@example.com"],
                        ["From", "from@example.com"],
                        ["Subject", "Webhook testing"],
                        ["Mime-Version", "1.0"],
                        [
                            "Content-Type",
                            [
                                "multipart/alternative",
                                {"boundary": "74fb561763da440d8e6a034054974251"},
                            ],
                        ],
                    ]
                ),
                "X-Mailgun-Sid": "WyIxZmY4ZSIsICJtZWRtdW5kc"
                "0BnbWFpbC5jb20iLCAiZjFjNzgyIl0=",
                "token": "06c96bafc3f42a66b9edd546347a2fe18dc23461fe80dc52f0",
                "timestamp": "1461261330",
                "Message-Id": "<20160421175529.19495.89030.B3AE3728@example.com>",
                "recipient": "recipient@example.com",
                "event": "delivered",
            }
        )
        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(
            event.timestamp, datetime(2016, 4, 21, 17, 55, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(
            event.message_id, "<20160421175529.19495.89030.B3AE3728@example.com>"
        )
        self.assertEqual(
            event.event_id, "06c96bafc3f42a66b9edd546347a2fe18dc23461fe80dc52f0"
        )
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(querydict_to_postdict(event.esp_event), raw_event)
        self.assertEqual(event.tags, [])
        self.assertEqual(event.metadata, {})

    def test_dropped_bounce(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "code": "605",
                "domain": "example.com",
                "description": "Not delivering to previously bounced address",
                "attachment-count": "1",
                "Message-Id": "<20160421180324.70521.79375.96884DDB@example.com>",
                "reason": "hardfail",
                "event": "dropped",
                "message-headers": json.dumps(
                    [
                        [
                            "X-Mailgun-Sid",
                            "WyI3Y2VjMyIsICJib3VuY2VAZXhhbXBsZS5jb20iLCAiZjFjNzgyIl0=",
                        ],
                        [
                            "Received",
                            "by luna.mailgun.net with HTTP;"
                            " Thu, 21 Apr 2016 18:03:24 +0000",
                        ],
                        [
                            "Message-Id",
                            "<20160421180324.70521.79375.96884DDB@example.com>",
                        ],
                        ["To", "bounce@example.com"],
                        ["From", "from@example.com"],
                        ["Subject", "Webhook testing"],
                        ["Mime-Version", "1.0"],
                        [
                            "Content-Type",
                            [
                                "multipart/alternative",
                                {"boundary": "a5b51388a4e3455d8feb8510bb8c9fa2"},
                            ],
                        ],
                    ]
                ),
                "recipient": "bounce@example.com",
                "timestamp": "1461261330",
                "X-Mailgun-Sid": "WyI3Y2VjMyIsICJib3VuY2VAZ"
                "XhhbXBsZS5jb20iLCAiZjFjNzgyIl0=",
                "token": "a3fe1fa1640349ac552b84ddde373014b4c41645830c8dd3fc",
            }
        )
        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(
            event.timestamp, datetime(2016, 4, 21, 17, 55, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(
            event.message_id, "<20160421180324.70521.79375.96884DDB@example.com>"
        )
        self.assertEqual(
            event.event_id, "a3fe1fa1640349ac552b84ddde373014b4c41645830c8dd3fc"
        )
        self.assertEqual(event.recipient, "bounce@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(
            event.description, "Not delivering to previously bounced address"
        )
        self.assertEqual(querydict_to_postdict(event.esp_event), raw_event)

    def test_dropped_spam(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "code": "607",
                "description": "Not delivering to a user who marked"
                " your messages as spam",
                "reason": "hardfail",
                "event": "dropped",
                "recipient": "complaint@example.com",
                # (omitting some fields that aren't relevant to the test)
            }
        )
        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.reject_reason, "spam")
        self.assertEqual(
            event.description,
            "Not delivering to a user who marked your messages as spam",
        )

    def test_dropped_timed_out(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "code": "499",
                "description": "Unable to connect to MX servers: [example.com]",
                "reason": "old",
                "event": "dropped",
                "recipient": "complaint@example.com",
                # (omitting some fields that aren't relevant to the test)
            }
        )
        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.reject_reason, "timed_out")
        self.assertEqual(
            event.description, "Unable to connect to MX servers: [example.com]"
        )

    def test_invalid_mailbox(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "code": "550",
                "error": "550 5.1.1 The email account that you tried to reach does"
                " not exist. Please try "
                "    5.1.1 double-checking the recipient's email address for typos or "
                "    5.1.1 unnecessary spaces.",
                "event": "bounced",
                "recipient": "noreply@example.com",
                # (omitting some fields that aren't relevant to the test)
            }
        )
        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertIn(
            "The email account that you tried to reach does not exist",
            event.mta_response,
        )

    def test_alt_smtp_code(self):
        # In some cases, Mailgun uses RFC-3463 extended SMTP status codes
        # (x.y.z, rather than nnn). See issue #62.
        raw_event = mailgun_sign_legacy_payload(
            {
                "code": "5.1.1",
                "error": "smtp;550 5.1.1 RESOLVER.ADR.RecipNotFound; not found",
                "event": "bounced",
                "recipient": "noreply@example.com",
                # (omitting some fields that aren't relevant to the test)
            }
        )
        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=MailgunTrackingWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertIn("RecipNotFound", event.mta_response)

    def test_metadata_message_headers(self):
        # Metadata fields are interspersed with other data, but also in message-headers
        # for delivered, bounced and dropped events
        raw_event = mailgun_sign_legacy_payload(
            {
                "event": "delivered",
                "message-headers": json.dumps(
                    [
                        [
                            "X-Mailgun-Variables",
                            '{"custom1": "value1",'
                            ' "custom2": "{\\"key\\":\\"value\\"}"}',
                        ],
                    ]
                ),
                "custom1": "value1",
                # you can store JSON, but you'll need to unpack it yourself:
                "custom2": '{"key":"value"}',
            }
        )
        self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler)
        event = kwargs["event"]
        self.assertEqual(
            event.metadata, {"custom1": "value1", "custom2": '{"key":"value"}'}
        )

    def test_metadata_post_fields(self):
        # Metadata fields are only interspersed with other event params
        # for opened, clicked, unsubscribed events
        raw_event = mailgun_sign_legacy_payload(
            {
                "event": "clicked",
                "custom1": "value1",
                # you can store JSON, but you'll need to unpack it yourself:
                "custom2": '{"key":"value"}',
            }
        )
        self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler)
        event = kwargs["event"]
        self.assertEqual(
            event.metadata, {"custom1": "value1", "custom2": '{"key":"value"}'}
        )

    def test_metadata_key_conflicts(self):
        # If you happen to name metadata (user-variable) keys the same as Mailgun
        # event properties, Mailgun will include both in the webhook post.
        # Make sure we don't confuse them.
        metadata = {
            "event": "metadata-event",
            "recipient": "metadata-recipient",
            "signature": "metadata-signature",
            "timestamp": "metadata-timestamp",
            "token": "metadata-token",
            "ordinary field": "ordinary metadata value",
        }

        raw_event = mailgun_sign_legacy_payload(
            {
                "event": "clicked",
                "recipient": "actual-recipient@example.com",
                "token": "actual-event-token",
                "timestamp": "1461261330",
                "url": "http://clicked.example.com/actual/event/param",
                "h": "an (undocumented) Mailgun event param",
                "tag": ["actual-tag-1", "actual-tag-2"],
            }
        )

        # Simulate how Mailgun merges user-variables fields into event:
        for key in metadata.keys():
            if key in raw_event:
                if key in {"signature", "timestamp", "token"}:
                    # For these fields, Mailgun's value appears after the metadata value
                    raw_event[key] = [metadata[key], raw_event[key]]
                elif key == "message-headers":
                    pass  # Mailgun won't merge this field into the event
                else:
                    # For all other fields, the defined event value comes first
                    raw_event[key] = [raw_event[key], metadata[key]]
            else:
                raw_event[key] = metadata[key]

        response = self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        # if this fails, signature checking is using metadata values:
        self.assertEqual(response.status_code, 200)

        kwargs = self.assert_handler_called_once_with(self.tracking_handler)
        event = kwargs["event"]
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.recipient, "actual-recipient@example.com")
        self.assertEqual(event.timestamp.isoformat(), "2016-04-21T17:55:30+00:00")
        self.assertEqual(event.event_id, "actual-event-token")
        self.assertEqual(event.tags, ["actual-tag-1", "actual-tag-2"])
        self.assertEqual(event.metadata, metadata)

    def test_tags(self):
        # Most events include multiple 'tag' fields for message's tags
        raw_event = mailgun_sign_legacy_payload(
            {
                # Django TestClient encodes list as multiple field values:
                "tag": ["tag1", "tag2"],
                "event": "opened",
            }
        )
        self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler)
        event = kwargs["event"]
        self.assertEqual(event.tags, ["tag1", "tag2"])

    def test_x_tags(self):
        # Delivery events don't include 'tag', but do include 'X-Mailgun-Tag' fields
        raw_event = mailgun_sign_legacy_payload(
            {
                "X-Mailgun-Tag": ["tag1", "tag2"],
                "event": "delivered",
            }
        )
        self.client.post("/anymail/mailgun/tracking/", data=raw_event)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler)
        event = kwargs["event"]
        self.assertEqual(event.tags, ["tag1", "tag2"])

    def test_misconfigured_inbound(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "recipient": "test@inbound.example.com",
                "sender": "envelope-from@example.org",
                "message-headers": "[]",
                "body-plain": "Test body plain",
                "body-html": "<div>Test body html</div>",
            }
        )

        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set Mailgun's *inbound* route"
            " to Anymail's Mailgun *tracking* webhook URL.",
        ):
            self.client.post("/anymail/mailgun/tracking/", data=raw_event)
