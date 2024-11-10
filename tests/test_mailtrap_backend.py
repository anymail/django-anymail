import unittest
from datetime import datetime
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag
from django.utils.timezone import timezone

from anymail.exceptions import (
    AnymailAPIError,
    AnymailRecipientsRefused,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import attach_inline_image

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import AnymailTestMixin, sample_image_content


@tag("mailtrap")
@override_settings(
    EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend",
    ANYMAIL={"MAILTRAP_API_TOKEN": "test_api_token"},
)
class MailtrapBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "success": true,
        "message_ids": ["1df37d17-0286-4d8b-8edf-bc4ec5be86e6"]
    }"""

    def setUp(self):
        super().setUp()
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )

    def test_send_email(self):
        """Test sending a basic email"""
        response = self.message.send()
        self.assertEqual(response, 1)
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")

    def test_send_with_attachments(self):
        """Test sending an email with attachments"""
        self.message.attach("test.txt", "This is a test", "text/plain")
        response = self.message.send()
        self.assertEqual(response, 1)
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")

    def test_send_with_inline_image(self):
        """Test sending an email with inline images"""
        image_data = sample_image_content()  # Read from a png file

        cid = attach_inline_image(self.message, image_data)
        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        response = self.message.send()
        self.assertEqual(response, 1)
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")

    def test_send_with_metadata(self):
        """Test sending an email with metadata"""
        self.message.metadata = {"user_id": "12345"}
        response = self.message.send()
        self.assertEqual(response, 1)
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")

    def test_send_with_tag(self):
        """Test sending an email with one tag"""
        self.message.tags = ["tag1"]
        response = self.message.send()
        self.assertEqual(response, 1)
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")

    def test_send_with_tags(self):
        """Test sending an email with tags"""
        self.message.tags = ["tag1", "tag2"]
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_send_with_template(self):
        """Test sending an email with a template"""
        self.message.template_id = "template_id"
        response = self.message.send()
        self.assertEqual(response, 1)
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")

    def test_send_with_merge_data(self):
        """Test sending an email with merge data"""
        self.message.merge_data = {"to@example.com": {"name": "Recipient"}}
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_send_with_invalid_api_token(self):
        """Test sending an email with an invalid API token"""
        self.set_mock_response(status_code=401, raw=b'{"error": "Invalid API token"}')
        with self.assertRaises(AnymailAPIError):
            self.message.send()

    def test_send_with_serialization_error(self):
        """Test sending an email with a serialization error"""
        self.message.extra_headers = {
            "foo": Decimal("1.23")
        }  # Decimal can't be serialized
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
        err = cm.exception
        self.assertIsInstance(err, TypeError)
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")

    def test_send_with_api_error(self):
        """Test sending an email with a generic API error"""
        self.set_mock_response(
            status_code=500, raw=b'{"error": "Internal server error"}'
        )
        with self.assertRaises(AnymailAPIError):
            self.message.send()

    def test_send_with_headers_and_recipients(self):
        """Test sending an email with headers and multiple recipients"""
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com", "Also To <to2@example.com>"],
            bcc=["bcc1@example.com", "Also BCC <bcc2@example.com>"],
            cc=["cc1@example.com", "Also CC <cc2@example.com>"],
            headers={
                "Reply-To": "another@example.com",
                "X-MyHeader": "my value",
                "Message-ID": "mycustommsgid@example.com",
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject")
        self.assertEqual(data["text"], "Body goes here")
        self.assertEqual(data["from"]["email"], "from@example.com")
        self.assertEqual(
            data["headers"],
            {
                "Reply-To": "another@example.com",
                "X-MyHeader": "my value",
                "Message-ID": "mycustommsgid@example.com",
            },
        )
        # Verify recipients correctly identified as "to", "cc", or "bcc"
        self.assertEqual(
            data["to"],
            [
                {"email": "to1@example.com"},
                {"email": "to2@example.com", "name": "Also To"},
            ],
        )
        self.assertEqual(
            data["cc"],
            [
                {"email": "cc1@example.com"},
                {"email": "cc2@example.com", "name": "Also CC"},
            ],
        )
        self.assertEqual(
            data["bcc"],
            [
                {"email": "bcc1@example.com"},
                {"email": "bcc2@example.com", "name": "Also BCC"},
            ],
        )


@tag("mailtrap")
class MailtrapBackendAnymailFeatureTests(MailtrapBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "envelope@example.com"
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345"}
        response = self.message.send()
        self.assertEqual(response, 1)
        data = self.get_api_call_json()
        self.assertEqual(data["custom_variables"], {"user_id": "12345"})

    def test_send_at(self):
        send_at = datetime(2023, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.message.send_at = send_at
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["tag1"]
        response = self.message.send()
        self.assertEqual(response, 1)
        data = self.get_api_call_json()
        self.assertEqual(data["category"], "tag1")

    def test_tracking(self):
        self.message.track_clicks = True
        self.message.track_opens = True
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_template_id(self):
        self.message.template_id = "template_id"
        response = self.message.send()
        self.assertEqual(response, 1)
        data = self.get_api_call_json()
        self.assertEqual(data["template_uuid"], "template_id")

    def test_merge_data(self):
        self.message.merge_data = {"to@example.com": {"name": "Recipient"}}
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_merge_global_data(self):
        self.message.merge_global_data = {"global_name": "Global Recipient"}
        response = self.message.send()
        self.assertEqual(response, 1)
        data = self.get_api_call_json()
        self.assertEqual(
            data["template_variables"], {"global_name": "Global Recipient"}
        )

    def test_esp_extra(self):
        self.message.esp_extra = {"custom_option": "value"}
        response = self.message.send()
        self.assertEqual(response, 1)
        data = self.get_api_call_json()
        self.assertEqual(data["custom_option"], "value")


@tag("mailtrap")
class MailtrapBackendRecipientsRefusedTests(MailtrapBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid
    """

    @unittest.skip("TODO: is this test correct/necessary?")
    def test_recipients_refused(self):
        self.set_mock_response(
            status_code=400, raw=b'{"error": "All recipients refused"}'
        )
        with self.assertRaises(AnymailRecipientsRefused):
            self.message.send()

    @unittest.skip(
        "TODO: is this test correct/necessary? How to handle this in mailtrap backend?"
    )
    def test_fail_silently(self):
        self.set_mock_response(
            status_code=400, raw=b'{"error": "All recipients refused"}'
        )
        self.message.fail_silently = True
        sent = self.message.send()
        self.assertEqual(sent, 0)


@tag("mailtrap")
class MailtrapBackendSessionSharingTestCase(
    SessionSharingTestCases, MailtrapBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mailtrap")
@override_settings(EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend")
class MailtrapBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_token(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bMAILTRAP_API_TOKEN\b")
        self.assertRegex(errmsg, r"\bANYMAIL_MAILTRAP_API_TOKEN\b")
