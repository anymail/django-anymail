import os
import unittest
from datetime import datetime, timedelta
from email.headerregistry import Address

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin

ANYMAIL_TEST_UNISENDER_GO_API_KEY = os.getenv("ANYMAIL_TEST_UNISENDER_GO_API_KEY")
ANYMAIL_TEST_UNISENDER_GO_API_URL = os.getenv("ANYMAIL_TEST_UNISENDER_GO_API_URL")
ANYMAIL_TEST_UNISENDER_GO_DOMAIN = os.getenv("ANYMAIL_TEST_UNISENDER_GO_DOMAIN")
ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID = os.getenv(
    "ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID"
)


@tag("unisender_go", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_UNISENDER_GO_API_KEY
    and ANYMAIL_TEST_UNISENDER_GO_API_URL
    and ANYMAIL_TEST_UNISENDER_GO_DOMAIN,
    "Set ANYMAIL_TEST_UNISENDER_GO_API_KEY, ANYMAIL_TEST_UNISENDER_GO_API_URL"
    " and ANYMAIL_TEST_UNISENDER_GO_DOMAIN environment variables to run Unisender Go"
    " integration tests",
)
@override_settings(
    ANYMAIL_UNISENDER_GO_API_KEY=ANYMAIL_TEST_UNISENDER_GO_API_KEY,
    ANYMAIL_UNISENDER_GO_API_URL=ANYMAIL_TEST_UNISENDER_GO_API_URL,
    EMAIL_BACKEND="anymail.backends.unisender_go.EmailBackend",
)
class UnisenderGoBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """
    Unisender Go API integration tests

    These tests run against the **live** Unisender Go API, using the
    environment variable `ANYMAIL_TEST_UNISENDER_GO_API_KEY` as the API key,
    `ANYMAIL_UNISENDER_GO_API_URL` as the API URL where that key was issued,
    and `ANYMAIL_TEST_UNISENDER_GO_DOMAIN` to construct the sender addresses.
    If any of those variables are not set, these tests won't run.

    To run the template test, also set ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID
    to a valid template in your account.

    The tests send actual email to a sink address at anymail.dev.
    """

    def setUp(self):
        super().setUp()
        self.from_email = f"from@{ANYMAIL_TEST_UNISENDER_GO_DOMAIN}"
        self.message = AnymailMessage(
            "Anymail Unisender Go integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Unisender Go send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # Unisender Go always queues
        self.assertRegex(message_id, r".+")
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now() + timedelta(minutes=2)
        message = AnymailMessage(
            subject="Anymail Unisender Go all-options integration test",
            body="This is the text body",
            from_email=str(
                Address(display_name="Test From, with comma", addr_spec=self.from_email)
            ),
            to=["test+to1@anymail.dev", '"Recipient 2, OK?" <test+to2@anymail.dev>'],
            # Unisender Go doesn't support cc or bcc:
            # cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            # bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            # Unisender Go only supports a single reply-to:
            reply_to=['"Reply, with comma" <reply@example.com>'],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            metadata={"meta1": "simple string", "meta2": 2},
            send_at=send_at,
            tags=["tag 1", "tag 2"],
            track_opens=False,
            track_clicks=False,
            esp_extra={
                "global_language": "en",
                "options": {"unsubscribe_url": "https://example.com/unsubscribe?id=1"},
            },
        )
        message.attach_alternative("<p>HTML content</p>", "text/html")
        message.attach_alternative("<p>AMP HTML content</p>", "text/x-amp-html")

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        self.assertEqual(message.anymail_status.status, {"queued"})
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "queued")
        self.assertRegex(recipient_status["test+to1@anymail.dev"].message_id, r".+")
        self.assertRegex(recipient_status["test+to2@anymail.dev"].message_id, r".+")
        # Anymail generates unique message_id for each recipient:
        self.assertNotEqual(
            recipient_status["test+to1@anymail.dev"].message_id,
            recipient_status["test+to2@anymail.dev"].message_id,
        )

    @unittest.skipUnless(
        ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID,
        "Set ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID to run the"
        " Unisender Go template integration test",
    )
    def test_template(self):
        """
        To run this test, create a template in your account containing
        "{{order_id}}" and "{{ship_date}}" substitutions, and set
        ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID to the template's id.
        """
        message = AnymailMessage(
            # This is an actual template in the Anymail test account:
            template_id=ANYMAIL_TEST_UNISENDER_GO_TEMPLATE_ID,
            to=["Recipient 1 <test+to1@anymail.dev>", "test+to2@anymail.dev"],
            reply_to=["Do not reply <reply@example.dev>"],
            tags=["using-template"],
            merge_data={
                "test+to1@anymail.dev": {"order_id": "12345"},
                "test+to2@anymail.dev": {"order_id": "23456"},
            },
            merge_global_data={"ship_date": "yesterday"},
            metadata={"customer-id": "unknown", "meta2": 2},
            merge_metadata={
                "test+to1@anymail.dev": {"customer-id": "ZXK9123"},
                "test+to2@anymail.dev": {"customer-id": "ZZT4192"},
            },
        )
        message.from_email = None  # use template sender
        message.attach("attachment1.txt", "Here is some\ntext", "text/plain")

        message.send()
        # Unisender Go always queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "queued")
        self.assertRegex(recipient_status["test+to1@anymail.dev"].message_id, r".+")
        self.assertRegex(recipient_status["test+to2@anymail.dev"].message_id, r".+")
        # Anymail generates unique message_id for each recipient:
        self.assertNotEqual(
            recipient_status["test+to1@anymail.dev"].message_id,
            recipient_status["test+to2@anymail.dev"].message_id,
        )

    @override_settings(ANYMAIL_UNISENDER_GO_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        # Make sure the exception message includes Unisender Go's response:
        with self.assertRaisesMessage(AnymailAPIError, "Can not decode key"):
            self.message.send()
