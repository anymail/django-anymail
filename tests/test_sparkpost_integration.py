import os
import unittest
from datetime import datetime, timedelta

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_SPARKPOST_API_KEY = os.getenv('ANYMAIL_TEST_SPARKPOST_API_KEY')


@tag('sparkpost', 'live')
@unittest.skipUnless(ANYMAIL_TEST_SPARKPOST_API_KEY,
                     "Set ANYMAIL_TEST_SPARKPOST_API_KEY environment variable "
                     "to run SparkPost integration tests")
@override_settings(ANYMAIL_SPARKPOST_API_KEY=ANYMAIL_TEST_SPARKPOST_API_KEY,
                   EMAIL_BACKEND="anymail.backends.sparkpost.EmailBackend")
class SparkPostBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """SparkPost API integration tests

    These tests run against the **live** SparkPost API, using the
    environment variable `ANYMAIL_TEST_SPARKPOST_API_KEY` as the API key
    If that variable is not set, these tests won't run.

    SparkPost doesn't offer a test mode -- it tries to send everything
    you ask. To avoid stacking up a pile of undeliverable @example.com
    emails, the tests use SparkPost's "sink domain" @*.sink.sparkpostmail.com.
    https://www.sparkpost.com/docs/faq/using-sink-server/

    SparkPost also doesn't support arbitrary senders (so no from@example.com).
    We've set up @test-sp.anymail.info as a validated sending domain for these tests.
    """

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage('Anymail SparkPost integration test', 'Text content',
                                      'test@test-sp.anymail.info', ['to@test.sink.sparkpostmail.com'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the SparkPost send status and transmission id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['to@test.sink.sparkpostmail.com'].status
        message_id = anymail_status.recipients['to@test.sink.sparkpostmail.com'].message_id

        self.assertEqual(sent_status, 'queued')  # SparkPost always queues
        self.assertRegex(message_id, r'.+')  # this is actually the transmission_id; should be non-blank
        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now() + timedelta(minutes=2)
        message = AnymailMessage(
            subject="Anymail all-options integration test",
            body="This is the text body",
            from_email="Test From <test@test-sp.anymail.info>",
            to=["to1@test.sink.sparkpostmail.com", "Recipient 2 <to2@test.sink.sparkpostmail.com>"],
            # Limit the live b/cc's to avoid running through our small monthly allowance:
            # cc=["cc1@test.sink.sparkpostmail.com", "Copy 2 <cc2@test.sink.sparkpostmail.com>"],
            # bcc=["bcc1@test.sink.sparkpostmail.com", "Blind Copy 2 <bcc2@test.sink.sparkpostmail.com>"],
            cc=["Copy To <cc@test.sink.sparkpostmail.com>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={"X-Anymail-Test": "value"},

            metadata={"meta1": "simple string", "meta2": 2},
            send_at=send_at,
            tags=["tag 1"],  # SparkPost only supports single tags
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
        self.assertEqual(message.anymail_status.status, {'queued'})  # SparkPost always queues

    def test_merge_data(self):
        message = AnymailMessage(
            subject="Anymail merge_data test: {{ value }}",
            body="This body includes merge data: {{ value }}\n"
                 "And global merge data: {{ global }}",
            from_email="Test From <test@test-sp.anymail.info>",
            to=["to1@test.sink.sparkpostmail.com", "Recipient 2 <to2@test.sink.sparkpostmail.com>"],
            merge_data={
                'to1@test.sink.sparkpostmail.com': {'value': 'one'},
                'to2@test.sink.sparkpostmail.com': {'value': 'two'},
            },
            merge_global_data={
                'global': 'global_value'
            },
        )
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status['to1@test.sink.sparkpostmail.com'].status, 'queued')
        self.assertEqual(recipient_status['to2@test.sink.sparkpostmail.com'].status, 'queued')

    def test_stored_template(self):
        message = AnymailMessage(
            template_id='test-template',  # a real template in our SparkPost test account
            to=["to1@test.sink.sparkpostmail.com"],
            merge_data={
                'to1@test.sink.sparkpostmail.com': {
                    'name': "Test Recipient",
                }
            },
            merge_global_data={
                'order': '12345',
            },
        )
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status['to1@test.sink.sparkpostmail.com'].status, 'queued')

    @override_settings(ANYMAIL_SPARKPOST_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 403)
        # Make sure the exception message includes SparkPost's response:
        self.assertIn("Forbidden", str(err))
