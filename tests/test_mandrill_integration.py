import os
import unittest

from django.core import mail
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError, AnymailRecipientsRefused
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_MANDRILL_API_KEY = os.getenv('ANYMAIL_TEST_MANDRILL_API_KEY')


@tag('mandrill', 'live')
@unittest.skipUnless(ANYMAIL_TEST_MANDRILL_API_KEY,
                     "Set ANYMAIL_TEST_MANDRILL_API_KEY environment variable to run integration tests")
@override_settings(MANDRILL_API_KEY=ANYMAIL_TEST_MANDRILL_API_KEY,
                   EMAIL_BACKEND="anymail.backends.mandrill.EmailBackend")
class MandrillBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Mandrill API integration tests

    These tests run against the **live** Mandrill API, using the
    environment variable `ANYMAIL_TEST_MANDRILL_API_KEY` as the API key.
    If that variable is not set, these tests won't run.

    See https://mandrill.zendesk.com/hc/en-us/articles/205582447
    for info on Mandrill test keys.

    """

    def setUp(self):
        super().setUp()
        self.message = mail.EmailMultiAlternatives('Anymail Mandrill integration test', 'Text content',
                                                   'from@example.com', ['test+to1@anymail.info'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the Mandrill send status and _id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        # noinspection PyUnresolvedReferences
        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['test+to1@anymail.info'].status
        message_id = anymail_status.recipients['test+to1@anymail.info'].message_id

        self.assertIn(sent_status, ['sent', 'queued'])  # successful send (could still bounce later)
        self.assertGreater(len(message_id), 0)  # don't know what it'll be, but it should exist

        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)  # because only a single recipient (else would be a set)

    def test_all_options(self):
        message = AnymailMessage(
            subject="Anymail Mandrill all-options integration test",
            body="This is the text body",
            from_email="Test From <from@example.com>",
            to=["test+to1@anymail.info", "Recipient 2 <test+to2@anymail.info>"],
            cc=["test+cc1@anymail.info", "Copy 2 <test+cc2@anymail.info>"],
            bcc=["test+bcc1@anymail.info", "Blind Copy 2 <test+bcc2@anymail.info>"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            headers={"X-Anymail-Test": "value"},

            # no metadata, send_at, track_clicks support
            tags=["tag 1"],  # max one tag
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
        self.assertTrue(message.anymail_status.status.issubset({'queued', 'sent'}))

    def test_invalid_from(self):
        # Example of trying to send from an invalid address
        # Mandrill returns a 500 response (which raises a MandrillAPIError)
        self.message.from_email = 'webmaster@localhost'  # Django default DEFAULT_FROM_EMAIL
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 500)
        self.assertIn("email address is invalid", str(err))

    def test_invalid_to(self):
        # Example of detecting when a recipient is not a valid email address
        self.message.to = ['invalid@localhost']
        try:
            self.message.send()
        except AnymailRecipientsRefused:
            # Mandrill refused to deliver the mail -- message.anymail_status will tell you why:
            # noinspection PyUnresolvedReferences
            anymail_status = self.message.anymail_status
            self.assertEqual(anymail_status.recipients['invalid@localhost'].status, 'invalid')
            self.assertEqual(anymail_status.status, {'invalid'})
        else:
            # Sometimes Mandrill queues these test sends
            # noinspection PyUnresolvedReferences
            if self.message.anymail_status.status == {'queued'}:
                self.skipTest("Mandrill queued the send -- can't complete this test")
            else:
                self.fail("Anymail did not raise AnymailRecipientsRefused for invalid recipient")

    def test_rejected_to(self):
        # Example of detecting when a recipient is on Mandrill's rejection blacklist
        self.message.to = ['reject@test.mandrillapp.com']
        try:
            self.message.send()
        except AnymailRecipientsRefused:
            # Mandrill refused to deliver the mail -- message.anymail_status will tell you why:
            # noinspection PyUnresolvedReferences
            anymail_status = self.message.anymail_status
            self.assertEqual(anymail_status.recipients['reject@test.mandrillapp.com'].status, 'rejected')
            self.assertEqual(anymail_status.status, {'rejected'})
        else:
            # Sometimes Mandrill queues these test sends
            # noinspection PyUnresolvedReferences
            if self.message.anymail_status.status == {'queued'}:
                self.skipTest("Mandrill queued the send -- can't complete this test")
            else:
                self.fail("Anymail did not raise AnymailRecipientsRefused for blacklist recipient")

    @override_settings(MANDRILL_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        # Example of trying to send with an invalid MANDRILL_API_KEY
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 500)
        # Make sure the exception message includes Mandrill's response:
        self.assertIn("Invalid API key", str(err))
