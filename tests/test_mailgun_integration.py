import os
import unittest
from datetime import datetime, timedelta
from email.utils import formataddr

from django.test import SimpleTestCase, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, override_settings, sample_image_path

ANYMAIL_TEST_MAILGUN_API_KEY = os.getenv("ANYMAIL_TEST_MAILGUN_API_KEY")
ANYMAIL_TEST_MAILGUN_DOMAIN = os.getenv("ANYMAIL_TEST_MAILGUN_DOMAIN")


@tag("mailgun", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILGUN_API_KEY and ANYMAIL_TEST_MAILGUN_DOMAIN,
    "Set ANYMAIL_TEST_MAILGUN_API_KEY and ANYMAIL_TEST_MAILGUN_DOMAIN environment"
    " variables to run Mailgun integration tests",
)
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.mailgun.EmailBackend",
            "OPTIONS": {
                "api_key": ANYMAIL_TEST_MAILGUN_API_KEY,
                "sender_domain": ANYMAIL_TEST_MAILGUN_DOMAIN,
                "send_defaults": {"esp_extra": {"o:testmode": "yes"}},
            },
        },
    },
)
class MailgunBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Mailgun API integration tests

    These tests run against the **live** Mailgun API, using the
    environment variable `ANYMAIL_TEST_MAILGUN_API_KEY` as the API key
    and `ANYMAIL_TEST_MAILGUN_DOMAIN` as the sender domain.
    If those variables are not set, these tests won't run.

    """

    def setUp(self):
        super().setUp()
        self.from_email = "from@%s" % ANYMAIL_TEST_MAILGUN_DOMAIN
        self.message = AnymailMessage(
            "Anymail Mailgun integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Mailgun send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # Mailgun always queues
        # don't know what it'll be, but it should exist:
        self.assertGreater(len(message_id), 0)

        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now().replace(microsecond=0) + timedelta(minutes=2)
        from_email = formataddr(("Test From, with comma", self.from_email))
        message = AnymailMessage(
            subject="Anymail Mailgun all-options integration test",
            body="This is the text body",
            from_email=from_email,
            to=["test+to1@anymail.dev", "Recipient 2 <test+to2@anymail.dev>"],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={"X-Anymail-Test": "value"},
            metadata={"meta1": "simple string", "meta2": 2},
            send_at=send_at,
            tags=["tag 1", "tag 2"],
            track_clicks=False,
            track_opens=True,
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("vedhæftet fil.csv", "ID,Name\n1,3", "text/csv")
        cid = message.attach_inline_image_file(
            sample_image_path(), domain=ANYMAIL_TEST_MAILGUN_DOMAIN
        )
        message.attach_alternative(
            "<div>This is the <i>html</i> body <img src='cid:%s'></div>" % cid,
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
        # single message should have the same message_id for each recipient:
        self.assertEqual(
            message.anymail_status.recipients["test+to1@anymail.dev"].message_id,
            message.anymail_status.recipients["test+to2@anymail.dev"].message_id,
        )

    def test_per_recipient_options(self):
        message = AnymailMessage(
            from_email=formataddr(("Test From", self.from_email)),
            to=["test+to1@anymail.dev", '"Recipient 2" <test+to2@anymail.dev>'],
            subject="Anymail Mailgun per-recipient options test",
            body="This is the text body",
            merge_metadata={
                "test+to1@anymail.dev": {"meta1": "one", "meta2": "two"},
                "test+to2@anymail.dev": {"meta1": "recipient 2"},
            },
            headers={
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
                "X-Custom-Header": "default",
            },
            merge_headers={
                "test+to1@anymail.dev": {
                    "List-Unsubscribe": "<https://example.com/a/>",
                    "X-Custom-Header": "custom",
                },
                "test+to2@anymail.dev": {
                    "List-Unsubscribe": "<https://example.com/b/>",
                },
            },
        )
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "queued")

    def test_stored_template(self):
        message = AnymailMessage(
            # name of a real template named in Anymail's Mailgun test account:
            template_id="test-template",
            # Mailgun templates don't define subject:
            subject="Your order %recipient.order%",
            # Mailgun templates don't define sender:
            from_email=formataddr(("Test From>", self.from_email)),
            to=["test+to1@anymail.dev"],
            # metadata and merge_data must not have any conflicting keys
            # when using template_id:
            metadata={"meta1": "simple string", "meta2": 2},
            merge_data={
                "test+to1@anymail.dev": {
                    "name": "Test Recipient",
                }
            },
            merge_global_data={
                "order": "12345",
            },
        )
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")

    @override_settings(
        MAILERS={
            "default": {
                "BACKEND": "anymail.backends.mailgun.EmailBackend",
                "OPTIONS": {
                    "api_key": "Hey, that's not an API key",
                    "sender_domain": ANYMAIL_TEST_MAILGUN_DOMAIN,
                    "send_defaults": {"esp_extra": {"o:testmode": "yes"}},
                },
            },
        },
    )
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Mailgun doesn't offer any additional explanation in its response body
        # self.assertIn("Forbidden", str(err))
