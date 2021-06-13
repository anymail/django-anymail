import json
from base64 import b64encode
from unittest.mock import ANY

from django.test import tag

from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailjet import MailjetInboundWebhookView

from .utils import sample_image_content, sample_email_content
from .webhook_cases import WebhookTestCase


@tag('mailjet')
class MailjetInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        raw_event = {
            "Sender": "envelope-from@example.org",
            "Recipient": "test@inbound.example.com",
            "Date": "20171012T013104",  # this is just the Date header from the sender, parsed to UTC
            "From": '"Displayed From" <from+test@example.org>',
            "Subject": "Test subject",
            "Headers": {
                "Return-Path": ["<bounce-handler=from+test%example.org@mail.example.org>"],
                "Received": [
                    "from mail.example.org by parse.mailjet.com ..."
                    "by mail.example.org for <test@inbound.example.com> ...",
                    "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
                ],
                "MIME-Version": ["1.0"],
                "From": '"Displayed From" <from+test@example.org>',
                "Date": "Wed, 11 Oct 2017 18:31:04 -0700",
                "Message-ID": "<CAEPk3R+4Zr@mail.example.org>",
                "Subject": "Test subject",
                "To": "Test Inbound <test@inbound.example.com>, other@example.com",
                "Cc": "cc@example.com",
                "Reply-To": "from+test@milter.example.org",
                "Content-Type": ["multipart/alternative; boundary=\"boundary0\""],
            },
            "Parts": [{
                "Headers": {
                    "Content-Type": ['text/plain; charset="UTF-8"']
                },
                "ContentRef": "Text-part"
            }, {
                "Headers": {
                    "Content-Type": ['text/html; charset="UTF-8"'],
                    "Content-Transfer-Encoding": ["quoted-printable"]
                },
                "ContentRef": "Html-part"
            }],
            "Text-part": "Test body plain",
            "Html-part": "<div>Test body html</div>",
            "SpamAssassinScore": "1.7"
        }

        response = self.client.post('/anymail/mailjet/inbound/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=MailjetInboundWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        # AnymailInboundEvent
        event = kwargs['event']
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, 'inbound')
        self.assertIsNone(event.timestamp)  # Mailjet doesn't provide inbound event timestamp
        self.assertIsNone(event.event_id)  # Mailjet doesn't provide inbound event id
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_event)

        # AnymailInboundMessage - convenience properties
        message = event.message

        self.assertEqual(message.from_email.display_name, 'Displayed From')
        self.assertEqual(message.from_email.addr_spec, 'from+test@example.org')
        self.assertEqual([str(e) for e in message.to],
                         ['Test Inbound <test@inbound.example.com>', 'other@example.com'])
        self.assertEqual([str(e) for e in message.cc],
                         ['cc@example.com'])
        self.assertEqual(message.subject, 'Test subject')
        self.assertEqual(message.date.isoformat(" "), "2017-10-11 18:31:04-07:00")
        self.assertEqual(message.text, 'Test body plain')
        self.assertEqual(message.html, '<div>Test body html</div>')

        self.assertEqual(message.envelope_sender, 'envelope-from@example.org')
        self.assertEqual(message.envelope_recipient, 'test@inbound.example.com')
        self.assertIsNone(message.stripped_text)  # Mailjet doesn't provide stripped plaintext body
        self.assertIsNone(message.stripped_html)  # Mailjet doesn't provide stripped html
        self.assertIsNone(message.spam_detected)  # Mailjet doesn't provide spam boolean
        self.assertEqual(message.spam_score, 1.7)

        # AnymailInboundMessage - other headers
        self.assertEqual(message['Message-ID'], "<CAEPk3R+4Zr@mail.example.org>")
        self.assertEqual(message['Reply-To'], "from+test@milter.example.org")
        self.assertEqual(message.get_all('Received'), [
            "from mail.example.org by parse.mailjet.com ..."
            "by mail.example.org for <test@inbound.example.com> ...",
            "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
        ])

    def test_attachments(self):
        image_content = sample_image_content()
        email_content = sample_email_content()
        raw_event = {
            "Headers": {
                "MIME-Version": ["1.0"],
                "Content-Type": ["multipart/mixed; boundary=\"boundary0\""],
            },
            "Parts": [{
                "Headers": {"Content-Type": ['multipart/related; boundary="boundary1"']}
            }, {
                "Headers": {"Content-Type": ['multipart/alternative; boundary="boundary2"']}
            }, {
                "Headers": {"Content-Type": ['text/plain; charset="UTF-8"']},
                "ContentRef": "Text-part"
            }, {
                "Headers": {
                    "Content-Type": ['text/html; charset="UTF-8"'],
                    "Content-Transfer-Encoding": ["quoted-printable"]
                },
                "ContentRef": "Html-part"
            }, {
                "Headers": {
                    "Content-Type": ['text/plain'],
                    "Content-Disposition": ['attachment; filename="test.txt"'],
                    "Content-Transfer-Encoding": ["quoted-printable"],
                },
                "ContentRef": "Attachment1"
            }, {
                "Headers": {
                    "Content-Type": ['image/png; name="image.png"'],
                    "Content-Disposition": ['inline; filename="image.png"'],
                    "Content-Transfer-Encoding": ["base64"],
                    "Content-ID": ["<abc123>"],
                },
                "ContentRef": "InlineAttachment1"
            }, {
                "Headers": {
                    "Content-Type": ['message/rfc822; charset="US-ASCII"'],
                    "Content-Disposition": ['attachment'],
                },
                "ContentRef": "Attachment2"
            }],
            "Text-part": "Test body plain",
            "Html-part": "<div>Test body html <img src='cid:abc123'></div>",
            "InlineAttachment1": b64encode(image_content).decode('ascii'),
            "Attachment1": b64encode('test attachment'.encode('utf-8')).decode('ascii'),
            "Attachment2": b64encode(email_content).decode('ascii'),
        }

        response = self.client.post('/anymail/mailjet/inbound/',
                                    content_type='application/json', data=json.dumps(raw_event))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=MailjetInboundWebhookView,
                                                      event=ANY, esp_name='Mailjet')
        event = kwargs['event']
        message = event.message
        attachments = message.attachments  # AnymailInboundMessage convenience accessor
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].get_filename(), 'test.txt')
        self.assertEqual(attachments[0].get_content_type(), 'text/plain')
        self.assertEqual(attachments[0].get_content_text(), 'test attachment')
        self.assertEqual(attachments[1].get_content_type(), 'message/rfc822')
        self.assertEqualIgnoringHeaderFolding(attachments[1].get_content_bytes(), email_content)

        inlines = message.inline_attachments
        self.assertEqual(len(inlines), 1)
        inline = inlines['abc123']
        self.assertEqual(inline.get_filename(), 'image.png')
        self.assertEqual(inline.get_content_type(), 'image/png')
        self.assertEqual(inline.get_content_bytes(), image_content)
