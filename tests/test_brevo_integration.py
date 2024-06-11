import os
import unittest
from datetime import datetime, timedelta
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin

ANYMAIL_TEST_BREVO_API_KEY = os.getenv("ANYMAIL_TEST_BREVO_API_KEY")
ANYMAIL_TEST_BREVO_DOMAIN = os.getenv("ANYMAIL_TEST_BREVO_DOMAIN")


@tag("brevo", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_BREVO_API_KEY and ANYMAIL_TEST_BREVO_DOMAIN,
    "Set ANYMAIL_TEST_BREVO_API_KEY and ANYMAIL_TEST_BREVO_DOMAIN "
    "environment variables to run Brevo integration tests",
)
@override_settings(
    ANYMAIL_BREVO_API_KEY=ANYMAIL_TEST_BREVO_API_KEY,
    ANYMAIL_BREVO_SEND_DEFAULTS=dict(),
    EMAIL_BACKEND="anymail.backends.brevo.EmailBackend",
)
class BrevoBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Brevo v3 API integration tests

    Brevo doesn't have sandbox so these tests run
    against the **live** Brevo API, using the
    environment variable `ANYMAIL_TEST_BREVO_API_KEY` as the API key,
    and `ANYMAIL_TEST_BREVO_DOMAIN` to construct sender addresses.
    If those variables are not set, these tests won't run.

    https://developers.brevo.com/docs/faq#how-can-i-test-the-api

    """

    def setUp(self):
        super().setUp()
        self.from_email = "from@%s" % ANYMAIL_TEST_BREVO_DOMAIN
        self.message = AnymailMessage(
            "Anymail Brevo integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Brevo send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # Brevo always queues
        # Message-ID can be ...@smtp-relay.mail.fr or .sendinblue.com:
        self.assertRegex(message_id, r"\<.+@.+\>")
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now() + timedelta(minutes=2)
        message = AnymailMessage(
            subject="Anymail Brevo all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From, with comma", self.from_email)),
            to=["test+to1@anymail.dev", '"Recipient 2, OK?" <test+to2@anymail.dev>'],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            # Brevo API v3 only supports single reply-to
            reply_to=['"Reply, with comma" <reply@example.com>'],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            metadata={"meta1": "simple string", "meta2": 2},
            send_at=send_at,
            tags=["tag 1", "tag 2"],
        )
        # Brevo requires an HTML body:
        message.attach_alternative("<p>HTML content</p>", "text/html")

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        # Brevo always queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertRegex(message.anymail_status.message_id, r"\<.+@.+\>")

    def test_template(self):
        message = AnymailMessage(
            # There is a *new-style* template with this id in the Anymail test account:
            template_id=5,
            # Override template sender:
            from_email=formataddr(("Sender", self.from_email)),
            to=["Recipient 1 <test+to1@anymail.dev>", "test+to2@anymail.dev"],
            reply_to=["Do not reply <reply@example.dev>"],
            tags=["using-template"],
            # The Anymail test template includes `{{ params.SHIP_DATE }}`
            # and `{{ params.ORDER_ID }}` substitutions
            merge_data={
                "test+to1@anymail.dev": {"ORDER_ID": "12345"},
                "test+to2@anymail.dev": {"ORDER_ID": "23456"},
            },
            merge_global_data={"SHIP_DATE": "yesterday"},
            metadata={"customer-id": "unknown", "meta2": 2},
            merge_metadata={
                "test+to1@anymail.dev": {"customer-id": "ZXK9123"},
                "test+to2@anymail.dev": {"customer-id": "ZZT4192"},
            },
            headers={
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
            },
            merge_headers={
                "test+to1@anymail.dev": {
                    "List-Unsubscribe": "<https://example.com/a/>",
                },
                "test+to2@anymail.dev": {
                    "List-Unsubscribe": "<https://example.com/b/>",
                },
            },
        )

        message.attach("attachment1.txt", "Here is some\ntext", "text/plain")

        message.send()
        # Brevo always queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "queued")
        self.assertRegex(
            recipient_status["test+to1@anymail.dev"].message_id, r"\<.+@.+\>"
        )
        self.assertRegex(
            recipient_status["test+to2@anymail.dev"].message_id, r"\<.+@.+\>"
        )
        # Each recipient gets their own message_id:
        self.assertNotEqual(
            recipient_status["test+to1@anymail.dev"].message_id,
            recipient_status["test+to2@anymail.dev"].message_id,
        )

    @override_settings(ANYMAIL_BREVO_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Make sure the exception message includes Brevo's response:
        self.assertIn("Key not found", str(err))
