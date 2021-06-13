import json
from io import BytesIO
from textwrap import dedent
from unittest.mock import ANY

from django.test import tag

from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.sendgrid import SendGridInboundWebhookView

from .utils import dedent_bytes, sample_image_content, sample_email_content
from .webhook_cases import WebhookTestCase


@tag('sendgrid')
class SendgridInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        raw_event = {
            'headers': dedent("""\
                Received: from mail.example.org by mx987654321.sendgrid.net ...
                Received: by mail.example.org for <test@inbound.example.com> ...
                DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=example.org; ...
                MIME-Version: 1.0
                Received: by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)
                From: "Displayed From" <from+test@example.org>
                Date: Wed, 11 Oct 2017 18:31:04 -0700
                Message-ID: <CAEPk3R+4Zr@mail.example.org>
                Subject: Test subject
                To: "Test Inbound" <test@inbound.example.com>, other@example.com
                Cc: cc@example.com
                Content-Type: multipart/mixed; boundary="94eb2c115edcf35387055b61f849"
                """),
            'from': 'Displayed From <from+test@example.org>',
            'to': 'Test Inbound <test@inbound.example.com>, other@example.com',
            'subject': "Test subject",
            'text': "Test body plain",
            'html': "<div>Test body html</div>",
            'attachments': "0",
            'charsets': '{"to":"UTF-8","html":"UTF-8","subject":"UTF-8","from":"UTF-8","text":"UTF-8"}',
            'envelope': '{"to":["test@inbound.example.com"],"from":"envelope-from@example.org"}',
            'sender_ip': "10.10.1.71",
            'dkim': "{@example.org : pass}",  # yep, SendGrid uses not-exactly-json for this field
            'SPF': "pass",
            'spam_score': "1.7",
            'spam_report': 'Spam detection software, running on the system "mx987654321.sendgrid.net", '
                           'has identified this incoming email as possible spam...',
        }
        response = self.client.post('/anymail/sendgrid/inbound/', data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=SendGridInboundWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        # AnymailInboundEvent
        event = kwargs['event']
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, 'inbound')
        self.assertIsNone(event.timestamp)
        self.assertIsNone(event.event_id)
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event.POST.dict(), raw_event)  # esp_event is a Django HttpRequest

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
        self.assertIsNone(message.stripped_text)
        self.assertIsNone(message.stripped_html)
        self.assertIsNone(message.spam_detected)  # SendGrid doesn't give a simple yes/no; check the score yourself
        self.assertEqual(message.spam_score, 1.7)

        # AnymailInboundMessage - other headers
        self.assertEqual(message['Message-ID'], "<CAEPk3R+4Zr@mail.example.org>")
        self.assertEqual(message.get_all('Received'), [
            "from mail.example.org by mx987654321.sendgrid.net ...",
            "by mail.example.org for <test@inbound.example.com> ...",
            "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
        ])

    def test_attachments(self):
        att1 = BytesIO('test attachment'.encode('utf-8'))
        att1.name = 'test.txt'
        image_content = sample_image_content()
        att2 = BytesIO(image_content)
        att2.name = 'image.png'
        email_content = sample_email_content()
        att3 = BytesIO(email_content)
        att3.content_type = 'message/rfc822; charset="us-ascii"'
        raw_event = {
            'headers': '',
            'attachments': '3',
            'attachment-info': json.dumps({
                "attachment3": {"filename": "", "name": "", "charset": "US-ASCII", "type": "message/rfc822"},
                "attachment2": {"filename": "image.png", "name": "image.png", "type": "image/png",
                                "content-id": "abc123"},
                "attachment1": {"filename": "test.txt", "name": "test.txt", "type": "text/plain"},
            }),
            'content-ids': '{"abc123": "attachment2"}',
            'attachment1': att1,
            'attachment2': att2,  # inline
            'attachment3': att3,
        }

        response = self.client.post('/anymail/sendgrid/inbound/', data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=SendGridInboundWebhookView,
                                                      event=ANY, esp_name='SendGrid')
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

    def test_inbound_mime(self):
        # SendGrid has an option to send the full, raw MIME message
        raw_event = {
            'email': dedent("""\
                From: A tester <test@example.org>
                Date: Thu, 12 Oct 2017 18:03:30 -0700
                Message-ID: <CAEPk3RKEx@mail.example.org>
                Subject: Raw MIME test
                To: test@inbound.example.com
                MIME-Version: 1.0
                Content-Type: multipart/alternative; boundary="94eb2c05e174adb140055b6339c5"

                --94eb2c05e174adb140055b6339c5
                Content-Type: text/plain; charset="UTF-8"
                Content-Transfer-Encoding: quoted-printable

                It's a body=E2=80=A6

                --94eb2c05e174adb140055b6339c5
                Content-Type: text/html; charset="UTF-8"
                Content-Transfer-Encoding: quoted-printable

                <div dir=3D"ltr">It's a body=E2=80=A6</div>

                --94eb2c05e174adb140055b6339c5--
                """),
            'from': 'A tester <test@example.org>',
            'to': 'test@inbound.example.com',
            'subject': "Raw MIME test",
            'charsets': '{"to":"UTF-8","subject":"UTF-8","from":"UTF-8"}',
            'envelope': '{"to":["test@inbound.example.com"],"from":"envelope-from@example.org"}',
            'sender_ip': "10.10.1.71",
            'dkim': "{@example.org : pass}",  # yep, SendGrid uses not-exactly-json for this field
            'SPF': "pass",
            'spam_score': "1.7",
            'spam_report': 'Spam detection software, running on the system "mx987654321.sendgrid.net", '
                           'has identified this incoming email as possible spam...',
        }

        response = self.client.post('/anymail/sendgrid/inbound/', data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=SendGridInboundWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        message = event.message
        self.assertEqual(message.envelope_sender, 'envelope-from@example.org')
        self.assertEqual(message.envelope_recipient, 'test@inbound.example.com')
        self.assertEqual(message.subject, 'Raw MIME test')
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(message.html, """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""")

    def test_inbound_charsets(self):
        # Captured (sanitized) from actual SendGrid inbound webhook payload 7/2020,
        # using a test message constructed with a variety of charsets:
        raw_post = dedent_bytes(b"""\
            --xYzZY
            Content-Disposition: form-data; name="headers"

            Date: Fri, 24 Jul 2020 16:43:46 UTC
            To: =?utf-8?q?R=C3=A9cipiendaire_pr=C3=A9cieux?= <inbound@sg.example.com>
            From: =?utf-8?q?Op=C3=A9rateur?= de test <sender@example.com>
            Subject: =?cp850?q?Como_usted_pidi=A2?=

            --xYzZY
            Content-Disposition: form-data; name="subject"

            Como usted pidi\xa2
            --xYzZY
            Content-Disposition: form-data; name="to"

            R\xc3\xa9cipiendaire pr\xc3\xa9cieux <inbound@sg.example.com>
            --xYzZY
            Content-Disposition: form-data; name="html"

            <p>\xbfEsto se ve como esperabas?</p>
            --xYzZY
            Content-Disposition: form-data; name="from"

            Op\xc3\xa9rateur de test <sender@example.com>
            --xYzZY
            Content-Disposition: form-data; name="text"

            Test the ESP\x92s inbound charset handling\x85
            --xYzZY
            Content-Disposition: form-data; name="charsets"

            {"to":"UTF-8","cc":"UTF-8","html":"iso-8859-1","subject":"cp850","from":"UTF-8","text":"windows-1252"}
            --xYzZY--
            """).replace(b"\n", b"\r\n")

        response = self.client.post('/anymail/sendgrid/inbound/', data=raw_post,
                                    content_type="multipart/form-data; boundary=xYzZY")
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=SendGridInboundWebhookView,
                                                      event=ANY, esp_name='SendGrid')
        event = kwargs['event']
        message = event.message

        self.assertEqual(message.from_email.display_name, "Opérateur de test")
        self.assertEqual(message.from_email.addr_spec, "sender@example.com")
        self.assertEqual(len(message.to), 1)
        self.assertEqual(message.to[0].display_name, "Récipiendaire précieux")
        self.assertEqual(message.to[0].addr_spec, "inbound@sg.example.com")
        self.assertEqual(message.subject, "Como usted pidió")
        self.assertEqual(message.text, "Test the ESP’s inbound charset handling…")
        self.assertEqual(message.html, "<p>¿Esto se ve como esperabas?</p>")
