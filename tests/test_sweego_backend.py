import json
from base64 import b64encode
from datetime import datetime

from django.core import mail
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .mock_requests_backend import RequestsBackendMockAPITestCase, SessionSharingTestCases
from .utils import sample_image_content


@tag("sweego")
@override_settings(
    EMAIL_BACKEND="anymail.backends.sweego.EmailBackend",
    ANYMAIL={
        "SWEEGO_API_KEY": "test_api_key_1234567890abcdef",
    },
)
class SweegoBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""
    {
        "channel": "email",
        "provider": "sweego",
        "swg_uids": {"to@example.com": "02-abc123-def456"},
        "transaction_id": "tx-1234567890abcdef"
    }
    """

    def setUp(self):
        super().setUp()
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("sweego")
class SweegoBackendStandardEmailTests(SweegoBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@sender.example.com",
            ["to@example.com"],
            fail_silently=False,
        )
        self.assert_esp_called("/send")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["Api-Key"], "test_api_key_1234567890abcdef")
        self.assertEqual(headers["Content-Type"], "application/json")
        
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["message-txt"], "Here is the message.")
        self.assertEqual(data["from"]["email"], "from@sender.example.com")
        self.assertEqual(data["recipients"][0]["email"], "to@example.com")

    def test_name_addr(self):
        """Make sure RFC2822 name-addr format (with display-name) is allowed"""
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "From Name <from@example.com>",
            ["Recipient #1 <to1@example.com>", "to2@example.com"],
            cc=["Carbon Copy <cc1@example.com>", "cc2@example.com"],
            bcc=["Blind Copy <bcc1@example.com>", "bcc2@example.com"],
        )
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(data["from"]["email"], "from@example.com")
        self.assertEqual(data["from"]["name"], "From Name")
        # All recipients go to 'recipients' array in Sweego
        recipients = data["recipients"]
        emails = [r["email"] for r in recipients]
        self.assertIn("to1@example.com", emails)
        self.assertIn("to2@example.com", emails)
        self.assertIn("cc1@example.com", emails)
        self.assertIn("bcc1@example.com", emails)

    def test_email_message(self):
        email = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["to1@example.com", "to2@example.com"],
            bcc=["bcc1@example.com"],
            cc=["cc1@example.com"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject")
        self.assertEqual(data["message-txt"], "Body")
        # All recipients go to 'recipients' array in Sweego
        recipients = data["recipients"]
        emails = [r["email"] for r in recipients]
        self.assertEqual(len(recipients), 4)  # 2 to + 1 cc + 1 bcc
        self.assertIn("to1@example.com", emails)
        self.assertIn("to2@example.com", emails)
        self.assertIn("bcc1@example.com", emails)
        self.assertIn("cc1@example.com", emails)

    def test_html_message(self):
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message-txt"], text_content)
        self.assertEqual(data["message-html"], html_content)

    def test_html_only(self):
        email = mail.EmailMessage(
            "Subject", "<p>HTML only</p>", "from@example.com", ["to@example.com"]
        )
        email.content_subtype = "html"
        email.send()
        data = self.get_api_call_json()
        self.assertNotIn("message-txt", data)
        self.assertEqual(data["message-html"], "<p>HTML only</p>")

    def test_reply_to(self):
        email = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            reply_to=["reply@example.com"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["reply-to"]["email"], "reply@example.com")

    def test_reply_to_with_name(self):
        email = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            reply_to=["Reply Name <reply@example.com>"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["reply-to"]["email"], "reply@example.com")
        self.assertEqual(data["reply-to"]["name"], "Reply Name")

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(
            filename="test.txt", content=text_content, mimetype="text/plain"
        )

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["filename"], "test.txt")
        # Sweego uses only filename and content (no type field)
        self.assertEqual(
            attachments[0]["content"], b64encode(text_content.encode()).decode()
        )
        self.assertEqual(attachments[1]["filename"], "test.png")
        self.assertEqual(attachments[1]["content"], b64encode(png_content).decode())

    def test_unicode_attachment_correctly_decoded(self):
        # Slight modification of the Django unicode docs example
        self.message.attach("Une pièce jointe.txt", "Une pièce jointe", "text/plain")
        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], "Une pièce jointe.txt")

    def test_embedded_images(self):
        """Test that inline images are converted to regular attachments.
        
        Sweego's /send API doesn't support inline attachments,
        so they are added as regular attachments instead.
        """
        from anymail.message import attach_inline_image

        image_filename = "image.png"
        image_content = sample_image_content()
        cid = attach_inline_image(self.message, image_content, filename=image_filename)

        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message-html"], html_content)

        # Inline images become regular attachments in Sweego
        self.assertNotIn("inline", data)
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], image_filename)
        self.assertEqual(attachments[0]["content"], b64encode(image_content).decode())

    def test_attached_images(self):
        image_filename = "image.png"
        image_content = sample_image_content()

        self.message.attach(image_filename, image_content, "image/png")
        self.message.send()

        data = self.get_api_call_json()
        self.assertNotIn("inline", data)
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], image_filename)

    def test_extra_headers(self):
        self.message.extra_headers = {"X-Custom": "custom value"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["headers"]["X-Custom"], "custom value")

    def test_extra_headers_serialization(self):
        self.message.extra_headers = {"X-Custom-Number": 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["headers"]["X-Custom-Number"], "123")

    def test_api_failure(self):
        self.set_mock_response(status_code=400, raw=b'{"error": "Invalid request"}')
        with self.assertRaisesMessage(AnymailAPIError, "Invalid request"):
            self.message.send()

    def test_api_response_invalid_json(self):
        self.set_mock_response(status_code=200, raw=b"Not JSON")
        with self.assertRaises(AnymailAPIError):
            self.message.send()


@tag("sweego")
class SweegoBackendAnymailFeatureTests(SweegoBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "order_id": "67890"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertIn("headers", data)
        # Metadata should be stored as X-Metadata-* headers
        self.assertEqual(data["headers"]["X-Metadata-user_id"], "12345")
        self.assertEqual(data["headers"]["X-Metadata-order_id"], "67890")

    def test_tags(self):
        self.message.tags = ["receipt", "important"]
        self.message.send()
        data = self.get_api_call_json()
        # Tags should be stored in campaign-tags field
        self.assertEqual(data["campaign-tags"], ["receipt", "important"])

    def test_tags_passed_through(self):
        """Test that tags are passed through without validation per Anymail policy"""
        # Per ADDING_ESPS.md: Anymail doesn't enforce ESP policies,
        # it passes data through and lets the ESP validate
        self.message.tags = [
            "valid-tag",
            "has spaces",  # Invalid per Sweego, but should pass through
            "special@chars!",  # Invalid per Sweego, but should pass through
            "verylongtagnamethatneedstruncation",  # Too long, but should pass through
            "tag5",
            "tag6",  # More than 5, but should pass through
        ]
        self.message.send()
        data = self.get_api_call_json()
        # All tags should be passed through as-is
        self.assertEqual(len(data["campaign-tags"]), 6)
        self.assertEqual(data["campaign-tags"][0], "valid-tag")
        self.assertEqual(data["campaign-tags"][1], "has spaces")
        self.assertEqual(data["campaign-tags"][5], "tag6")

    def test_template_id(self):
        message = AnymailMessage(
            to=["to@example.com"],
            template_id="welcome_template",
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["template-id"], "welcome_template")

    def test_merge_data_single_recipient(self):
        """Test merge_data with single recipient uses /send endpoint."""
        message = AnymailMessage(
            to=["alice@example.com"],
            subject="Hello",
            template_id="greeting",
            merge_data={
                "alice@example.com": {"name": "Alice", "order_no": "12345"},
            },
        )
        message.send()
        # Should use /send endpoint for single recipient
        self.assert_esp_called("/send")
        data = self.get_api_call_json()
        # With single recipient, merge_data goes to root variables
        self.assertEqual(data["variables"]["name"], "Alice")
        self.assertEqual(data["variables"]["order_no"], "12345")

    def test_merge_data_multiple_recipients(self):
        """Test merge_data with multiple recipients uses /send/bulk/email endpoint."""
        self.set_mock_response(raw=b"""{
            "channel": "email",
            "provider": "sweego",
            "swg_uids": {
                "alice@example.com": "02-uid-alice",
                "bob@example.com": "02-uid-bob"
            },
            "transaction_id": "tx-bulk-123"
        }""")
        message = AnymailMessage(
            to=["alice@example.com", "bob@example.com"],
            subject="Hello {{name}}",
            template_id="greeting",
            merge_data={
                "alice@example.com": {"name": "Alice", "order_no": "12345"},
                "bob@example.com": {"name": "Bob", "order_no": "67890"},
            },
        )
        message.send()
        # Should use /send/bulk/email endpoint for multiple recipients
        self.assert_esp_called("/send/bulk/email")
        data = self.get_api_call_json()
        # With multiple recipients, merge_data goes in each recipient's variables
        recipients = {r["email"]: r for r in data["recipients"]}
        self.assertEqual(recipients["alice@example.com"]["variables"]["name"], "Alice")
        self.assertEqual(recipients["alice@example.com"]["variables"]["order_no"], "12345")
        self.assertEqual(recipients["bob@example.com"]["variables"]["name"], "Bob")
        self.assertEqual(recipients["bob@example.com"]["variables"]["order_no"], "67890")

    def test_multiple_recipients_uses_bulk_endpoint(self):
        """Test that multiple recipients automatically use /send/bulk/email."""
        self.set_mock_response(raw=b"""{
            "channel": "email",
            "provider": "sweego",
            "swg_uids": {
                "to1@example.com": "02-uid-1",
                "to2@example.com": "02-uid-2"
            },
            "transaction_id": "tx-bulk-456"
        }""")
        message = AnymailMessage(
            to=["to1@example.com", "to2@example.com"],
            subject="Hello",
            body="Test message",
        )
        message.send()
        self.assert_esp_called("/send/bulk/email")

    def test_merge_global_data(self):
        message = AnymailMessage(
            to=["to@example.com"],
            template_id="welcome",
            merge_global_data={"company_name": "Acme Inc", "year": "2024"},
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["variables"]["company_name"], "Acme Inc")
        self.assertEqual(data["variables"]["year"], "2024")

    def test_merge_global_data_with_bulk(self):
        """Test merge_global_data is applied to all recipients in bulk mode."""
        self.set_mock_response(raw=b"""{
            "channel": "email",
            "provider": "sweego",
            "swg_uids": {
                "alice@example.com": "02-uid-alice",
                "bob@example.com": "02-uid-bob"
            },
            "transaction_id": "tx-bulk-789"
        }""")
        message = AnymailMessage(
            to=["alice@example.com", "bob@example.com"],
            template_id="welcome",
            merge_global_data={"company_name": "Acme Inc"},
            merge_data={
                "alice@example.com": {"name": "Alice"},
                "bob@example.com": {"name": "Bob"},
            },
        )
        message.send()
        data = self.get_api_call_json()
        recipients = {r["email"]: r for r in data["recipients"]}
        # Global data should be merged with per-recipient data
        self.assertEqual(recipients["alice@example.com"]["variables"]["company_name"], "Acme Inc")
        self.assertEqual(recipients["alice@example.com"]["variables"]["name"], "Alice")
        self.assertEqual(recipients["bob@example.com"]["variables"]["company_name"], "Acme Inc")
        self.assertEqual(recipients["bob@example.com"]["variables"]["name"], "Bob")

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call. (E.g., don't send tags: [] if there are no tags.)
        But required fields like channel and provider should be present.
        """
        self.message.send()
        data = self.get_api_call_json()
        # Required fields should always be present
        self.assertEqual(data["channel"], "email")
        self.assertEqual(data["provider"], "sweego")
        # Optional fields should not be present
        self.assertNotIn("template-id", data)
        self.assertNotIn("variables", data)
        self.assertNotIn("attachments", data)
        self.assertNotIn("inline", data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            "custom_field": "custom_value",
            "another_field": 123,
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["custom_field"], "custom_value")
        self.assertEqual(data["another_field"], 123)

    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message"""
        response_content = b"""{
            "channel": "email",
            "provider": "sweego",
            "swg_uids": {
                "to1@example.com": "02-uid-to1",
                "to2@example.com": "02-uid-to2"
            },
            "transaction_id": "tx-abc123"
        }"""
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com", "to2@example.com"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"queued"})
        # message_id is a set of all recipient message IDs
        self.assertEqual(
            msg.anymail_status.message_id, {"02-uid-to1", "02-uid-to2"}
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "02-uid-to1",
        )
        self.assertEqual(
            msg.anymail_status.recipients["to2@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to2@example.com"].message_id,
            "02-uid-to2",
        )
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    def test_inline_attachment_without_cid(self):
        """Inline attachments are converted to regular attachments.
        
        Sweego's /send API doesn't support inline attachments,
        so they are handled as regular attachments regardless of CID.
        """
        from anymail.backends.sweego import SweegoPayload
        from anymail.utils import Attachment
        from unittest.mock import MagicMock

        # Create a mock attachment that is inline but has no CID
        mock_att = MagicMock(spec=Attachment)
        mock_att.inline = True
        mock_att.cid = None
        mock_att.name = "image.png"
        mock_att.content_type = "image/png"
        mock_att.b64content = "base64content"

        # Create payload and test add_attachment directly
        backend = MagicMock()
        backend.api_key = "test_key"
        message = AnymailMessage(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )
        payload = SweegoPayload(message, {}, backend)

        # Should not raise - inline becomes regular attachment
        payload.add_attachment(mock_att)
        self.assertEqual(len(payload.data["attachments"]), 1)
        self.assertEqual(payload.data["attachments"][0]["filename"], "image.png")


@tag("sweego")
class SweegoBackendSessionSharingTestCase(
    SessionSharingTestCases, SweegoBackendMockAPITestCase
):
    """Test backend's use of Requests Session across sends"""

    pass  # tests are defined in the mixin
