import os
import unittest

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin


ANYMAIL_TEST_POSTAL_API_KEY = os.getenv('ANYMAIL_TEST_POSTAL_API_KEY')
ANYMAIL_TEST_POSTAL_API_URL = os.getenv('ANYMAIL_TEST_POSTAL_API_URL')


@tag('postal', 'live')
@unittest.skipUnless(ANYMAIL_TEST_POSTAL_API_KEY and ANYMAIL_TEST_POSTAL_API_URL,
                     "Set ANYMAIL_TEST_POSTAL_API_KEY and ANYMAIL_TEST_POSTAL_API_URL "
                     "environment variables to run Postal integration tests")
@override_settings(ANYMAIL_POSTAL_API_KEY=ANYMAIL_TEST_POSTAL_API_KEY,
                   ANYMAIL_POSTAL_API_URL=ANYMAIL_TEST_POSTAL_API_URL,
                   EMAIL_BACKEND="anymail.backends.postal.EmailBackend")
class PostalBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Postal API integration tests

    These tests run against the **live** Postal API, using the
    environment variable `ANYMAIL_TEST_POSTAL_API_KEY` as the API key and
    `ANYMAIL_TEST_POSTAL_API_URL` as server url.
    If these variables are not set, these tests won't run.
    """

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage('Anymail Postal integration test', 'Text content',
                                      'from@example.com', ['test+to1@anymail.dev'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the Postal send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['test+to1@anymail.dev'].status
        message_id = anymail_status.recipients['test+to1@anymail.dev'].message_id

        self.assertEqual(sent_status, 'queued')
        self.assertGreater(len(message_id), 0)  # non-empty string
        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Postal all-options integration test",
            body="This is the text body",
            from_email="Test From <from@example.com>",
            envelope_sender="bounces@example.com",
            to=["test+to1@anymail.dev", "Recipient 2 <test+to2@anymail.dev>"],
            cc=["test+cc1@anymail.dev", "Copy 2 <test+cc2@anymail.dev>"],
            bcc=["test+bcc1@anymail.dev", "Blind Copy 2 <test+bcc2@anymail.dev>"],
            reply_to=["reply1@example.com"],
            headers={"X-Anymail-Test": "value"},
            tags=["tag 1"],  # max one tag
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")

        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})
        self.assertEqual(message.anymail_status.recipients['test+to1@anymail.dev'].status, 'queued')
        self.assertEqual(message.anymail_status.recipients['test+to2@anymail.dev'].status, 'queued')
        # distinct messages should have different message_ids:
        self.assertNotEqual(message.anymail_status.recipients['test+to1@anymail.dev'].message_id,
                            message.anymail_status.recipients['teset+to2@anymail.dev'].message_id)

    def test_invalid_from(self):
        self.message.from_email = 'webmaster@localhost'  # Django's default From
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        response = err.response.json()
        self.assertEqual(err.status_code, 200)
        self.assertEqual(response['status'], 'error')
        self.assertIn("The From address is not authorised to send mail from this server", response['data']['message'])
        self.assertIn("UnauthenticatedFromAddress", response['data']['code'])

    @override_settings(ANYMAIL_POSTAL_API_KEY="Hey, that's not an API key!")
    def test_invalid_server_token(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        response = err.response.json()
        self.assertEqual(err.status_code, 200)
        self.assertEqual(response['status'], 'error')
        self.assertIn("The API token provided in X-Server-API-Key was not valid.", response['data']['message'])
        self.assertIn("InvalidServerAPIKey", response['data']['code'])
