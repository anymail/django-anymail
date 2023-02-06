import os
import unittest
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

# For most integration tests, Postmark's sandboxed "POSTMARK_API_TEST" token is used.
# But to test template sends, a real Postmark server token and template id are needed:
ANYMAIL_TEST_POSTMARK_SERVER_TOKEN = os.getenv("ANYMAIL_TEST_POSTMARK_SERVER_TOKEN")
ANYMAIL_TEST_POSTMARK_TEMPLATE_ID = os.getenv("ANYMAIL_TEST_POSTMARK_TEMPLATE_ID")
ANYMAIL_TEST_POSTMARK_DOMAIN = os.getenv("ANYMAIL_TEST_POSTMARK_DOMAIN")


@tag("postmark", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_POSTMARK_DOMAIN,
    "Set ANYMAIL_TEST_POSTMARK_DOMAIN environment variable "
    "to run Postmark template integration tests",
)
@override_settings(
    ANYMAIL_POSTMARK_SERVER_TOKEN="POSTMARK_API_TEST",
    EMAIL_BACKEND="anymail.backends.postmark.EmailBackend",
)
class PostmarkBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Postmark API integration tests

    These tests run against the **live** Postmark API, but using a
    test key that's not capable of sending actual email.
    """

    def setUp(self):
        super().setUp()
        self.from_email = "from@%s" % ANYMAIL_TEST_POSTMARK_DOMAIN
        self.message = AnymailMessage(
            "Anymail Postmark integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Postmark send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "sent")
        self.assertGreater(len(message_id), 0)  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Postmark all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From, with comma", self.from_email)),
            to=["test+to1@anymail.dev", "Recipient 2 <test+to2@anymail.dev>"],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={"X-Anymail-Test": "value"},
            # no send_at support
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1"],  # max one tag
            track_opens=True,
            track_clicks=True,
            merge_data={},  # force batch send (distinct message for each `to`)
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
        self.assertEqual(message.anymail_status.status, {"sent"})
        self.assertEqual(
            message.anymail_status.recipients["test+to1@anymail.dev"].status, "sent"
        )
        self.assertEqual(
            message.anymail_status.recipients["test+to2@anymail.dev"].status, "sent"
        )
        # distinct messages should have different message_ids:
        self.assertNotEqual(
            message.anymail_status.recipients["test+to1@anymail.dev"].message_id,
            message.anymail_status.recipients["test+to2@anymail.dev"].message_id,
        )

    def test_invalid_from(self):
        self.message.from_email = "webmaster@localhost"  # Django's default From
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 422)
        self.assertIn("Invalid 'From' address", str(err))

    @unittest.skipUnless(
        ANYMAIL_TEST_POSTMARK_SERVER_TOKEN
        and ANYMAIL_TEST_POSTMARK_TEMPLATE_ID
        and ANYMAIL_TEST_POSTMARK_DOMAIN,
        "Set ANYMAIL_TEST_POSTMARK_SERVER_TOKEN and ANYMAIL_TEST_POSTMARK_TEMPLATE_ID "
        "and ANYMAIL_TEST_POSTMARK_DOMAIN environment variables to run Postmark "
        "template integration tests",
    )
    @override_settings(ANYMAIL_POSTMARK_SERVER_TOKEN=ANYMAIL_TEST_POSTMARK_SERVER_TOKEN)
    def test_template(self):
        message = AnymailMessage(
            from_email=self.from_email,
            to=["test+to1@anymail.dev", "Second Recipient <test+to2@anymail.dev>"],
            template_id=ANYMAIL_TEST_POSTMARK_TEMPLATE_ID,
            merge_data={
                "test+to1@anymail.dev": {"name": "Recipient 1", "order_no": "12345"},
                "test+to2@anymail.dev": {"order_no": "6789"},
            },
            merge_global_data={"name": "Valued Customer"},
        )
        message.send()
        self.assertEqual(message.anymail_status.status, {"sent"})

    @override_settings(ANYMAIL_POSTMARK_SERVER_TOKEN="Hey, that's not a server token!")
    def test_invalid_server_token(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Make sure the exception message includes Postmark's response:
        self.assertIn("Please verify that you are using a valid token", str(err))
