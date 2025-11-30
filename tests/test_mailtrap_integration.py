import os
import unittest
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

# Environment variables to run these live integration tests...
# API token for both sets of tests:
ANYMAIL_TEST_MAILTRAP_API_TOKEN = os.getenv("ANYMAIL_TEST_MAILTRAP_API_TOKEN")
# Validated sending domain for transactional API tests:
ANYMAIL_TEST_MAILTRAP_DOMAIN = os.getenv("ANYMAIL_TEST_MAILTRAP_DOMAIN")
# Test inbox id for sandbox API tests:
ANYMAIL_TEST_MAILTRAP_SANDBOX_ID = os.getenv("ANYMAIL_TEST_MAILTRAP_SANDBOX_ID")
# Template id for both sets of tests:
ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID = os.getenv("ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID")


@tag("mailtrap", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILTRAP_API_TOKEN and ANYMAIL_TEST_MAILTRAP_DOMAIN,
    "Set ANYMAIL_TEST_MAILTRAP_API_TOKEN and ANYMAIL_TEST_MAILTRAP_DOMAIN"
    " environment variables to run Mailtrap transactional integration tests",
)
@override_settings(
    ANYMAIL={
        "MAILTRAP_API_TOKEN": ANYMAIL_TEST_MAILTRAP_API_TOKEN,
    },
    EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend",
)
class MailtrapBackendTransactionalIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """
    Mailtrap API integration tests using transactional API

    These tests run against the live Mailtrap Transactional API.
    They send real email (to /dev/null mailboxes on the anymail.dev domain).
    """

    def setUp(self):
        super().setUp()
        from_domain = ANYMAIL_TEST_MAILTRAP_DOMAIN
        self.from_email = f"from@{from_domain}"
        self.message = AnymailMessage(
            "Anymail Mailtrap integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Mailtrap send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")
        self.assertGreater(len(message_id), 0)  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Mailtrap all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From, with comma", self.from_email)),
            to=["test+to1@anymail.dev", "Recipient 2 <test+to2@anymail.dev>"],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
            },
            # no send_at support
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1"],  # max one tag
            # no track_clicks/track_opens support
            # either of these merge_ options will force batch send
            # (unique message for each "to" recipient)
            merge_metadata={
                "test+to1@anymail.dev": {"customer-id": "ZXK9123"},
                "test+to2@anymail.dev": {"customer-id": "ZZT4192"},
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
        self.assertEqual(err.status_code, 401)
        self.assertIn("Unauthorized", str(err))

    @unittest.skipUnless(
        ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID,
        "Set ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID to test Mailtrap stored templates",
    )
    def test_template(self):
        message = AnymailMessage(
            from_email=self.from_email,
            to=["test+to1@anymail.dev", "Second Recipient <test+to2@anymail.dev>"],
            template_id=ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID,
            merge_data={
                "test+to1@anymail.dev": {"name": "Recipient 1", "order_no": "12345"},
                "test+to2@anymail.dev": {"order_no": "6789"},
            },
            merge_global_data={"name": "Valued Customer"},
        )
        message.send()
        self.assertEqual(message.anymail_status.status, {"queued"})

    @override_settings(ANYMAIL={"MAILTRAP_API_TOKEN": "Hey, that's not an API token!"})
    def test_invalid_api_token(self):
        # Invalid API key generates same error as unvalidated from address
        with self.assertRaisesMessage(AnymailAPIError, "Unauthorized"):
            self.message.send()


@tag("mailtrap", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILTRAP_API_TOKEN and ANYMAIL_TEST_MAILTRAP_SANDBOX_ID,
    "Set ANYMAIL_TEST_MAILTRAP_API_TOKEN and ANYMAIL_TEST_MAILTRAP_SANDBOX_ID"
    " environment variables to run Mailtrap sandbox integration tests",
)
@override_settings(
    ANYMAIL={
        "MAILTRAP_API_TOKEN": ANYMAIL_TEST_MAILTRAP_API_TOKEN,
        "MAILTRAP_SANDBOX_ID": ANYMAIL_TEST_MAILTRAP_SANDBOX_ID,
    },
    EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend",
)
class MailtrapBackendSandboxIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """
    Mailtrap API integration tests using sandbox testing inbox

    These tests run against the live Mailtrap Test API ("sandbox").
    Mail is delivered to the test inbox; no email is sent.
    """

    def setUp(self):
        super().setUp()
        from_domain = ANYMAIL_TEST_MAILTRAP_DOMAIN or "example.com"
        self.from_email = f"from@{from_domain}"
        self.message = AnymailMessage(
            "Anymail Mailtrap integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the Mailtrap send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # Mailtrap reports queued on success
        self.assertRegex(message_id, r".+")  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    @unittest.skip("Batch with two recipients exceeds rate limit on free plan")
    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Mailtrap all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From, with comma", self.from_email)),
            to=["test+to1@anymail.dev", "Recipient 2 <test+to2@anymail.dev>"],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
            },
            # no send_at support
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1"],  # max one tag
            # no track_clicks/track_opens support
            # either of these merge_ options will force batch send
            # (unique message for each "to" recipient)
            merge_metadata={
                "test+to1@anymail.dev": {"customer-id": "ZXK9123"},
                "test+to2@anymail.dev": {"customer-id": "ZZT4192"},
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
        # distinct messages should have different message_ids:
        self.assertNotEqual(
            message.anymail_status.recipients["test+to1@anymail.dev"].message_id,
            message.anymail_status.recipients["test+to2@anymail.dev"].message_id,
        )

    @unittest.skip("Batch with two recipients exceeds rate limit on free plan")
    @unittest.skipUnless(
        ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID,
        "Set ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID to test Mailtrap stored templates",
    )
    def test_template(self):
        message = AnymailMessage(
            from_email=self.from_email,
            to=["test+to1@anymail.dev", "Second Recipient <test+to2@anymail.dev>"],
            template_id=ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID,
            merge_data={
                "test+to1@anymail.dev": {"name": "Recipient 1", "order_no": "12345"},
                "test+to2@anymail.dev": {"order_no": "6789"},
            },
            merge_global_data={"name": "Valued Customer"},
        )
        message.send()
        self.assertEqual(message.anymail_status.status, {"queued"})

    @override_settings(
        ANYMAIL={
            "MAILTRAP_API_TOKEN": "Hey, that's not an API token!",
            "MAILTRAP_SANDBOX_ID": ANYMAIL_TEST_MAILTRAP_SANDBOX_ID,
        }
    )
    def test_invalid_api_token(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertIn("Unauthorized", str(err))
        self.assertEqual(err.status_code, 401)
