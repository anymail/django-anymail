import os
import unittest

from django.test import SimpleTestCase, tag

from anymail.message import AnymailMessage, attach_inline_image

from .utils import AnymailTestMixin, override_settings, sample_image_content

API_KEY = os.getenv("ANYMAIL_TEST_MAILCHANNELS_API_KEY")
FROM_EMAIL = os.getenv("ANYMAIL_TEST_MAILCHANNELS_FROM_EMAIL")
TO_EMAIL = os.getenv("ANYMAIL_TEST_MAILCHANNELS_TO_EMAIL")


@tag("mailchannels", "live")
@unittest.skipUnless(
    API_KEY and FROM_EMAIL and TO_EMAIL,
    "Set ANYMAIL_TEST_MAILCHANNELS_API_KEY, ANYMAIL_TEST_MAILCHANNELS_FROM_EMAIL "
    "and ANYMAIL_TEST_MAILCHANNELS_TO_EMAIL to run live MailChannels tests",
)
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.mailchannels.EmailBackend",
            "OPTIONS": {"api_key": API_KEY},
        }
    }
)
class MailChannelsIntegrationTests(AnymailTestMixin, SimpleTestCase):
    """Queues real mail. Use an authorized sender and controlled recipient.

    Queue acceptance alone does not verify rendering, envelope or delivery.
    Inspect the received message and MailChannels events separately.
    """

    def test_queue_multipart_with_attachments(self):
        message = AnymailMessage(
            "Anymail MailChannels integration test",
            "Text content",
            FROM_EMAIL,
            [TO_EMAIL],
        )
        cid = attach_inline_image(message, sample_image_content(), filename="logo.png")
        message.attach_alternative(
            f'<p>HTML content</p><img src="cid:{cid}">', "text/html"
        )
        message.attach("test.txt", "Test attachment", "text/plain")
        self.assertEqual(message.send(), 1)
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertTrue(message.anymail_status.message_id)

    def test_queue_merge(self):
        message = AnymailMessage(
            "Anymail MailChannels merge test",
            "Hello {{name}}",
            FROM_EMAIL,
            [TO_EMAIL],
            merge_data={TO_EMAIL: {"name": "Anymail"}},
            merge_headers={TO_EMAIL: {"X-Anymail-Test": "merge"}},
        )
        self.assertEqual(message.send(), 1)
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertTrue(message.anymail_status.message_id)
