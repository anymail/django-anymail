import os
import unittest
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin

ANYMAIL_TEST_RESEND_API_KEY = os.getenv("ANYMAIL_TEST_RESEND_API_KEY")
ANYMAIL_TEST_RESEND_DOMAIN = os.getenv("ANYMAIL_TEST_RESEND_DOMAIN")


@tag("resend", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_RESEND_API_KEY and ANYMAIL_TEST_RESEND_DOMAIN,
    "Set ANYMAIL_TEST_RESEND_API_KEY and ANYMAIL_TEST_RESEND_DOMAIN "
    "environment variables to run Resend integration tests",
)
@override_settings(
    ANYMAIL_RESEND_API_KEY=ANYMAIL_TEST_RESEND_API_KEY,
    EMAIL_BACKEND="anymail.backends.resend.EmailBackend",
)
class ResendBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Resend.com API integration tests

    Resend doesn't have sandbox so these tests run
    against the **live** Resend API, using the
    environment variable `ANYMAIL_TEST_RESEND_API_KEY` as the API key,
    and `ANYMAIL_TEST_RESEND_DOMAIN` to construct sender addresses.
    If those variables are not set, these tests won't run.

    """

    def setUp(self):
        super().setUp()
        self.from_email = "from@%s" % ANYMAIL_TEST_RESEND_DOMAIN
        self.message = AnymailMessage(
            "Anymail Resend integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Resend message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # Resend always queues
        self.assertGreater(len(message_id), 0)  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Resend all-options integration test",
            body="This is the text body",
            # Verify workarounds for address formatting issues:
            from_email=formataddr(("Test «Från», med komma", self.from_email)),
            to=["test+to1@anymail.dev", '"Recipient 2, OK?" <test+to2@anymail.dev>'],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=['"Reply, with comma" <reply@example.com>', "reply2@example.com"],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1", "tag 2"],
        )
        message.attach_alternative("<p>HTML content</p>", "text/html")

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        # Resend always queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertGreater(
            len(message.anymail_status.message_id), 0
        )  # non-empty string

    @unittest.skip("Resend has stopped responding to bad/missing API keys (12/2023)")
    @override_settings(ANYMAIL_RESEND_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaisesMessage(AnymailAPIError, "API key is invalid"):
            self.message.send()
