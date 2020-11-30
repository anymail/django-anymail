import os
import unittest

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_MAILJET_API_KEY = os.getenv('ANYMAIL_TEST_MAILJET_API_KEY')
ANYMAIL_TEST_MAILJET_SECRET_KEY = os.getenv('ANYMAIL_TEST_MAILJET_SECRET_KEY')


@tag('mailjet', 'live')
@unittest.skipUnless(ANYMAIL_TEST_MAILJET_API_KEY and ANYMAIL_TEST_MAILJET_SECRET_KEY,
                     "Set ANYMAIL_TEST_MAILJET_API_KEY and ANYMAIL_TEST_MAILJET_SECRET_KEY "
                     "environment variables to run Mailjet integration tests")
@override_settings(ANYMAIL={"MAILJET_API_KEY": ANYMAIL_TEST_MAILJET_API_KEY,
                            "MAILJET_SECRET_KEY": ANYMAIL_TEST_MAILJET_SECRET_KEY,
                            "MAILJET_SEND_DEFAULTS": {"esp_extra": {"SandboxMode": True}},  # don't actually send mail
                            },
                   EMAIL_BACKEND="anymail.backends.mailjet.EmailBackend")
class MailjetBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Mailjet API integration tests

    These tests run against the **live** Mailjet API, using the
    environment variables `ANYMAIL_TEST_MAILJET_API_KEY` and `ANYMAIL_TEST_MAILJET_SECRET_KEY`
    as the API key and API secret key, respectively.
    If those variables are not set, these tests won't run.

    These tests enable Mailjet's SandboxMode to avoid sending any email;
    remove the esp_extra setting above if you are trying to actually send test messages.

    Mailjet also doesn't support unverified senders (so no from@example.com).
    We've set up @test-mj.anymail.info as a validated sending domain for these tests.
    """

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage('Anymail Mailjet integration test', 'Text content',
                                      'test@test-mj.anymail.info', ['test+to1@anymail.info'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the Mailjet send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['test+to1@anymail.info'].status
        message_id = anymail_status.recipients['test+to1@anymail.info'].message_id

        self.assertEqual(sent_status, 'sent')
        self.assertRegex(message_id, r'.+')
        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Mailjet all-options integration test",
            body="This is the text body",
            from_email='"Test Sender, Inc." <test@test-mj.anymail.info>',
            to=['test+to1@anymail.info', '"Recipient, 2nd" <test+to2@anymail.info>'],
            cc=['test+cc1@anymail.info', 'Copy 2 <test+cc1@anymail.info>'],
            bcc=['test+bcc1@anymail.info', 'Blind Copy 2 <test+bcc2@anymail.info>'],
            reply_to=['"Reply, To" <reply2@example.com>'],  # Mailjet only supports single reply_to
            headers={"X-Anymail-Test": "value"},

            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1"],  # Mailjet only allows a single tag
            track_clicks=True,
            track_opens=True,
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")
        cid = message.attach_inline_image_file(sample_image_path())
        message.attach_alternative(
            "<p><b>HTML:</b> with <a href='http://example.com'>link</a>"
            "and image: <img src='cid:%s'></div>" % cid,
            "text/html")

        message.send()
        self.assertEqual(message.anymail_status.status, {'sent'})

    def test_merge_data(self):
        message = AnymailMessage(
            subject="Anymail Mailjet merge_data test",  # Mailjet doesn't support merge fields in the subject
            body="This body includes merge data: [[var:value]]\n"
                 "And global merge data: [[var:global]]",
            from_email="Test From <test@test-mj.anymail.info>",
            to=["test+to1@anymail.info", "Recipient 2 <test+to2@anymail.info>"],
            merge_data={
                'test+to1@anymail.info': {'value': 'one'},
                'test+to2@anymail.info': {'value': 'two'},
            },
            merge_global_data={
                'global': 'global_value'
            },
        )
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status['test+to1@anymail.info'].status, 'sent')
        self.assertEqual(recipient_status['test+to2@anymail.info'].status, 'sent')

    def test_stored_template(self):
        message = AnymailMessage(
            template_id='176375',  # ID of the real template named 'test-template' in our Mailjet test account
            to=["test+to1@anymail.info"],
            merge_data={
                'test+to1@anymail.info': {
                    'name': "Test Recipient",
                }
            },
            merge_global_data={
                'order': '12345',
            },
        )
        message.from_email = None  # use the template's sender email/name
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status['test+to1@anymail.info'].status, 'sent')

    @override_settings(ANYMAIL={"MAILJET_API_KEY": "Hey, that's not an API key!",
                                "MAILJET_SECRET_KEY": "and this isn't the secret for it"})
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        self.assertIn("API key authentication/authorization failure", str(err))
