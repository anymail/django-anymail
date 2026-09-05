from datetime import datetime, timezone
from textwrap import dedent
from unittest.mock import ANY

import responses
from django.test import override_settings, tag
from responses.matchers import header_matcher, request_kwargs_matcher

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailtrap import MailtrapInboundWebhookView

from .test_mailtrap_webhooks import TEST_WEBHOOK_SIGNING_SECRET, MailtrapWebhookTestCase
from .webhook_cases import WebhookBasicAuthTestCase


@tag("mailtrap")
@override_settings(
    ANYMAIL_MAILTRAP_INBOUND_SECRET=TEST_WEBHOOK_SIGNING_SECRET,
    ANYMAIL_MAILTRAP_API_TOKEN="test_api_token",
)
class MailtrapInboundWebhookSignedSecurityTestCase(
    MailtrapWebhookTestCase, WebhookBasicAuthTestCase
):
    should_warn_if_no_auth = False

    def call_webhook(self):
        return self.client_post_signed(
            "/anymail/mailtrap/inbound/",
            json_data={"events": []},
            secret=TEST_WEBHOOK_SIGNING_SECRET,
        )

    # Additional tests are in WebhookBasicAuthTestCase

    def test_valid_signature(self):
        response = self.client_post_signed(
            "/anymail/mailtrap/inbound/",
            json_data={"events": []},
            secret=TEST_WEBHOOK_SIGNING_SECRET,
        )
        self.assertEqual(response.status_code, 200)

    def test_invalid_signature(self):
        response = self.client_post_signed(
            "/anymail/mailtrap/inbound/",
            json_data={"events": []},
            secret="invalid-secret",
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_signature(self):
        response = self.client.post(
            "/anymail/mailtrap/inbound/",
            data={"events": []},
        )
        self.assertEqual(response.status_code, 400)


@tag("mailtrap")
class MailtrapInboundSettingsTestCase(MailtrapWebhookTestCase):
    def test_requires_api_token(self):
        with self.assertRaisesMessage(AnymailConfigurationError, "MAILTRAP_API_TOKEN"):
            self.client_post_signed("/anymail/mailtrap/inbound/", {"events": []})

    @override_settings(
        ANYMAIL={
            "MAILTRAP_INBOUND_SECRET": "inbound secret",
            "MAILTRAP_TRACKING_SECRET": "tracking secret",
            "MAILTRAP_API_TOKEN": "api-token",
        }
    )
    def test_webhook_signing_secret_is_different(self):
        response = self.client_post_signed(
            "/anymail/mailtrap/inbound/",
            {"events": []},
            secret="inbound secret",
        )
        self.assertEqual(response.status_code, 200)

    def test_set_options_in_view_params(self):
        view = MailtrapInboundWebhookView.as_view(
            api_url="https://dev.mailtrap.com/api",
            api_token="special-token",
            inbound_secret="custom",
        )
        view_instance = view.view_class(**view.view_initkwargs)
        self.assertEqual(view_instance.api_url, "https://dev.mailtrap.com/api/")
        self.assertEqual(view_instance.api_token, "special-token")
        self.assertEqual(view_instance.signing_secret, b"custom")


@tag("mailtrap")
@override_settings(ANYMAIL_MAILTRAP_API_TOKEN="api-token")
class MailtrapInboundTestCase(MailtrapWebhookTestCase):
    @responses.activate
    def test_inbound(self):
        raw_webhook_payload = {
            "events": [
                {
                    "event": "inbound.message_received",
                    "event_id": "2eac365a-a49d-11f1-8c43-0a58a9feac03",
                    "timestamp": 1788113042436,
                    "inbox_id": 1111,
                    "message_id": "0000111122223333444",
                    # Mailtrap does not seem to include the email address (9/2026)
                    "from": "Sender Name ",
                }
            ]
        }
        raw_message_url = (
            "https://mailsend-...-bodies.s3.amazonaws.com/.../raw.eml?X-Amz-Params=..."
        )
        raw_message_data = {
            "id": "0000111122223333444",
            "inbox_id": 1111,
            "from": "Sender Name <from@example.com>",
            "to": ["recipient@example.org"],
            # ...
            "raw_message_url": raw_message_url,
            "raw_message_expires_at": "2026-08-30T19:09:32.569Z",
        }
        raw_mime = dedent("""\
            From: Sender Name <from@example.com>
            To: recipient@example.org
            Subject: Testing Mailtrap inbound
            Date: Sun, 30 Aug 2026 11:03:48 -0700
            Message-ID: <ABCDE12345@mail.example.com>
            MIME-Version: 1.0
            Content-Type: multipart/alternative; boundary=boundary

            --boundary
            Content-Type: text/plain

            Hello, world!
            --boundary
            Content-Type: text/html

            <p>Hello, world!</p>
            --boundary--
        """).replace("\n", "\r\n").encode()

        # Mock: retrieve inbound message data
        match_api_token = header_matcher({"Authorization": "Bearer api-token"})
        responses.add(
            responses.GET,
            "https://mailtrap.io/api/inbound/inboxes/1111/messages/0000111122223333444",
            match=[match_api_token],
            json=raw_message_data,
        )

        # Mock: download raw MIME
        responses.add(
            responses.GET,
            raw_message_url,
            content_type="message/rfc822",
            body=raw_mime,
            match=[request_kwargs_matcher({"stream": True})],
        )

        response = self.client.post(
            "/anymail/mailtrap/inbound/",
            content_type="application/json",
            data=raw_webhook_payload,
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailtrapInboundWebhookView,
            event=ANY,
            esp_name="Mailtrap",
        )

        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            datetime(2026, 8, 30, 18, 4, 2, 436000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.esp_event, raw_message_data)
        self.assertIsInstance(event.message, AnymailInboundMessage)

        # AnymailInboundMessage - parsed from raw MIME
        message = event.message
        self.assertEqual(message.from_email.display_name, "Sender Name")
        self.assertEqual(message.from_email.addr_spec, "from@example.com")
        self.assertEqual([str(e) for e in message.to], ["recipient@example.org"])
        self.assertEqual(message.subject, "Testing Mailtrap inbound")
        self.assertEqual(message.text, "Hello, world!")
        self.assertEqual(message.html, "<p>Hello, world!</p>")
        self.assertEqual(message["Message-ID"], "<ABCDE12345@mail.example.com>")

    @responses.activate
    def test_mailtrap_example_payload(self):
        # Mailtrap's "Test your integration" has an incorrect event name under
        # "Example of payload" (9/2026). Anymail should accept and ignore that,
        # without attempting to fetch any messages.
        raw_webhook_payload = {
            "events": [
                {
                    "event": "inbound_message_received",  # (sic)
                    "message_id": "8d2a4c16-9c7f-4a7e-8b51-8d2a4c169c7f",
                    "inbound_inbox_id": 1,
                    "inbound_inbox_address": "hello@inbound.example.com",
                    "from": "sender@example.com",
                    "to": "hello@inbound.example.com",
                    "subject": "Hello from a customer",
                    "timestamp": 1733497282,
                }
            ]
        }
        response = self.client.post(
            "/anymail/mailtrap/inbound/",
            content_type="application/json",
            data=raw_webhook_payload,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(responses.calls), 0)

    def test_misconfigured_tracking(self):
        errmsg = (
            "You seem to have set Mailtrap's *tracking* webhook"
            " to Anymail's Mailtrap *inbound* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client.post(
                "/anymail/mailtrap/inbound/",
                content_type="application/json",
                data={"events": [{"event": "delivery"}]},
            )
