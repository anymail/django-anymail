import os
import unittest
from email.utils import formataddr

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_MAILTRAP_API_TOKEN = os.getenv("ANYMAIL_TEST_MAILTRAP_API_TOKEN")
ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID = os.getenv("ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID")
# Optional: if provided, use for nicer From address; sandbox doesn't require this
ANYMAIL_TEST_MAILTRAP_DOMAIN = os.getenv("ANYMAIL_TEST_MAILTRAP_DOMAIN")
ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID = os.getenv("ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID")


@tag("mailtrap", "live")
@unittest.skipUnless(
    ANYMAIL_TEST_MAILTRAP_API_TOKEN and ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID,
    "Set ANYMAIL_TEST_MAILTRAP_API_TOKEN and ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID"
    " environment variables to run Mailtrap integration tests",
)
@override_settings(
    ANYMAIL={
        "MAILTRAP_API_TOKEN": ANYMAIL_TEST_MAILTRAP_API_TOKEN,
        # Use Mailtrap sandbox (testing) API so we don't actually send email
        "MAILTRAP_TEST_INBOX_ID": ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID,
        # You can override MAILTRAP_TEST_API_URL via env if needed; default is fine
    },
    EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend",
)
class MailtrapBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Mailtrap API integration tests (using sandbox testing inbox)

    These tests run against the live Mailtrap API in testing mode, using
    ANYMAIL_TEST_MAILTRAP_API_TOKEN for authentication and
    ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID for the sandbox inbox id. No real
    email is sent in this mode.
    """

    def setUp(self):
        super().setUp()
        from_domain = ANYMAIL_TEST_MAILTRAP_DOMAIN or "anymail.dev"
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

        self.assertEqual(sent_status, "sent")  # Mailtrap reports sent on success
        self.assertRegex(message_id, r".+")  # non-empty string
        # set of all recipient statuses:
        self.assertEqual(anymail_status.status, {sent_status})
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Mailtrap all-options integration test",
            body="This is the text body",
            from_email=formataddr(("Test From, with comma", self.from_email)),
            to=[
                "test+to1@anymail.dev",
                "Recipient 2 <test+to2@anymail.dev>",
            ],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=[
                '"Reply, with comma" <reply@example.com>',
                "reply2@example.com",
            ],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": "3"},
            metadata={"meta1": "simple string", "meta2": 2},
            # Mailtrap supports only a single tag/category
            tags=["tag 1"],
            track_clicks=True,
            track_opens=True,
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")
        cid = message.attach_inline_image_file(sample_image_path())
        message.attach_alternative(
            "<p><b>HTML:</b> with <a href='http://example.com'>link</a>"
            f"and image: <img src='cid:{cid}'></div>",
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

    @unittest.skipUnless(
        ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID,
        "Set ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID to test Mailtrap stored templates",
    )
    def test_stored_template(self):
        message = AnymailMessage(
            # UUID of a template available in your Mailtrap account
            template_id=ANYMAIL_TEST_MAILTRAP_TEMPLATE_UUID,
            to=["test+to1@anymail.dev", "Second Recipient <test+to2@anymail.dev>"],
            merge_global_data={  # Mailtrap uses template_variables for global vars
                "company_info_name": "Test_Company_info_name",
                "name": "Test_Name",
                "company_info_address": "Test_Company_info_address",
                "company_info_city": "Test_Company_info_city",
                "company_info_zip_code": "Test_Company_info_zip_code",
                "company_info_country": "Test_Company_info_country",
            },
        )
        # Use template's configured sender if desired
        message.from_email = self.from_email
        message.send()
        self.assertEqual(message.anymail_status.status, {"sent"})

    @override_settings(
        ANYMAIL={
            "MAILTRAP_API_TOKEN": "Hey, that's not an API token!",
            "MAILTRAP_TEST_INBOX_ID": ANYMAIL_TEST_MAILTRAP_TEST_INBOX_ID,
        }
    )
    def test_invalid_api_token(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
