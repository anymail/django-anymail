import os
import unittest

from django.test import SimpleTestCase, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, override_settings, sample_image_path

ANYMAIL_TEST_SMTP2GO_API_KEY = os.getenv("ANYMAIL_TEST_SMTP2GO_API_KEY")
ANYMAIL_TEST_SMTP2GO_DOMAIN = os.getenv("ANYMAIL_TEST_SMTP2GO_DOMAIN")
ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID = os.getenv("ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID")


@tag("smtp2go", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_SMTP2GO_API_KEY and ANYMAIL_TEST_SMTP2GO_DOMAIN,
    "Set ANYMAIL_TEST_SMTP2GO_API_KEY and ANYMAIL_TEST_SMTP2GO_DOMAIN "
    "environment variables to run SMTP2GO integration tests",
)
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.smtp2go.EmailBackend",
            "OPTIONS": {"api_key": ANYMAIL_TEST_SMTP2GO_API_KEY},
        }
    }
)
class SMTP2GOBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Live SMTP2GO tests, sending real email to Anymail's test mailboxes."""

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage(
            "Anymail SMTP2GO integration test",
            "This is a test message from Anymail.",
            f"from@{ANYMAIL_TEST_SMTP2GO_DOMAIN}",
            ["test+to1@anymail.dev"],
        )

    def test_simple_send(self):
        self.assertEqual(self.message.send(), 1)
        self.assertEqual(self.message.anymail_status.status, {"queued"})
        self.assertIsInstance(self.message.anymail_status.message_id, str)
        self.assertTrue(self.message.anymail_status.message_id)

    def test_all_options(self):
        self.message.to = [
            "test+to1@anymail.dev",
            '"Recipient 2, OK?" <test+to2@anymail.dev>',
        ]
        self.message.cc = ["Copy <test+cc1@anymail.dev>"]
        self.message.bcc = ["test+bcc1@anymail.dev"]
        self.message.reply_to = ["Reply <reply@example.com>", "other@example.com"]
        self.message.extra_headers = {"X-Anymail-Test": "all-options"}
        self.message.attach("attachment.txt", "Text attachment ✓", "text/plain")
        cid = self.message.attach_inline_image_file(sample_image_path())
        self.message.attach_alternative(
            f'<p>HTML <img src="cid:{cid}"></p>', "text/html"
        )
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})
        self.assertEqual(len(self.message.anymail_status.recipients), 4)

    def test_batch(self):
        self.message.to = ["test+to1@anymail.dev", "test+to2@anymail.dev"]
        self.message.merge_headers = {
            "test+to1@anymail.dev": {"X-Anymail-Test": "recipient-one"},
            "test+to2@anymail.dev": {"X-Anymail-Test": "recipient-two"},
        }
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})
        self.assertNotEqual(
            self.message.anymail_status.recipients["test+to1@anymail.dev"].message_id,
            self.message.anymail_status.recipients["test+to2@anymail.dev"].message_id,
        )

    @unittest.skipUnless(
        ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID,
        "Set ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID to test SMTP2GO templates",
    )
    def test_template(self):
        self.message.template_id = ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID
        self.message.merge_global_data = {"name": "Anymail test"}
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})

    @override_settings(
        MAILERS={
            "default": {
                "BACKEND": "anymail.backends.smtp2go.EmailBackend",
                "OPTIONS": {"api_key": "invalid-api-key"},
            }
        }
    )
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError):
            self.message.send()
