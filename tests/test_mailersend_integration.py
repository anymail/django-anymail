import os
import unittest
from datetime import datetime, timedelta
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_MAILERSEND_API_TOKEN = os.getenv("ANYMAIL_TEST_MAILERSEND_API_TOKEN")
ANYMAIL_TEST_MAILERSEND_DOMAIN = os.getenv("ANYMAIL_TEST_MAILERSEND_DOMAIN")


@tag("mailersend", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILERSEND_API_TOKEN and ANYMAIL_TEST_MAILERSEND_DOMAIN,
    "Set ANYMAIL_TEST_MAILERSEND_API_TOKEN and ANYMAIL_TEST_MAILERSEND_DOMAIN"
    " environment variables to run MailerSend integration tests",
)
@override_settings(
    ANYMAIL={
        "MAILERSEND_API_TOKEN": ANYMAIL_TEST_MAILERSEND_API_TOKEN,
    },
    EMAIL_BACKEND="anymail.backends.mailersend.EmailBackend",
)
class MailerSendBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """MailerSend API integration tests

    These tests run against the **live** MailerSend API, using the
    environment variable `ANYMAIL_TEST_MAILERSEND_API_TOKEN` as the API token
    and `ANYMAIL_TEST_MAILERSEND_DOMAIN` as the sender domain.
    If those variables are not set, these tests won't run.

    """

    def setUp(self):
        super().setUp()
        self.from_email = f"from@{ANYMAIL_TEST_MAILERSEND_DOMAIN}"
        self.message = AnymailMessage(
            "Anymail MailerSend integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the MailerSend send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # MailerSend queues
        # don't know what it'll be, but it should exist (and not be a bulk id):
        self.assertGreater(len(message_id), 0)
        self.assertFalse(message_id.startswith("bulk:"))

        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now() + timedelta(minutes=2)
        from_email = formataddr(("Test From, with comma", self.from_email))
        message = AnymailMessage(
            subject="Anymail MailerSend all-options integration test",
            body="This is the text body",
            from_email=from_email,
            to=[
                "test+to1@anymail.dev",
                "Recipient 2 <test+to2@anymail.dev>",
                "test+bounce@anymail.dev",  # will be rejected
            ],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            # MailerSend only supports single reply_to:
            reply_to=["Reply <reply@example.com>"],
            # MailerSend supports very limited extra headers:
            headers={"Precedence": "bulk", "In-Reply-To": "earlier-id@anymail.dev"},
            send_at=send_at,
            tags=["tag 1", "tag 2"],
            track_clicks=False,
            track_opens=True,
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("vedhæftet fil.csv", "ID,Name\n1,3", "text/csv")
        cid = message.attach_inline_image_file(
            sample_image_path(), domain=ANYMAIL_TEST_MAILERSEND_DOMAIN
        )
        message.attach_alternative(
            f"<div>This is the <i>html</i> body <img src='cid:{cid}'></div>",
            "text/html",
        )

        message.send()

        # First two recipients should be queued, other should be bounced
        self.assertEqual(message.anymail_status.status, {"queued", "rejected"})
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+bounce@anymail.dev"].status, "rejected")

    def test_stored_template(self):
        message = AnymailMessage(
            # id of a real template named in Anymail's MailerSend test account:
            template_id="vywj2lpokkm47oqz",
            to=[
                "test+to1@anymail.dev",
                "test+to2@anymail.dev",
                "test+bounce@anymail.dev",  # will be rejected
            ],
            merge_data={
                "test+to1@anymail.dev": {"name": "First Recipient", "order": 12345},
                "test+to2@anymail.dev": {"name": "Second Recipient", "order": 67890},
                "test+bounce@anymail.dev": {"name": "Bounces", "order": 3},
            },
            merge_global_data={"date": "yesterday"},
            esp_extra={
                # CAREFUL: with "expose-to-list", all recipients will see
                #   every other recipient's email address. (See docs!)
                "batch_send_mode": "expose-to-list"
            },
        )
        message.from_email = None  # use template From
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "queued")
        self.assertEqual(recipient_status["test+bounce@anymail.dev"].status, "rejected")
        self.assertFalse(
            recipient_status["test+to1@anymail.dev"].message_id.startswith("bulk:")
        )
        self.assertIsNone(recipient_status["test+bounce@anymail.dev"].message_id)

    def test_batch_send_mode_bulk(self):
        # Same test as above, but with batch_send_mode "use-bulk-email".
        # (Uses different API; status is handled very differently.)
        message = AnymailMessage(
            # id of a real template named in Anymail's MailerSend test account:
            template_id="vywj2lpokkm47oqz",
            to=[
                "test+to1@anymail.dev",
                "test+to2@anymail.dev",
                "test+bounce@anymail.dev",  # will be rejected
            ],
            merge_data={
                "test+to1@anymail.dev": {"name": "First Recipient", "order": 12345},
                "test+to2@anymail.dev": {"name": "Second Recipient", "order": 67890},
                "test+bounce@anymail.dev": {"name": "Bounces", "order": 3},
            },
            merge_global_data={"date": "yesterday"},
            esp_extra={"batch_send_mode": "use-bulk-email"},
        )
        message.from_email = None  # use template From
        message.send()
        recipient_status = message.anymail_status.recipients
        # With use-bulk-email, must poll bulk-email status API to determine status:
        self.assertEqual(recipient_status["test+to1@anymail.dev"].status, "unknown")
        self.assertEqual(recipient_status["test+to2@anymail.dev"].status, "unknown")
        self.assertEqual(recipient_status["test+bounce@anymail.dev"].status, "unknown")
        # With use-bulk-email, message_id will be MailerSend's bulk_email_id
        # rather than an actual message_id. Anymail adds "bulk:" to differentiate:
        self.assertTrue(
            recipient_status["test+to1@anymail.dev"].message_id.startswith("bulk:")
        )
        self.assertTrue(
            recipient_status["test+bounce@anymail.dev"].message_id.startswith("bulk:")
        )

    @override_settings(
        ANYMAIL={
            "MAILERSEND_API_TOKEN": "Hey, that's not an API token",
        }
    )
    def test_invalid_api_key(self):
        with self.assertRaisesMessage(AnymailAPIError, "Unauthenticated"):
            self.message.send()
