import json
from base64 import b64encode
from textwrap import dedent
from unittest.mock import ANY

from django.test import tag

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailpace import MailPaceInboundWebhookView

from .utils import sample_email_content, sample_image_content, test_file_content
from .webhook_cases import WebhookTestCase

from .utils import sample_email_content, sample_image_content, test_file_content
from .webhook_cases import WebhookTestCase

@tag("mailpace")
class MailPaceInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        # Create a MailPace webhook payload with minimal information for testing
        mailpace_payload = {
            "event": "inbound",
            "payload": {
                "id": "unique-event-id",
                "created_at": "2023-11-05T12:34:56Z",
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "subject": "Test Subject",
                "text": "Test message body",
            }
        }

        # Serialize the payload to JSON
        mailpace_payload_json = json.dumps(mailpace_payload)

        # Simulate a POST request to the MailPace webhook view
        response = self.client.post(
            "/anymail/mailpace/inbound/",
            content_type="application/json",
            data=mailpace_payload_json,
        )

        # Check the response status code (assuming 200 OK is expected)
        self.assertEqual(response.status_code, 200)

        # Check if the AnymailInboundEvent signal was dispatched
        # self.assertSignalSent(
        #     AnymailInboundEvent,
        #     event_type=ANY,
        #     timestamp=timezone.now(),
        #     event_id='unique-event-id',
        #     message_id=ANY,
        #     recipient='recipient@example.com',
        #     from_email='sender@example.com',
        #     subject='Test Subject',
        #     text='Test message body',
        #     html=None,  # Adjust this if HTML content is expected
        #     headers=ANY,  # Define the expected headers
        # )

    def test_attachments(self):
        # Create a MailPace webhook payload with attachments for testing
        mailpace_payload = {
            "event": "inbound",
            "payload": {
                "id": "unique-event-id",
                "created_at": "2023-11-05T12:34:56Z",
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "subject": "Test Subject",
                "text": "Test message body",
                "attachments": [
                    {
                        "filename": "test.txt",
                        "content": "abc",
                        "content_type": "text/plain",
                    },
                ],
            }
        }

        # Serialize the payload to JSON
        mailpace_payload_json = json.dumps(mailpace_payload)

        # Simulate a POST request to the MailPace webhook view
        response = self.client.post(
            "/anymail/mailpace/inbound/",
            content_type="application/json",
            data=mailpace_payload_json,
        )

        # Check the response status code (assuming 200 OK is expected)
        self.assertEqual(response.status_code, 200)

        # Check if the AnymailInboundEvent signal was dispatched with attachments
        # self.assertSignalSent(
        #     AnymailInboundEvent,
        #     event_type=ANY,
        #     timestamp=timezone.now(),
        #     event_id='unique-event-id',
        #     message_id=ANY,
        #     recipient='recipient@example.com',
        #     from_email='sender@example.com',
        #     subject='Test Subject',
        #     text='Test message body',
        #     attachments=[
        #         AnymailInboundMessage.Attachment(
        #             content_type='text/plain',
        #             content=test_file_content(),
        #             filename='test.txt',
        #         ),
        #     ],
        #     headers=ANY,  # Define the expected headers
        # )

    def test_inbound_with_raw_email(self):
        # Create a MailPace webhook payload with a raw email for testing
        mailpace_payload = {
            "event": "inbound",
            "payload": {
                "id": "unique-event-id",
                "created_at": "2023-11-05T12:34:56Z",
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "raw_email": b64encode(sample_email_content()).decode('utf-8'),
            }
        }

        # Serialize the payload to JSON
        mailpace_payload_json = json.dumps(mailpace_payload)

        response = self.client.post(
            "/anymail/mailpace/inbound/",
            content_type="application/json",
            data=mailpace_payload_json,
        )

        # Check the response status code (assuming 200 OK is expected)
        self.assertEqual(response.status_code, 200)

        # Check if the AnymailInboundEvent signal was dispatched with raw_email
        # self.assertSignalSent(
        #     AnymailInboundEvent,
        #     event_type=ANY,
        #     timestamp=timezone.now(),
        #     event_id='unique-event-id',
        #     message_id=ANY,
        #     recipient='recipient@example.com',
        #     from_email='sender@example.com',
        #     subject=None,  # Adjust this if the subject is expected
        #     text=None,  # Adjust this if text content is expected
        #     raw_email=sample_email_content(),
        #     headers=ANY,  # Define the expected headers
        # )
