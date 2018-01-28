from django.dispatch import receiver

from anymail.backends.test import EmailBackend as TestEmailBackend
from anymail.exceptions import AnymailCancelSend, AnymailRecipientsRefused
from anymail.message import AnymailRecipientStatus
from anymail.signals import pre_send, post_send

from .test_general_backend import TestBackendTestCase


class TestPreSendSignal(TestBackendTestCase):
    """Test Anymail's pre_send signal"""

    def test_pre_send(self):
        """Pre-send receivers invoked for each message, before sending"""
        @receiver(pre_send, weak=False)
        def handle_pre_send(sender, message, esp_name, **kwargs):
            self.assertEqual(self.get_send_count(), 0)  # not sent yet
            self.assertEqual(sender, TestEmailBackend)
            self.assertEqual(message, self.message)
            self.assertEqual(esp_name, "Test")  # the TestEmailBackend's ESP is named "Test"
            self.receiver_called = True
        self.addCleanup(pre_send.disconnect, receiver=handle_pre_send)

        self.receiver_called = False
        self.message.send()
        self.assertTrue(self.receiver_called)
        self.assertEqual(self.get_send_count(), 1)  # sent now

    def test_modify_message_in_pre_send(self):
        """Pre-send receivers can modify message"""
        @receiver(pre_send, weak=False)
        def handle_pre_send(sender, message, esp_name, **kwargs):
            message.to = [email for email in message.to if not email.startswith('bad')]
            message.body += "\nIf you have received this message in error, ignore it"
        self.addCleanup(pre_send.disconnect, receiver=handle_pre_send)

        self.message.to = ['legit@example.com', 'bad@example.com']
        self.message.send()
        params = self.get_send_params()
        self.assertEqual([email.addr_spec for email in params['to']],  # params['to'] is EmailAddress list
                         ['legit@example.com'])
        self.assertRegex(params['text_body'],
                         r"If you have received this message in error, ignore it$")

    def test_cancel_in_pre_send(self):
        """Pre-send receiver can cancel the send"""
        @receiver(pre_send, weak=False)
        def cancel_pre_send(sender, message, esp_name, **kwargs):
            raise AnymailCancelSend("whoa there")
        self.addCleanup(pre_send.disconnect, receiver=cancel_pre_send)

        self.message.send()
        self.assertEqual(self.get_send_count(), 0)  # send API not called


class TestPostSendSignal(TestBackendTestCase):
    """Test Anymail's post_send signal"""

    def test_post_send(self):
        """Post-send receiver called for each message, after sending"""
        @receiver(post_send, weak=False)
        def handle_post_send(sender, message, status, esp_name, **kwargs):
            self.assertEqual(self.get_send_count(), 1)  # already sent
            self.assertEqual(sender, TestEmailBackend)
            self.assertEqual(message, self.message)
            self.assertEqual(status.status, {'sent'})
            self.assertEqual(status.message_id, 0)
            self.assertEqual(status.recipients['to@example.com'].status, 'sent')
            self.assertEqual(status.recipients['to@example.com'].message_id, 0)
            self.assertEqual(esp_name, "Test")  # the TestEmailBackend's ESP is named "Test"
            self.receiver_called = True
        self.addCleanup(post_send.disconnect, receiver=handle_post_send)

        self.receiver_called = False
        self.message.send()
        self.assertTrue(self.receiver_called)

    def test_post_send_exception(self):
        """All post-send receivers called, even if one throws"""
        @receiver(post_send, weak=False)
        def handler_1(sender, message, status, esp_name, **kwargs):
            raise ValueError("oops")
        self.addCleanup(post_send.disconnect, receiver=handler_1)

        @receiver(post_send, weak=False)
        def handler_2(sender, message, status, esp_name, **kwargs):
            self.handler_2_called = True
        self.addCleanup(post_send.disconnect, receiver=handler_2)

        self.handler_2_called = False
        with self.assertRaises(ValueError):
            self.message.send()
        self.assertTrue(self.handler_2_called)

    def test_rejected_recipients(self):
        """Post-send receiver even if AnymailRecipientsRefused is raised"""
        @receiver(post_send, weak=False)
        def handle_post_send(sender, message, status, esp_name, **kwargs):
            self.receiver_called = True
        self.addCleanup(post_send.disconnect, receiver=handle_post_send)

        self.message.anymail_test_response = {
            'recipient_status': {
                'to@example.com': AnymailRecipientStatus(message_id=None, status='rejected')
            }
        }

        self.receiver_called = False
        with self.assertRaises(AnymailRecipientsRefused):
            self.message.send()
        self.assertTrue(self.receiver_called)
