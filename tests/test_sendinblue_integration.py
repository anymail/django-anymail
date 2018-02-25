import os
import unittest

from django.test import SimpleTestCase
from django.test.utils import override_settings

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, RUN_LIVE_TESTS

SENDINBLUE_TEST_API_KEY = os.getenv('SENDINBLUE_TEST_API_KEY')


@unittest.skipUnless(RUN_LIVE_TESTS, "RUN_LIVE_TESTS disabled in this environment")
@unittest.skipUnless(SENDINBLUE_TEST_API_KEY,
                     "Set SENDINBLUE_TEST_API_KEY environment variable "
                     "to run SendinBlue integration tests")
@override_settings(ANYMAIL_SENDINBLUE_API_KEY=SENDINBLUE_TEST_API_KEY,
                   ANYMAIL_SENDINBLUE_SEND_DEFAULTS=dict(),
                   EMAIL_BACKEND="anymail.backends.sendinblue.EmailBackend")
class SendinBlueBackendIntegrationTests(SimpleTestCase, AnymailTestMixin):
    """SendinBlue v3 API integration tests

    SendinBlue doesn't have sandbox so these tests run
    against the **live** SendinBlue API, using the
    environment variable `SENDINBLUE_TEST_API_KEY` as the API key
    If those variables are not set, these tests won't run.

    https://developers.sendinblue.com/docs/faq#section-how-can-i-test-the-api-

    """

    def setUp(self):
        super(SendinBlueBackendIntegrationTests, self).setUp()

        self.message = AnymailMessage('Anymail SendinBlue integration test', 'Text content',
                                      'from@example.com', ['to@example.com'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the SendinBlue send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['to@example.com'].status
        message_id = anymail_status.recipients['to@example.com'].message_id

        self.assertEqual(sent_status, 'queued')  # SendinBlue always queues
        self.assertRegex(message_id, r'\<.+@smtp-relay\.mailin\.fr\>')  # should use from_email's domain
        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options_without_template(self):
        message = AnymailMessage(
            subject="Anymail all-options integration test",
            body="This is the text body",
            from_email='"Test From, with comma" <from@example.com>',
            to=["to1@example.com", '"Recipient 2, OK?" <to2@example.com>'],
            cc=["cc1@example.com", "Copy 2 <cc2@example.com>"],
            bcc=["bcc1@example.com", "Blind Copy 2 <bcc2@example.com>"],
            reply_to=['"Reply, with comma" <reply@example.com>'],  # SendinBlue API v3 only supports single reply-to
            tags=["tag 1"],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            merge_global_data={
                'global': 'global_value'
            },
            metadata={"meta1": "simple string", "meta2": 2},
        )
        message.attach_alternative('<p>HTML content</p>', "text/html")  # SendinBlue need an HTML content to work

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})  # SendinBlue always queues

    def test_all_options_with_template(self):
        message = AnymailMessage(
            template_id='1',
            to=["to1@example.com", 'to2@example.com'],
            cc=["cc1@example.com", "cc2@example.com"],
            bcc=["bcc1@example.com", "bcc2@example.com"],
            reply_to=['reply@example.com'],  # SendinBlue API v3 only supports single reply-to
            tags=["tag 1"],
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},
            merge_global_data={
                'global': 'global_value'
            },
            metadata={"meta1": "simple string", "meta2": 2},
        )

        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})  # SendinBlue always queues

    @override_settings(ANYMAIL_SENDINBLUE_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Make sure the exception message includes SendinBlue's response:
        self.assertIn("Key not found", str(err))
