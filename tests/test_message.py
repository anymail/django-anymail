from django.core.mail import EmailMultiAlternatives
from django.test import SimpleTestCase
from mock import patch

from anymail.message import AnymailRecipientStatus, AnymailStatus, attach_inline_image

from .utils import AnymailTestMixin, sample_image_content


class InlineImageTests(AnymailTestMixin, SimpleTestCase):
    def setUp(self):
        self.message = EmailMultiAlternatives()
        super().setUp()

    @patch("email.utils.socket.getfqdn")
    def test_default_domain(self, mock_getfqdn):
        """The default Content-ID domain should *not* use local hostname"""
        # (This avoids problems with ESPs that re-use Content-ID as attachment
        # filename: if the local hostname ends in ".com", you can end up with
        # an inline attachment filename that causes Gmail to reject the message.)
        mock_getfqdn.return_value = "server.example.com"
        cid = attach_inline_image(self.message, sample_image_content())
        self.assertRegex(cid, r"[\w.]+@inline",
                         "Content-ID should be a valid Message-ID, "
                         "but _not_ @server.example.com")

    def test_domain_override(self):
        cid = attach_inline_image(self.message, sample_image_content(),
                                  domain="example.org")
        self.assertRegex(cid, r"[\w.]+@example\.org",
                         "Content-ID should be a valid Message-ID @example.org")


class AnymailStatusTests(AnymailTestMixin, SimpleTestCase):
    def test_single_recipient(self):
        recipients = {
            "one@example.com": AnymailRecipientStatus("12345", "sent"),
        }
        status = AnymailStatus()
        status.set_recipient_status(recipients)
        self.assertEqual(status.status, {"sent"})
        self.assertEqual(status.message_id, "12345")
        self.assertEqual(status.recipients, recipients)
        self.assertEqual(repr(status),
                         "AnymailStatus<status={'sent'}, message_id='12345', 1 recipients>")
        self.assertEqual(repr(status.recipients["one@example.com"]),
                         "AnymailRecipientStatus('12345', 'sent')")

    def test_multiple_recipients(self):
        recipients = {
            "one@example.com": AnymailRecipientStatus("12345", "sent"),
            "two@example.com": AnymailRecipientStatus("45678", "queued"),
        }
        status = AnymailStatus()
        status.set_recipient_status(recipients)
        self.assertEqual(status.status, {"queued", "sent"})
        self.assertEqual(status.message_id, {"12345", "45678"})
        self.assertEqual(status.recipients, recipients)
        self.assertEqual(repr(status),
                         "AnymailStatus<status={'queued', 'sent'}, message_id={'12345', '45678'}, 2 recipients>")

    def test_multiple_recipients_same_message_id(self):
        # status.message_id collapses when it's the same for all recipients
        recipients = {
            "one@example.com": AnymailRecipientStatus("12345", "sent"),
            "two@example.com": AnymailRecipientStatus("12345", "queued"),
        }
        status = AnymailStatus()
        status.set_recipient_status(recipients)
        self.assertEqual(status.message_id, "12345")
        self.assertEqual(repr(status),
                         "AnymailStatus<status={'queued', 'sent'}, message_id='12345', 2 recipients>")

    def test_none(self):
        status = AnymailStatus()
        self.assertIsNone(status.status)
        self.assertIsNone(status.message_id)
        self.assertEqual(repr(status), "AnymailStatus<status=None>")

    def test_invalid_message_id(self):
        with self.assertRaisesMessage(TypeError, "Invalid message_id"):
            AnymailRecipientStatus(["id-list", "is-not-valid"], "queued")

    def test_invalid_status(self):
        with self.assertRaisesMessage(ValueError, "Invalid status"):
            AnymailRecipientStatus("12345", "not-a-known-status")
