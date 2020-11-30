import os
import unittest
from datetime import datetime, timedelta

from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin, sample_image_path

ANYMAIL_TEST_SENDGRID_API_KEY = os.getenv('ANYMAIL_TEST_SENDGRID_API_KEY')
ANYMAIL_TEST_SENDGRID_TEMPLATE_ID = os.getenv('ANYMAIL_TEST_SENDGRID_TEMPLATE_ID')


@tag('sendgrid', 'live')
@unittest.skipUnless(ANYMAIL_TEST_SENDGRID_API_KEY,
                     "Set ANYMAIL_TEST_SENDGRID_API_KEY environment variable "
                     "to run SendGrid integration tests")
@override_settings(ANYMAIL_SENDGRID_API_KEY=ANYMAIL_TEST_SENDGRID_API_KEY,
                   ANYMAIL_SENDGRID_SEND_DEFAULTS={"esp_extra": {
                       "mail_settings": {"sandbox_mode": {"enable": True}},
                   }},
                   EMAIL_BACKEND="anymail.backends.sendgrid.EmailBackend")
class SendGridBackendIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """SendGrid v3 API integration tests

    These tests run against the **live** SendGrid API, using the
    environment variable `ANYMAIL_TEST_SENDGRID_API_KEY` as the API key
    If those variables are not set, these tests won't run.

    The SEND_DEFAULTS above force SendGrid's v3 sandbox mode, which avoids sending mail.
    (Sandbox sends also don't show in the activity feed, so disable that for live debugging.)

    The tests also use SendGrid's "sink domain" @sink.sendgrid.net for recipient addresses.
    https://support.sendgrid.com/hc/en-us/articles/201995663-Safely-Test-Your-Sending-Speed

    """

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage('Anymail SendGrid integration test', 'Text content',
                                      'from@example.com', ['to@sink.sendgrid.net'])
        self.message.attach_alternative('<p>HTML content</p>', "text/html")

    def test_simple_send(self):
        # Example of getting the SendGrid send status and message id from the message
        sent_count = self.message.send()
        self.assertEqual(sent_count, 1)

        anymail_status = self.message.anymail_status
        sent_status = anymail_status.recipients['to@sink.sendgrid.net'].status
        message_id = anymail_status.recipients['to@sink.sendgrid.net'].message_id

        self.assertEqual(sent_status, 'queued')  # SendGrid always queues
        self.assertUUIDIsValid(message_id)  # Anymail generates a UUID tracking id
        self.assertEqual(anymail_status.status, {sent_status})  # set of all recipient statuses
        self.assertEqual(anymail_status.message_id, message_id)

    def test_all_options(self):
        send_at = datetime.now().replace(microsecond=0) + timedelta(minutes=2)
        message = AnymailMessage(
            subject="Anymail all-options integration test",
            body="This is the text body",
            from_email='"Test From, with comma" <from@example.com>',
            to=["to1@sink.sendgrid.net", '"Recipient 2, OK?" <to2@sink.sendgrid.net>'],
            cc=["cc1@sink.sendgrid.net", "Copy 2 <cc2@sink.sendgrid.net>"],
            bcc=["bcc1@sink.sendgrid.net", "Blind Copy 2 <bcc2@sink.sendgrid.net>"],
            reply_to=['"Reply, with comma" <reply@example.com>'],  # v3 only supports single reply-to
            headers={"X-Anymail-Test": "value", "X-Anymail-Count": 3},

            metadata={"meta1": "simple string", "meta2": 2},
            send_at=send_at,
            tags=["tag 1", "tag 2"],
            track_clicks=True,
            track_opens=True,
            # esp_extra={'asm': {'group_id': 1}},  # this breaks activity feed if you don't have an asm group
        )
        message.attach("attachment1.txt", "Here is some\ntext for you", "text/plain")
        message.attach("attachment2.csv", "ID,Name\n1,Amy Lina", "text/csv")
        cid = message.attach_inline_image_file(sample_image_path())
        message.attach_alternative(
            "<p><b>HTML:</b> with <a href='http://example.com'>link</a>"
            "and image: <img src='cid:%s'></div>" % cid,
            "text/html")

        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})  # SendGrid always queues

    def test_merge_data(self):
        message = AnymailMessage(
            subject="Anymail merge_data test: %field%",
            body="This body includes merge data: %field%",
            from_email="Test From <from@example.com>",
            to=["to1@sink.sendgrid.net", "Recipient 2 <to2@sink.sendgrid.net>"],
            reply_to=['"Merge data in reply name: %field%" <reply@example.com>'],
            merge_data={
                'to1@sink.sendgrid.net': {'field': 'one'},
                'to2@sink.sendgrid.net': {'field': 'two'},
            },
            esp_extra={
                'merge_field_format': '%{}%',
            },
        )
        message.send()
        recipient_status = message.anymail_status.recipients
        self.assertEqual(recipient_status['to1@sink.sendgrid.net'].status, 'queued')
        self.assertEqual(recipient_status['to2@sink.sendgrid.net'].status, 'queued')

    @unittest.skipUnless(ANYMAIL_TEST_SENDGRID_TEMPLATE_ID,
                         "Set the ANYMAIL_TEST_SENDGRID_TEMPLATE_ID environment variable "
                         "to a template in your SendGrid account to test stored templates")
    def test_stored_template(self):
        message = AnymailMessage(
            from_email="Test From <from@example.com>",
            to=["to@sink.sendgrid.net"],
            # Anymail's live test template has merge fields "name", "order_no", and "dept"...
            template_id=ANYMAIL_TEST_SENDGRID_TEMPLATE_ID,
            merge_data={
                'to@sink.sendgrid.net': {
                    'name': "Test Recipient",
                    'order_no': "12345",
                },
            },
            merge_global_data={'dept': "Fulfillment"},
        )
        message.send()
        self.assertEqual(message.anymail_status.status, {'queued'})

    @override_settings(ANYMAIL_SENDGRID_API_KEY="Hey, that's not an API key!")
    def test_invalid_api_key(self):
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        self.assertEqual(err.status_code, 401)
        # Make sure the exception message includes SendGrid's response:
        self.assertIn("authorization grant is invalid", str(err))
