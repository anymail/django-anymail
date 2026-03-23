from datetime import datetime, timezone
from unittest.mock import ANY

import responses
from django.test import override_settings, tag
from responses.matchers import header_matcher

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.resend import ResendInboundWebhookView

from .test_resend_webhooks import ResendWebhookTestCase
from .utils import sample_email_content, sample_image_content

TEST_EMAIL_ID = "56761188-7520-42d8-8898-ff6fc54ce618"
TEST_API_URL = f"https://api.resend.com/emails/receiving/{TEST_EMAIL_ID}"


@tag("resend")
@override_settings(ANYMAIL_RESEND_API_KEY="test-api-key")
class ResendInboundTestCase(ResendWebhookTestCase):
    # https://resend.com/docs/webhooks/emails/received
    # https://resend.com/docs/api-reference/emails/retrieve-received-email

    @responses.activate
    def test_inbound_basics_raw_mime(self):
        """Inbound webhook fetches full email via API; prefers raw MIME."""
        # Minimal webhook notification payload:
        raw_event = {
            "type": "email.received",
            "created_at": "2024-02-22T23:41:12.126Z",
            "data": {
                "email_id": TEST_EMAIL_ID,
                "created_at": "2024-02-22T23:41:11.894719+00:00",
                "from": "Sender Name <from@example.com>",
                "to": ["recipient@example.org"],
                "cc": [],
                "bcc": [],
                "subject": "Testing Resend inbound",
                "message_id": "<ABCDE12345@mail.example.com>",
                "attachments": [],
            },
        }

        # Raw MIME representation of the full email:
        raw_mime = (
            "From: Sender Name <from@example.com>\r\n"
            "To: recipient@example.org\r\n"
            "Subject: Testing Resend inbound\r\n"
            "Date: Thu, 22 Feb 2024 23:41:11 +0000\r\n"
            "Message-ID: <ABCDE12345@mail.example.com>\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: multipart/alternative; boundary=boundary\r\n"
            "\r\n"
            "--boundary\r\n"
            "Content-Type: text/plain\r\n"
            "\r\n"
            "Hello, world!\r\n"
            "--boundary\r\n"
            "Content-Type: text/html\r\n"
            "\r\n"
            "<p>Hello, world!</p>\r\n"
            "--boundary--\r\n"
        )

        raw_mime_url = "https://cdn.example.com/raw/email.eml?token=abc123"

        # Mock: retrieve full email metadata (includes raw download URL)
        match_api_key = header_matcher({"Authorization": "Bearer test-api-key"})
        responses.add(
            responses.GET,
            TEST_API_URL,
            match=[match_api_key],
            json={
                "id": TEST_EMAIL_ID,
                "from": "Sender Name <from@example.com>",
                "to": ["recipient@example.org"],
                "cc": [],
                "bcc": [],
                "reply_to": [],
                "subject": "Testing Resend inbound",
                "html": "<p>Hello, world!</p>",
                "text": "Hello, world!",
                "headers": {"Message-ID": "<ABCDE12345@mail.example.com>"},
                "message_id": "<ABCDE12345@mail.example.com>",
                "created_at": "2024-02-22T23:41:11.894719+00:00",
                "attachments": [],
                "raw": {
                    "download_url": raw_mime_url,
                    "expires_at": "2024-02-23T23:41:11+00:00",
                },
            },
        )

        # Mock: download raw MIME
        responses.add(
            responses.GET,
            raw_mime_url,
            content_type="message/rfc822",
            body=raw_mime.encode("utf-8"),
        )

        response = self.client_post_signed("/anymail/resend/inbound/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=ResendInboundWebhookView,
            event=ANY,
            esp_name="Resend",
        )

        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            datetime(2024, 2, 22, 23, 41, 12, 126000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.esp_event, raw_event)
        self.assertIsInstance(event.message, AnymailInboundMessage)

        # AnymailInboundMessage - parsed from raw MIME
        message = event.message
        self.assertEqual(message.from_email.display_name, "Sender Name")
        self.assertEqual(message.from_email.addr_spec, "from@example.com")
        self.assertEqual([str(e) for e in message.to], ["recipient@example.org"])
        self.assertEqual(message.subject, "Testing Resend inbound")
        self.assertEqual(message.text, "Hello, world!")
        self.assertEqual(message.html, "<p>Hello, world!</p>")
        self.assertEqual(message["Message-ID"], "<ABCDE12345@mail.example.com>")

    @responses.activate
    def test_inbound_basics_parsed_fields(self):
        """Falls back to constructing message from parsed fields when no raw MIME URL."""
        raw_event = {
            "type": "email.received",
            "created_at": "2024-02-22T23:41:12.126Z",
            "data": {
                "email_id": TEST_EMAIL_ID,
                "from": "Sender <from@example.com>",
                "to": ["recipient@example.org"],
                "subject": "Test subject",
                "message_id": "<msg@example.com>",
                "attachments": [],
            },
        }

        match_api_key = header_matcher({"Authorization": "Bearer test-api-key"})
        responses.add(
            responses.GET,
            TEST_API_URL,
            match=[match_api_key],
            json={
                "id": TEST_EMAIL_ID,
                "from": "Sender <from@example.com>",
                "to": ["recipient@example.org"],
                "cc": ["cc@example.com"],
                "bcc": [],
                "reply_to": ["reply@example.com"],
                "subject": "Test subject",
                "html": "<p>Hi</p>",
                "text": "Hi",
                "headers": {
                    "Message-ID": "<msg@example.com>",
                    "Date": "Thu, 22 Feb 2024 23:41:11 +0000",
                    # headers that appear multiple times arrive as lists:
                    "Received": [
                        "by mx1.example.com; ...",
                        "from smtp.example.com; ...",
                    ],
                },
                "message_id": "<msg@example.com>",
                "created_at": "2024-02-22T23:41:11.894719+00:00",
                "attachments": [],
                # No "raw" field → fall back to parsed fields
            },
        )

        response = self.client_post_signed("/anymail/resend/inbound/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=ResendInboundWebhookView,
            event=ANY,
            esp_name="Resend",
        )

        event = kwargs["event"]
        message = event.message
        self.assertEqual(message.from_email.addr_spec, "from@example.com")
        self.assertEqual([str(e) for e in message.to], ["recipient@example.org"])
        self.assertEqual([str(e) for e in message.cc], ["cc@example.com"])
        self.assertEqual(message.subject, "Test subject")
        self.assertEqual(message.text, "Hi")
        self.assertEqual(message.html, "<p>Hi</p>")
        self.assertEqual(message["Reply-To"], "reply@example.com")
        self.assertEqual(message["Message-ID"], "<msg@example.com>")
        self.assertEqual(
            message.get_all("Received"),
            [
                "by mx1.example.com; ...",
                "from smtp.example.com; ...",
            ],
        )

    @responses.activate
    def test_event_id_from_svix_header(self):
        """event_id comes from the svix-id request header."""
        raw_event = {
            "type": "email.received",
            "created_at": "2024-02-22T23:41:12.126Z",
            "data": {
                "email_id": TEST_EMAIL_ID,
                "from": "from@example.com",
                "to": ["to@example.org"],
                "attachments": [],
            },
        }

        responses.add(
            responses.GET,
            TEST_API_URL,
            json={
                "id": TEST_EMAIL_ID,
                "from": "from@example.com",
                "to": ["to@example.org"],
                "cc": [],
                "bcc": [],
                "reply_to": [],
                "subject": "",
                "html": None,
                "text": None,
                "headers": {},
                "attachments": [],
            },
        )

        svix_id = "msg_inbound_abcdef12345"
        response = self.client_post_signed(
            "/anymail/resend/inbound/", raw_event, svix_id=svix_id
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=ResendInboundWebhookView,
            event=ANY,
            esp_name="Resend",
        )
        self.assertEqual(kwargs["event"].event_id, svix_id)

    @responses.activate
    def test_attachments(self):
        """Attachments are downloaded and attached to the message."""
        text_content = b"Hello from attachment"
        image_content = sample_image_content()
        email_content = sample_email_content()

        raw_event = {
            "type": "email.received",
            "created_at": "2024-02-22T23:41:12.126Z",
            "data": {
                "email_id": TEST_EMAIL_ID,
                "from": "from@example.com",
                "to": ["to@example.org"],
                "attachments": [
                    {"id": "att-1"},
                    {"id": "att-2"},
                    {"id": "att-3"},
                ],
            },
        }

        # API response with no raw MIME URL → use parsed fields + attachment downloads
        responses.add(
            responses.GET,
            TEST_API_URL,
            json={
                "id": TEST_EMAIL_ID,
                "from": "from@example.com",
                "to": ["to@example.org"],
                "cc": [],
                "bcc": [],
                "reply_to": [],
                "subject": "",
                "html": None,
                "text": None,
                "headers": {},
                "message_id": None,
                "attachments": [
                    {
                        "id": "att-1",
                        "filename": "test.txt",
                        "content_type": "text/plain",
                        "content_disposition": "attachment",
                        "content_id": None,
                        "download_url": "https://cdn.example.com/att-1",
                        "expires_at": "2024-02-23T23:41:11+00:00",
                    },
                    {
                        "id": "att-2",
                        "filename": "image.png",
                        "content_type": "image/png",
                        "content_disposition": "inline",
                        "content_id": "img001",
                        "download_url": "https://cdn.example.com/att-2",
                        "expires_at": "2024-02-23T23:41:11+00:00",
                    },
                    {
                        "id": "att-3",
                        "filename": "original.eml",
                        "content_type": "message/rfc822",
                        "content_disposition": "attachment",
                        "content_id": None,
                        "download_url": "https://cdn.example.com/att-3",
                        "expires_at": "2024-02-23T23:41:11+00:00",
                    },
                ],
            },
        )

        responses.add(
            responses.GET,
            "https://cdn.example.com/att-1",
            content_type="text/plain; charset=utf-8",
            body=text_content,
        )
        responses.add(
            responses.GET,
            "https://cdn.example.com/att-2",
            content_type="image/png",
            body=image_content,
        )
        responses.add(
            responses.GET,
            "https://cdn.example.com/att-3",
            content_type="message/rfc822",
            body=email_content,
        )

        response = self.client_post_signed("/anymail/resend/inbound/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=ResendInboundWebhookView,
            event=ANY,
            esp_name="Resend",
        )

        event = kwargs["event"]
        message = event.message

        attachments = message.attachments
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].get_filename(), "test.txt")
        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_content_bytes(), text_content)
        self.assertEqual(attachments[1].get_content_type(), "message/rfc822")
        self.assertEqualIgnoringHeaderFolding(
            attachments[1].get_content_bytes(), email_content
        )

        inlines = message.content_id_map
        self.assertEqual(len(inlines), 1)
        inline = inlines["img001"]
        self.assertEqual(inline.get_filename(), "image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), image_content)

    def test_misconfigured_tracking(self):
        """Error if a tracking webhook event is posted to the inbound URL."""
        errmsg = (
            "You seem to have set Resend's *email.sent* webhook"
            " to Anymail's Resend *inbound* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client_post_signed(
                "/anymail/resend/inbound/",
                {"type": "email.sent", "data": {}},
            )
