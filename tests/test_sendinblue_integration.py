import os
import unittest
from datetime import datetime, timedelta
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin

ANYMAIL_TEST_SENDINBLUE_API_KEY = os.getenv("ANYMAIL_TEST_SENDINBLUE_API_KEY")
ANYMAIL_TEST_SENDINBLUE_DOMAIN = os.getenv("ANYMAIL_TEST_SENDINBLUE_DOMAIN")


@tag("sendinblue", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_SENDINBLUE_API_KEY and ANYMAIL_TEST_SENDINBLUE_DOMAIN,
    "Set ANYMAIL_TEST_SENDINBLUE_API_KEY and ANYMAIL_TEST_SENDINBLUE_DOMAIN "
    "environment variables to run SendinBlue integration tests",
)
@override_settings(
    ANYMAIL_SENDINBLUE_API_KEY=ANYMAIL_TEST_SENDINBLUE_API_KEY,
    ANYMAIL_SENDINBLUE_SEND_DEFAULTS=dict(),
    EMAIL_BACKEND="anymail.backends.sendinblue.EmailBackend",
)
class SendinBlueBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """SendinBlue v3 API integration tests

    SendinBlue doesn't have sandbox so these tests run
    against the **live** SendinBlue API, using the
    environment variable `ANYMAIL_TEST_SENDINBLUE_API_KEY` as the API key,
    and `ANYMAIL_TEST_SENDINBLUE_DOMAIN` to construct sender addresses.
    If those variables are not set, these tests won't run.

    https://developers.sendinblue.com/docs/faq#section-how-can-i-test-the-api-

    """

    def setUp(self):
        super().setUp()
        self.from_email = "from@%s" % ANYMAIL_TEST_SENDINBLUE_DOMAIN
        self.message = AnymailMessage(
            "Anymail SendinBlue integration test",
            "Text content",
            self.from_email,
            ["test+to1@anymail.dev"],
        )
        self.message.attach_alternative("<p>HTML content</p>", "text/html")

    def test_simple_send(self):
        # Example of getting the SendinBlue send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients["test+to1@anymail.dev"].status
        message_id = anymail_status.recipients["test+to1@anymail.dev"].message_id

        self.assertEqual(sent_status, "queued")  # SendinBlue always queues
        # Message-ID can be ...@smtp-relay.mail.fr or .sendinblue.com:
        self.assertRegex(message_id, r"\<.+@.+\>")
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now() + timedelta(minutes=2)
        message = AnymailMessage(
            subject="Anymail SendinBlue all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From, with comma", self.from_email)),
            to=["test+to1@anymail.dev", '"Recipient 2, OK?" <test+to2@anymail.dev>'],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            # SendinBlue API v3 only supports single reply-to
            reply_to=['"Reply, with comma" <reply@example.com>'],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            metadata={"meta1": "simple string", "meta2": 2},
            send_at=send_at,
            tags=["tag 1", "tag 2"],
        )
        # SendinBlue requires an HTML body:
        message.attach_alternative("<p>HTML content</p>", "text/html")

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        # SendinBlue always queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertRegex(message.anymail_status.message_id, r"\<.+@.+\>")

    def test_template(self):
        message = AnymailMessage(
            # There is a *new-style* template with this id in the Anymail test account:
            template_id=5,
            # Override template sender:
            from_email=formataddr(("Sender", self.from_email)),
            # No batch send (so max one recipient suggested):
            to=["Recipient <test+to1@anymail.dev>"],
            reply_to=["Do not reply <reply@example.dev>"],
            tags=["using-template"],
            headers={"X-Anymail-Test": "group: A, variation: C"},
            merge_global_data={
                # The Anymail test template includes `{{ params.SHIP_DATE }}`
                # and `{{ params.ORDER_ID }}` substitutions
                "SHIP_DATE": "yesterday",
                "ORDER_ID": "12345",
            },
            metadata={"customer-id": "ZXK9123", "meta2": 2},
        )

        # Normal attachments don't work with Sendinblue templates:
        #   message.attach("attachment1.txt", "Here is some\ntext", "text/plain")
        # If you can host the attachment content on some publicly-accessible URL,
        # this *non-portable* alternative allows sending attachments with templates:
        message.esp_extra = {
            "attachment": [
                {
                    "name": "attachment1.txt",
                    # URL where Sendinblue can download
                    # the attachment content while sending:
                    "url": "https://raw.githubusercontent.com/anymail"
                    "/django-anymail/main/LICENSE",
                }
            ]
        }

        message.send()
        # SendinBlue always queues:
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertRegex(message.anymail_status.message_id, r"\<.+@.+\>")

    @override_settings(ANYMAIL_SENDINBLUE_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Make sure the exception message includes SendinBlue's response:
        self.assertIn("Key not found", str(err))
