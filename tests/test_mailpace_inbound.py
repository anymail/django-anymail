import json
from base64 import b64encode
from textwrap import dedent
from unittest.mock import ANY

from django.test import tag

from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailpace import MailPaceInboundWebhookView

from .utils import sample_email_content, sample_image_content
from .webhook_cases import WebhookTestCase


@tag("mailpace")
class MailPaceInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        # Only raw is used by Anymail
        mailpace_payload = {
            "from": "Person A <person_a@test.com>",
            "headers": ["Received: from localhost...", "DKIM-Signature: v=1 a=rsa...;"],
            "messageId": "<3baf4caf-948a-41e6-bc5c-2e99058e6461@mailer.mailpace.com>",
            "raw": dedent(
                """\
                From: A tester <test@example.org>
                Date: Thu, 12 Oct 2017 18:03:30 -0700
                Message-ID: <CAEPk3RKEx@mail.example.org>
                Subject: Raw MIME test
                To: test@inbound.example.com
                MIME-Version: 1.0
                Content-Type: multipart/alternative; boundary="boundary1"

                --boundary1
                Content-Type: text/plain; charset="UTF-8"
                Content-Transfer-Encoding: quoted-printable

                It's a body=E2=80=A6

                --boundary1
                Content-Type: text/html; charset="UTF-8"
                Content-Transfer-Encoding: quoted-printable

                <div dir=3D"ltr">It's a body=E2=80=A6</div

                --boundary1--
                """  # NOQA: E501
            ),
            "to": "Person B <person_b@test.com>",
            "subject": "Email Subject",
            "cc": "Person C <person_c@test.com>",
            "bcc": "Person D <person_d@test.com>",
            "inReplyTo": "<3baf4caf-948a-41e6-bc5c-2e99058e6461@mailer.mailpace.com>",
            "replyTo": "bounces+abcd@test.com",
            "html": "<h1>Email Contents Here</h1>",
            "text": "Text Email Contents",
            "attachments": [
                {
                    "filename": "example.pdf",
                    "content_type": "application/pdf",
                    "content": "base64_encoded_content_of_the_attachment",
                },
            ],
        }

        response = self.client.post(
            "/anymail/mailpace/inbound/",
            content_type="application/json",
            data=json.dumps(mailpace_payload),
        )

        self.assertEqual(response.status_code, 200)

        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailPaceInboundWebhookView,
            event=ANY,
            esp_name="MailPace",
        )

        event = kwargs["event"]

        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")

        message = event.message

        self.assertEqual(message.to[0].address, "test@inbound.example.com")
        self.assertEqual(message["from"], "A tester <test@example.org>")
        self.assertEqual(message.subject, "Raw MIME test")

        self.assertEqual(len(message._headers), 7)

    def test_inbound_attachments(self):
        image_content = sample_image_content()
        email_content = sample_email_content()
        raw_mime = dedent(
            """\
            MIME-Version: 1.0
            From: from@example.org
            Subject: Attachments
            To: test@inbound.example.com
            Content-Type: multipart/mixed; boundary="boundary0"

            --boundary0
            Content-Type: multipart/related; boundary="boundary1"

            --boundary1
            Content-Type: text/html; charset="UTF-8"

            <div>This is the HTML body. It has an inline image: <img src="cid:abc123">.</div>

            --boundary1
            Content-Type: image/png
            Content-Disposition: inline; filename="image.png"
            Content-ID: <abc123>
            Content-Transfer-Encoding: base64

            {image_content_base64}
            --boundary1--
            --boundary0
            Content-Type: text/plain; charset="UTF-8"
            Content-Disposition: attachment; filename="test.txt"

            test attachment
            --boundary0
            Content-Type: message/rfc822; charset="US-ASCII"
            Content-Disposition: attachment
            X-Comment: (the only valid transfer encodings for message/* are 7bit, 8bit, and binary)

            {email_content}
            --boundary0--
            """  # NOQA: E501
        ).format(
            image_content_base64=b64encode(image_content).decode("ascii"),
            email_content=email_content.decode("ascii"),
        )

        # Only raw is used by Anymail
        mailpace_payload = {
            "from": "Person A <person_a@test.com>",
            "headers": ["Received: from localhost...", "DKIM-Signature: v=1 a=rsa...;"],
            "messageId": "<3baf4caf-948a-41e6-bc5c-2e99058e6461@mailer.mailpace.com>",
            "raw": raw_mime,
            "to": "Person B <person_b@test.com>",
            "subject": "Email Subject",
            "cc": "Person C <person_c@test.com>",
            "bcc": "Person D <person_d@test.com>",
            "inReplyTo": "<3baf4caf-948a-41e6-bc5c-2e99058e6461@mailer.mailpace.com>",
            "replyTo": "bounces+abcd@test.com",
            "html": "<h1>Email Contents Here</h1>",
            "text": "Text Email Contents",
            "attachments": [
                {
                    "filename": "example.pdf",
                    "content_type": "application/pdf",
                    "content": "base64_encoded_content_of_the_attachment",
                },
            ],
        }

        response = self.client.post(
            "/anymail/mailpace/inbound/",
            content_type="application/json",
            data=json.dumps(mailpace_payload),
        )

        self.assertEqual(response.status_code, 200)

        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailPaceInboundWebhookView,
            event=ANY,
            esp_name="MailPace",
        )

        event = kwargs["event"]

        self.assertIsInstance(event, AnymailInboundEvent)

        message = event.message

        self.assertEqual(message.to[0].address, "test@inbound.example.com")

        self.assertEqual(len(message._headers), 5)
        self.assertEqual(len(message.attachments), 2)
        attachment = message.attachments[0]
        self.assertEqual(attachment.get_filename(), "test.txt")
