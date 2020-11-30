import os
import unittest

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin

ANYMAIL_TEST_SENDINBLUE_API_KEY = os.getenv('ANYMAIL_TEST_SENDINBLUE_API_KEY')


@tag('sendinblue', 'live')
@unittest.skipUnless(ANYMAIL_TEST_SENDINBLUE_API_KEY,
                     "Set ANYMAIL_TEST_SENDINBLUE_API_KEY environment variable "
                     "to run SendinBlue integration tests")
@override_settings(ANYMAIL_SENDINBLUE_API_KEY=ANYMAIL_TEST_SENDINBLUE_API_KEY,
                   ANYMAIL_SENDINBLUE_SEND_DEFAULTS=dict(),
                   EMAIL_BACKEND="anymail.backends.sendinblue.EmailBackend")
class SendinBlueBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """SendinBlue v3 API integration tests

    SendinBlue doesn't have sandbox so these tests run
    against the **live** SendinBlue API, using the
    environment variable `ANYMAIL_TEST_SENDINBLUE_API_KEY` as the API key
    If those variables are not set, these tests won't run.

    https://developers.sendinblue.com/docs/faq#section-how-can-i-test-the-api-

    """

    def setUp(self):
        super().setUp()

        self.message = AnymailMessage('Anymail SendinBlue integration test', 'Text content',
                                      'from@test-sb.anymail.info', ['test+to1@anymail.info'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the SendinBlue send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['test+to1@anymail.info'].status
        message_id = anymail_status.recipients['test+to1@anymail.info'].message_id

        self.assertEqual(sent_status, 'queued')  # SendinBlue always queues
        self.assertRegex(message_id, r'\<.+@.+\>')  # Message-ID can be ...@smtp-relay.mail.fr or .sendinblue.com
        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail SendinBlue all-options integration test",
            body="This is the text body",
            from_email='"Test From, with comma" <from@test-sb.anymail.info>',
            to=["test+to1@anymail.info", '"Recipient 2, OK?" <test+to2@anymail.info>'],
            cc=["test+cc1@anymail.info", "Copy 2 <test+cc2@anymail.info>"],
            bcc=["test+bcc1@anymail.info", "Blind Copy 2 <test+bcc2@anymail.info>"],
            reply_to=['"Reply, with comma" <reply@example.com>'],  # SendinBlue API v3 only supports single reply-to
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},

            metadata={"meta1": "simple string", "meta2": 2},
            tags=["tag 1", "tag 2"],
        )
        message.attach_alternative('<p>HTML content</p>', "text/html")  # SendinBlue requires an HTML body

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})  # SendinBlue always queues
        self.assertRegex(message.anymail_status.message_id, r'\<.+@.+\>')

    def test_template(self):
        message = AnymailMessage(
            template_id=5,  # There is a *new-style* template with this id in the Anymail test account
            from_email='Sender <from@test-sb.anymail.info>',  # Override template sender
            to=["Recipient <test+to1@anymail.info>"],  # No batch send (so max one recipient suggested)
            reply_to=["Do not reply <reply@example.com>"],
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
        #   message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        # If you can host the attachment content on some publicly-accessible URL,
        # this *non-portable* alternative allows sending attachments with templates:
        message.esp_extra = {
            'attachment': [{
                'name': 'attachment1.txt',
                # URL where Sendinblue can download the attachment content while sending:
                'url': 'https://raw.githubusercontent.com/anymail/django-anymail/main/AUTHORS.txt',
            }]
        }

        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})  # SendinBlue always queues
        self.assertRegex(message.anymail_status.message_id, r'\<.+@.+\>')

    @override_settings(ANYMAIL_SENDINBLUE_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Make sure the exception message includes SendinBlue's response:
        self.assertIn("Key not found", str(err))
