"""
Sweego integration tests

These tests run against the live Sweego API, using the environment
variable `SWEEGO_API_KEY`. If that variable is not set, these tests are skipped.

To run the tests:
    export SWEEGO_API_KEY="your-api-key"
    export SWEEGO_TEST_FROM_EMAIL="sender@your-verified-domain.com"
    export ANYMAIL_TEST_EMAIL_TO="recipient@example.com"
    python -m pytest tests/test_sweego_integration.py

For bulk tests with different recipients:
    export ANYMAIL_TEST_EMAIL_TO_2="second-recipient@example.com"

The integration tests will send real emails to addresses you control.
You'll need to set the environment variables:
- SWEEGO_API_KEY: Your Sweego API key
- SWEEGO_TEST_FROM_EMAIL: A sender address from a verified domain in your Sweego account
- ANYMAIL_TEST_EMAIL_TO: The email address where you want to receive test messages
- ANYMAIL_TEST_EMAIL_TO_2: (Optional) Second email for bulk tests
"""

import os
import unittest

from django.test import SimpleTestCase, override_settings, tag

from anymail.message import AnymailMessage

SWEEGO_API_KEY = os.getenv("SWEEGO_API_KEY")
SWEEGO_TEST_FROM_EMAIL = os.getenv("SWEEGO_TEST_FROM_EMAIL")
ANYMAIL_TEST_EMAIL_TO = os.getenv("ANYMAIL_TEST_EMAIL_TO")
ANYMAIL_TEST_EMAIL_TO_2 = os.getenv("ANYMAIL_TEST_EMAIL_TO_2")


@tag("sweego", "live")
@unittest.skipUnless(
    SWEEGO_API_KEY and SWEEGO_TEST_FROM_EMAIL and ANYMAIL_TEST_EMAIL_TO,
    "Set SWEEGO_API_KEY, SWEEGO_TEST_FROM_EMAIL, and ANYMAIL_TEST_EMAIL_TO "
    "environment variables to run Sweego integration tests",
)
@override_settings(
    EMAIL_BACKEND="anymail.backends.sweego.EmailBackend",
    ANYMAIL={
        "SWEEGO_API_KEY": SWEEGO_API_KEY,
    },
)
class SweegoBackendIntegrationTests(SimpleTestCase):
    """Sweego API integration tests

    These tests run against the **live** Sweego API.
    """

    def setUp(self):
        self.from_email = SWEEGO_TEST_FROM_EMAIL
        self.to_email = ANYMAIL_TEST_EMAIL_TO
        # Use second email if available, otherwise use same email
        self.to_email_2 = ANYMAIL_TEST_EMAIL_TO_2 or ANYMAIL_TEST_EMAIL_TO

    def test_simple_send(self):
        """Test simple email send"""
        message = AnymailMessage(
            subject="Anymail Sweego integration test",
            body="This is a test email sent via the Sweego API.",
            from_email=self.from_email,
            to=[self.to_email],
        )
        message.send()

        # Verify the anymail_status is set
        self.assertIsNotNone(message.anymail_status)
        self.assertIn("queued", message.anymail_status.status)
        self.assertIsNotNone(message.anymail_status.message_id)

    def test_send_with_html(self):
        """Test sending HTML email"""
        message = AnymailMessage(
            subject="Anymail Sweego HTML test",
            body="This is the text version.",
            from_email=self.from_email,
            to=[self.to_email],
        )
        message.attach_alternative(
            "<html><body><h1>HTML Version</h1><p>This is the HTML version.</p></body></html>",
            "text/html",
        )
        message.send()
        self.assertIsNotNone(message.anymail_status.message_id)

    def test_send_with_attachment(self):
        """Test sending email with attachment"""
        message = AnymailMessage(
            subject="Anymail Sweego attachment test",
            body="This email has an attachment.",
            from_email=self.from_email,
            to=[self.to_email],
        )
        message.attach("test.txt", "This is a test attachment.", "text/plain")
        message.send()
        self.assertIsNotNone(message.anymail_status.message_id)

    def test_send_with_metadata_and_tags(self):
        """Test sending with metadata and tags"""
        message = AnymailMessage(
            subject="Anymail Sweego metadata test",
            body="This email has metadata and tags.",
            from_email=self.from_email,
            to=[self.to_email],
        )
        message.metadata = {"user_id": "test123", "campaign": "integration_test"}
        message.tags = ["test", "integration"]
        message.send()
        self.assertIsNotNone(message.anymail_status.message_id)

    @unittest.skip("Requires a valid template_id configured in your Sweego account")
    def test_send_with_template(self):
        """Test sending with template"""
        message = AnymailMessage(
            from_email=self.from_email,
            to=[self.to_email],
            template_id="your_template_id",  # Replace with actual template ID
        )
        message.merge_data = {
            self.to_email: {"name": "Test User", "company": "Test Company"}
        }
        message.send()
        self.assertIsNotNone(message.anymail_status.message_id)

    def test_send_to_multiple_recipients(self):
        """Test sending to multiple recipients uses bulk endpoint.

        With 2+ recipients, Sweego backend uses /send/bulk/email
        so each recipient receives an individual email.
        """
        message = AnymailMessage(
            subject="Anymail Sweego multiple recipients test",
            body="This email is sent to multiple recipients individually.",
            from_email=self.from_email,
            to=[self.to_email, self.to_email_2],
        )
        message.send()
        self.assertIsNotNone(message.anymail_status.message_id)
        # Each recipient should have their own swg_uid
        for recipient in message.anymail_status.recipients.values():
            self.assertIsNotNone(recipient.message_id)

    def test_send_bulk_with_merge_data(self):
        """Test bulk sending with per-recipient variables.

        This test verifies that /send/bulk/email correctly handles
        merge_data with different variables for each recipient.
        """
        message = AnymailMessage(
            subject="Anymail Sweego bulk test for {{name}}",
            body="Hello {{name}}, your code is {{code}}.",
            from_email=self.from_email,
            to=[self.to_email, self.to_email_2],
            merge_data={
                self.to_email: {"name": "Alice", "code": "ALICE123"},
                self.to_email_2: {"name": "Bob", "code": "BOB456"},
            },
            merge_global_data={"company": "Sweego"},
        )
        message.send()
        self.assertIsNotNone(message.anymail_status.message_id)
        self.assertEqual(message.anymail_status.status, {"queued"})
