import os
import unittest
from datetime import datetime, timedelta, timezone
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
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertIn(sent_status, {"queued", "sent"})  # MailKite queues then sends
        self.assertGreater(len(message_id), 0)  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail MailKite all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From", self.from_email)),
            to=["test+to1@anymail.dev", '"Recipient 2" <test+to2@anymail.dev>'],
            cc=["test+cc1@anymail.dev"],
            reply_to=["reply@example.com"],
            headers={"X-Anymail-Test": "value"},
            metadata={"meta1": "simple string", "meta2": 2},
            tags=["integration", "tag 2"],
            track_opens=True,
        )
        message.attach_alternative("<p>HTML content</p>", "text/html")
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")

        message.send()
        # All recipients share the single returned message id:
        self.assertGreater(len(message.anymail_status.message_id), 0)
        recipient_status = message.anymail_status.recipients
        self.assertIn(
            recipient_status["test+to1@anymail.dev"].status, {"queued", "sent"}
        )
        self.assertEqual(
            recipient_status["test+to1@anymail.dev"].message_id,
            recipient_status["test+to2@anymail.dev"].message_id,
        )

    def test_scheduled_send(self):
        # A future send_at parks the message with MailKite's scheduler.
        # Metadata and tags (carried as headers) are preserved on the
        # scheduled message.
        message = AnymailMessage(
            subject="Anymail MailKite scheduled-send integration test",
            body="This message was scheduled 2 minutes ahead via send_at",
            from_email=self.from_email,
            to=["test+to1@anymail.dev"],
            metadata={"meta1": "scheduled"},
            tags=["integration-scheduled"],
        )
        message.send_at = datetime.now(timezone.utc) + timedelta(minutes=2)
        message.send()

        anymail_status = message.anymail_status
        # MailKite returns an ssnd_… scheduled-send id and "scheduled" status,
        # which Anymail normalizes to "queued":
        self.assertEqual(anymail_status.status, {"queued"})
        self.assertTrue(anymail_status.message_id.startswith("ssnd_"))

    def test_batch_send(self):
        # merge_data switches to MailKite's batch endpoint: one personalized
        # message per recipient, each with its own message id.
        message = AnymailMessage(
            subject="Anymail MailKite batch integration test, {{name}}",
            body="This message was personalized for {{name}} ({{group}})",
            from_email=self.from_email,
            to=["test+to1@anymail.dev", "Recipient 2 <test+to2@anymail.dev>"],
            merge_data={
                "test+to1@anymail.dev": {"name": "One"},
                "test+to2@anymail.dev": {"name": "Two"},
            },
            merge_global_data={"group": "integration"},
            merge_metadata={
                "test+to1@anymail.dev": {"user_id": 1},
                "test+to2@anymail.dev": {"user_id": 2},
            },
        )
        message.send()

        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "sent")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "sent")
        # Batch = one message per recipient, so the ids differ:
        self.assertNotEqual(
            recipient_status["test+to1@anymail.dev"].message_id,
            recipient_status["test+to2@anymail.dev"].message_id,
        )
