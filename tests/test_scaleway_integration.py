import os
import unittest

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin

ANYMAIL_TEST_SCALEWAY_SECRET_KEY = os.getenv("ANYMAIL_TEST_SCALEWAY_SECRET_KEY")
ANYMAIL_TEST_SCALEWAY_PROJECT_ID = os.getenv("ANYMAIL_TEST_SCALEWAY_PROJECT_ID")
ANYMAIL_TEST_SCALEWAY_DOMAIN = os.getenv("ANYMAIL_TEST_SCALEWAY_DOMAIN")


@tag("scaleway", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_SCALEWAY_SECRET_KEY
    and ANYMAIL_TEST_SCALEWAY_PROJECT_ID
    and ANYMAIL_TEST_SCALEWAY_DOMAIN,
    "Set ANYMAIL_TEST_SCALEWAY_SECRET_KEY, ANYMAIL_TEST_SCALEWAY_PROJECT_ID, and "
    "ANYMAIL_TEST_SCALEWAY_DOMAIN environment variables to run Scaleway integration tests",
)
@override_settings(
    ANYMAIL={
        "SCALEWAY_SECRET_KEY": ANYMAIL_TEST_SCALEWAY_SECRET_KEY,
        "SCALEWAY_PROJECT_ID": ANYMAIL_TEST_SCALEWAY_PROJECT_ID,
    },
    EMAIL_BACKEND="anymail.backends.scaleway.EmailBackend",
)
class ScalewayIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Scaleway API integration tests

    These tests run against the **live** Scaleway API, using the
    environment variables to authorize.
    If those variables are not set, these tests will be skipped.
    """

    esp_name = "Scaleway"

    def setUp(self):
        super().setUp()
        self.from_email = f"from@{ANYMAIL_TEST_SCALEWAY_DOMAIN}"
        self.message = AnymailMessage(
            subject="Anymail Scaleway integration test",
            body="This is a test message from Anymail.",
            from_email=self.from_email,
            to=["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        """Test basic sending."""
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})
        self.assertIsNotNone(self.message.anymail_status.message_id)

    def test_all_options(self):
        """Test sending with all available options."""
        message = AnymailMessage(
            subject="Anymail Scaleway all-options test",
            body="This is a test message from Anymail.",
            from_email=f"from@{ANYMAIL_TEST_SCALEWAY_DOMAIN}",
            to=["test+to1@anymail.dev", '"Recipient 2, OK?" <test+to2@anymail.dev>'],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={"X-Anymail-Test": "all-options", "X-Anymail-Count": 3},
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1", "tag 2"],
        )
        message.attach_alternative("<p>HTML content</p>", "text/html")
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        self.assertEqual(len(message.anymail_status.recipients), 6)
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertIsNotNone(message.anymail_status.message_id)

    def test_invalid_from(self):
        self.message.from_email = "webmaster@localhost"
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 400)
        self.assertIn("Invalid email from address", str(err))

    @override_settings(
        ANYMAIL={
            "SCALEWAY_SECRET_KEY": "Hey, that's not a secret key",
            "SCALEWAY_PROJECT_ID": "not-a-project-id",
        }
    )
    def test_invalid_secret_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        self.assertIn("authentication is denied", str(err))
