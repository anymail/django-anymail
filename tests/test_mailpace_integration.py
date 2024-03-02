import os
import unittest
from email.headerregistry import Address

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_MAILPACE_SERVER_TOKEN = os.getenv("ANYMAIL_TEST_MAILPACE_SERVER_TOKEN")
ANYMAIL_TEST_MAILPACE_DOMAIN = os.getenv("ANYMAIL_TEST_MAILPACE_DOMAIN")


@tag("mailpace", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILPACE_SERVER_TOKEN and ANYMAIL_TEST_MAILPACE_DOMAIN,
    "Set ANYMAIL_TEST_MAILPACE_SERVER_TOKEN and ANYMAIL_TEST_MAILPACE_DOMAIN"
    " environment variables to run MailPace integration tests",
)
@override_settings(
    ANYMAIL_MAILPACE_SERVER_TOKEN=ANYMAIL_TEST_MAILPACE_SERVER_TOKEN,
    EMAIL_BACKEND="anymail.backends.mailpace.EmailBackend",
)
class MailPaceBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """
    MailPace API integration tests

    These tests run against the **live** MailPace API, using the
    environment variable `ANYMAIL_TEST_MAILPACE_SERVER_TOKEN` as the API key,
    and `ANYMAIL_TEST_MAILPACE_DOMAIN` to construct sender addresses.
    If those variables are not set, these tests won't run.
    """

    def setUp(self):
        super().setUp()
        self.from_email = str(
            Address(username="from", domain=ANYMAIL_TEST_MAILPACE_DOMAIN)
        )
        self.message = AnymailMessage(
            "Anymail MailPace integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the MailPace send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")
        self.assertGreater(message_id, 0)  # integer MailPace reference ID
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail MailPace all-options integration test",
            body="This is the text body",
            from_email=str(
                Address(
                    display_name="Test From, with comma",
                    username="sender",
                    domain=ANYMAIL_TEST_MAILPACE_DOMAIN,
                )
            ),
            to=[
                "test+to1@anymail.dev",
                '"Recipient 2, with comma" <test+to2@anymail.dev>',
            ],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={"List-Unsubscribe": "<https://example.com/unsub?id=123>"},
            tags=["tag 1", "tag 2"],
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")
        cid = message.attach_inline_image_file(sample_image_path())
        message.attach_alternative(
            "<p><b>HTML:</b> with <a href='http://example.com'>link</a>"
            "and image: <img src='cid:%s'></div>" % cid,
            "text/html",
        )

        message.send()
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertEqual(
            message.anymail_status.recipients["test+to1@anymail.dev"].status, "queued"
        )
        self.assertEqual(
            message.anymail_status.recipients["test+to2@anymail.dev"].status, "queued"
        )

    def test_invalid_from(self):
        self.message.from_email = "webmaster@localhost"  # Django's default From
        with self.assertRaisesMessage(
            AnymailAPIError, "does not match domain in From field (localhost)"
        ):
            self.message.send()

    @override_settings(ANYMAIL_MAILPACE_SERVER_TOKEN="Hey, that's not a server token!")
    def test_invalid_server_token(self):
        with self.assertRaisesMessage(AnymailAPIError, "Invalid API Token"):
            self.message.send()
