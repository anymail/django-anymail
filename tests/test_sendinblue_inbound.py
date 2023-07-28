from unittest.mock import ANY

import responses
from django.test import override_settings, tag
from responses.matchers import header_matcher

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.sendinblue import SendinBlueInboundWebhookView

from .utils import sample_email_content, sample_image_content
from .webhook_cases import WebhookTestCase


@tag("sendinblue")
@override_settings(ANYMAIL_SENDINBLUE_API_KEY="test-api-key")
class SendinBlueInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        # Actual (sanitized) Brevo inbound message payload 7/2023
        raw_event = {
            "Uuid": ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
            "MessageId": "<ABCDE12345@mail.example.com>",
            "InReplyTo": None,
            "From": {"Name": "Sender Name", "Address": "from@example.com"},
            "To": [{"Name": None, "Address": "test@anymail.dev"}],
            "Cc": [{"Name": None, "Address": "test+cc@anymail.dev"}],
            "ReplyTo": None,
            "SentAtDate": "Mon, 17 Jul 2023 11:11:22 -0700",
            "Subject": "Testing Brevo inbound",
            "Attachments": [],
            "Headers": {
                # Headers that appear more than once arrive as lists:
                "Received": [
                    "by outbound.example.com for <test@anymail.dev>; ...",
                    "from [10.10.1.22] by smtp.example.com for <test@anymail.dev>; ...",
                ],
                # Single appearance headers arrive as strings:
                "DKIM-Signature": "v=1; a=rsa-sha256; d=example.com; ...",
                "MIME-Version": "1.0",
                "From": "Sender Name <from@example.com>",
                "Date": "Mon, 17 Jul 2023 11:11:22 -0700",
                "Message-ID": "<ABCDE12345@mail.example.com>",
                "Subject": "Testing Brevo inbound",
                "To": "test@anymail.dev",
                "Cc": "test+cc@anymail.dev",
                "Content-Type": "multipart/alternative",
            },
            "SpamScore": 2.9,
            "ExtractedMarkdownMessage": "This is a test message.  \n",
            "ExtractedMarkdownSignature": "- Sender  \n",
            "RawHtmlBody": '<div dir="ltr">This is a <u>test message</u>.<div><br></div><div>- Mike</div><div><br></div></div>\r\n',  # NOQA: E501
            "RawTextBody": "This is a *test message*.\r\n\n- Sender\r\n",
        }

        response = self.client.post(
            "/anymail/sendinblue/inbound/",
            content_type="application/json",
            data={"items": [raw_event]},
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=SendinBlueInboundWebhookView,
            event=ANY,
            esp_name="SendinBlue",
        )
        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        # Brevo doesn't provide inbound event timestamp
        self.assertIsNone(event.timestamp)
        self.assertEqual(event.event_id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_event)

        # AnymailInboundMessage - convenience properties
        message = event.message

        self.assertEqual(message.from_email.display_name, "Sender Name")
        self.assertEqual(message.from_email.addr_spec, "from@example.com")
        self.assertEqual(
            [str(e) for e in message.to],
            ["test@anymail.dev"],
        )
        self.assertEqual([str(e) for e in message.cc], ["test+cc@anymail.dev"])
        self.assertEqual(message.subject, "Testing Brevo inbound")
        self.assertEqual(message.date.isoformat(" "), "2023-07-17 11:11:22-07:00")
        self.assertEqual(message.text, "This is a *test message*.\r\n\n- Sender\r\n")
        self.assertEqual(
            message.html,
            '<div dir="ltr">This is a <u>test message</u>.<div><br></div><div>- Mike</div><div><br></div></div>\r\n',  # NOQA: E501
        )

        self.assertIsNone(message.envelope_sender)
        self.assertIsNone(message.envelope_recipient)

        # Treat Brevo's ExtractedMarkdownMessage as stripped_text:
        self.assertEqual(message.stripped_text, "This is a test message.  \n")
        # Brevo doesn't provide stripped html:
        self.assertIsNone(message.stripped_html)
        self.assertIsNone(message.spam_detected)
        self.assertEqual(message.spam_score, 2.9)

        # AnymailInboundMessage - other headers
        self.assertEqual(message["Message-ID"], "<ABCDE12345@mail.example.com>")
        self.assertEqual(
            message.get_all("Received"),
            [
                "by outbound.example.com for <test@anymail.dev>; ...",
                "from [10.10.1.22] by smtp.example.com for <test@anymail.dev>; ...",
            ],
        )

    def test_envelope_attrs(self):
        # Brevo's example payload shows Return-Path and Delivered-To headers.
        # They don't seem to be present in our tests, but handle them if they're there:
        raw_event = {
            "Headers": {
                "Return-Path": "<sender@example.com>",
                "Delivered-To": "recipient@example.org",
            }
        }
        self.client.post(
            "/anymail/sendinblue/inbound/",
            content_type="application/json",
            data={"items": [raw_event]},
        )
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=SendinBlueInboundWebhookView,
            event=ANY,
            esp_name="SendinBlue",
        )
        event = kwargs["event"]
        message = event.message
        self.assertEqual(message.envelope_sender, "sender@example.com")
        self.assertEqual(message.envelope_recipient, "recipient@example.org")

    @responses.activate
    def test_attachments(self):
        text_content = "Une pièce jointe"
        image_content = sample_image_content()
        email_content = sample_email_content()

        raw_event = {
            # ... much of payload omitted ...
            "Headers": {
                "Content-Type": "multipart/mixed",
            },
            "Attachments": [
                {
                    "Name": "test.txt",
                    "ContentType": "text/plain",
                    "ContentLength": len(text_content),
                    "ContentID": None,
                    "DownloadToken": "download-token-text",
                },
                {
                    "Name": "image.png",
                    "ContentType": "image/png",
                    "ContentLength": len(image_content),
                    "ContentID": "abc123",
                    "DownloadToken": "download-token-image",
                },
                {
                    "Name": "",
                    "ContentType": "message/rfc822",
                    "ContentLength": len(email_content),
                    "ContentID": None,
                    "DownloadToken": "download-token-email",
                },
            ],
        }

        # Brevo supplies a "DownloadToken" that must be used to fetch
        # attachment content. Mock those fetches:
        match_api_key = header_matcher({"api-key": "test-api-key"})
        responses.add(
            responses.GET,
            "https://api.brevo.com/v3/inbound/attachments/download-token-text",
            match=[match_api_key],
            content_type="text/plain; charset=iso-8859-1",
            headers={"content-disposition": 'attachment; filename="test.txt"'},
            body=text_content.encode("iso-8859-1"),
        )
        responses.add(
            responses.GET,
            "https://api.brevo.com/v3/inbound/attachments/download-token-image",
            match=[match_api_key],
            content_type="image/png",
            headers={"content-disposition": 'attachment; filename="image.png"'},
            body=image_content,
        )
        responses.add(
            responses.GET,
            "https://api.brevo.com/v3/inbound/attachments/download-token-email",
            match=[match_api_key],
            content_type="message/rfc822; charset=us-ascii",
            headers={"content-disposition": "attachment"},
            body=email_content,
        )

        response = self.client.post(
            "/anymail/sendinblue/inbound/",
            content_type="application/json",
            data={"items": [raw_event]},
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=SendinBlueInboundWebhookView,
            event=ANY,
            esp_name="SendinBlue",
        )
        event = kwargs["event"]
        message = event.message
        attachments = message.attachments  # AnymailInboundMessage convenience accessor
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].get_filename(), "test.txt")
        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_content_text(), "Une pièce jointe")
        self.assertEqual(attachments[1].get_content_type(), "message/rfc822")
        self.assertEqualIgnoringHeaderFolding(
            attachments[1].get_content_bytes(), email_content
        )

        inlines = message.content_id_map
        self.assertEqual(len(inlines), 1)
        inline = inlines["abc123"]
        self.assertEqual(inline.get_filename(), "image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), image_content)

    def test_misconfigured_tracking(self):
        errmsg = (
            "You seem to have set SendinBlue's *tracking* webhook URL"
            " to Anymail's SendinBlue *inbound* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client.post(
                "/anymail/sendinblue/inbound/",
                content_type="application/json",
                data={"event": "delivered"},
            )
