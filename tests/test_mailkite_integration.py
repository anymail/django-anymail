import os
import unittest
from email.utils import formataddr

from django.test import SimpleTestCase, tag

from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, override_settings

ANYMAIL_TEST_MAILKITE_API_KEY = os.getenv("ANYMAIL_TEST_MAILKITE_API_KEY")
ANYMAIL_TEST_MAILKITE_DOMAIN = os.getenv("ANYMAIL_TEST_MAILKITE_DOMAIN")


@tag("mailkite", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILKITE_API_KEY and ANYMAIL_TEST_MAILKITE_DOMAIN,
    "Set ANYMAIL_TEST_MAILKITE_API_KEY and ANYMAIL_TEST_MAILKITE_DOMAIN "
    "environment variables to run MailKite integration tests",
)
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.mailkite.EmailBackend",
            "OPTIONS": {"api_key": ANYMAIL_TEST_MAILKITE_API_KEY},
        },
    },
)
class MailKiteBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """MailKite API integration tests

    MailKite doesn't have a sandbox, so these tests run against the **live**
    MailKite API, using the environment variable ``ANYMAIL_TEST_MAILKITE_API_KEY``
    as the API key, and ``ANYMAIL_TEST_MAILKITE_DOMAIN`` to construct sender
    addresses. If those variables are not set, these tests won't run.

    """

    def setUp(self):
        super().setUp()
        self.from_email = "from@%s" % ANYMAIL_TEST_MAILKITE_DOMAIN
        self.message = AnymailMessage(
            "Anymail MailKite integration test",
            "Text content",
            self.from_email,
            ["test+anymail@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the MailKite message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+anymail@anymail.dev"].status
        message_id = anymail_status.recipients["test+anymail@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # MailKite accepts and queues
        self.assertGreater(len(message_id), 0)  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail MailKite all-options integration test",
            body="This is the text body",
            # Verify workarounds for address formatting issues:
            from_email=formataddr(("Test «Från», med komma", self.from_email)),
            to=[
                "test+anymail@anymail.dev",
                '"Recipient 2, OK?" <test+anymail2@anymail.dev>',
            ],
            cc=[
                "test+anymail-cc1@anymail.dev",
                "Copy 2 <test+anymail-cc2@anymail.dev>",
            ],
            bcc=[
                "test+anymail-bcc1@anymail.dev",
                "Blind Copy 2 <test+anymail-bcc2@anymail.dev>",
            ],
            reply_to=['"Reply, with comma" <reply@example.com>'],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1", "tag 2"],
            track_opens=True,
            track_clicks=True,
        )
        message.attach_alternative("<p>HTML content</p>", "text/html")

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        # MailKite accepts and queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertGreater(len(message.anymail_status.message_id), 0)

    def test_template_send(self):
        # MailKite renders server-side templates and fills {{merge_tags}}.
        # Uses a base template id if ANYMAIL_TEST_MAILKITE_TEMPLATE is set,
        # otherwise skips.
        template_id = os.getenv("ANYMAIL_TEST_MAILKITE_TEMPLATE")
        if not template_id:
            self.skipTest("Set ANYMAIL_TEST_MAILKITE_TEMPLATE to run this test")
        message = AnymailMessage(
            from_email=self.from_email,
            to=["test+anymail@anymail.dev"],
            template_id=template_id,
            merge_global_data={"name": "Anymail"},
        )
        message.send()
        self.assertEqual(message.anymail_status.status, {"queued"})

    def test_batch_send(self):
        # merge_metadata will use the batch send API
        message = AnymailMessage(
            subject="Anymail MailKite batch send integration test",
            body="This is the text body",
            from_email=self.from_email,
            to=[
                "test+anymail@anymail.dev",
                '"Recipient 2" <test+anymail2@anymail.dev>',
            ],
            metadata={"meta1": "simple string", "meta2": 2},
            merge_metadata={
                "test+anymail@anymail.dev": {"meta3": "recipient 1"},
                "test+anymail2@anymail.dev": {"meta3": "recipient 2"},
            },
            tags=["tag 1", "tag 2"],
            headers={
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
            },
            merge_headers={
                "test+anymail@anymail.dev": {
                    "List-Unsubscribe": "<https://example.com/a/>",
                },
                "test+anymail2@anymail.dev": {
                    "List-Unsubscribe": "<https://example.com/b/>",
                },
            },
        )
        message.attach_alternative("<p>HTML content</p>", "text/html")

        message.send()
        # MailKite accepts and queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+anymail@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+anymail2@anymail.dev"].status, "queued")
        self.assertRegex(recipient_status["test+anymail@anymail.dev"].message_id, r".+")
        self.assertRegex(
            recipient_status["test+anymail2@anymail.dev"].message_id, r".+"
        )
        # Each recipient gets their own message_id:
        self.assertNotEqual(
            recipient_status["test+anymail@anymail.dev"].message_id,
            recipient_status["test+anymail2@anymail.dev"].message_id,
        )
