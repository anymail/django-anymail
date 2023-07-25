import json
from base64 import b64encode
from textwrap import dedent
from unittest.mock import ANY

from django.test import tag

from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.sparkpost import SparkPostInboundWebhookView

from .utils import sample_email_content, sample_image_content
from .webhook_cases import WebhookTestCase


@tag("sparkpost")
class SparkpostInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        event = {
            "protocol": "smtp",
            "rcpt_to": "test@inbound.example.com",
            "msg_from": "envelope-from@example.org",
            "content": {
                # Anymail just parses the raw rfc822 email.
                # SparkPost's other content fields are ignored.
                "email_rfc822_is_base64": False,
                "email_rfc822": dedent(
                    """\
                    Received: from mail.example.org by c.mta1vsmtp.cc.prd.sparkpost ...
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
                    """  # NOQA: E501
                ),
            },
        }
        raw_event = {"msys": {"relay_message": event}}

        response = self.client.post(
            "/anymail/sparkpost/inbound/",
            content_type="application/json",
            data=json.dumps([raw_event]),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=SparkPostInboundWebhookView,
            event=ANY,
            esp_name="SparkPost",
        )
        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertIsNone(event.timestamp)
        self.assertIsNone(event.event_id)
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_event)

        # AnymailInboundMessage - convenience properties
        message = event.message

        self.assertEqual(message.from_email.display_name, "Displayed From")
        self.assertEqual(message.from_email.addr_spec, "from+test@example.org")
        self.assertEqual(
            [str(e) for e in message.to],
            ["Test Inbound <test@inbound.example.com>", "other@example.com"],
        )
        self.assertEqual([str(e) for e in message.cc], ["cc@example.com"])
        self.assertEqual(message.subject, "Test subject")
        self.assertEqual(message.date.isoformat(" "), "2017-10-11 18:31:04-07:00")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""",
        )

        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "test@inbound.example.com")
        self.assertIsNone(message.stripped_text)
        self.assertIsNone(message.stripped_html)
        self.assertIsNone(message.spam_detected)
        self.assertIsNone(message.spam_score)

        # AnymailInboundMessage - other headers
        self.assertEqual(message["Message-ID"], "<CAEPk3R+4Zr@mail.example.org>")
        self.assertEqual(
            message.get_all("Received"),
            [
                "from mail.example.org by c.mta1vsmtp.cc.prd.sparkpost ...",
                "by mail.example.org for <test@inbound.example.com> ...",
                "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
            ],
        )

    def test_attachments(self):
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

        raw_event = {
            "msys": {
                "relay_message": {
                    "protocol": "smtp",
                    "content": {
                        "email_rfc822_is_base64": True,
                        "email_rfc822": b64encode(raw_mime.encode("utf-8")).decode(
                            "ascii"
                        ),
                    },
                }
            }
        }

        response = self.client.post(
            "/anymail/sparkpost/inbound/",
            content_type="application/json",
            data=json.dumps([raw_event]),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=SparkPostInboundWebhookView,
            event=ANY,
            esp_name="SparkPost",
        )
        event = kwargs["event"]
        message = event.message
        attachments = message.attachments  # AnymailInboundMessage convenience accessor
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].get_filename(), "test.txt")
        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_content_text(), "test attachment")
        self.assertEqual(attachments[1].get_content_type(), "message/rfc822")
        self.assertEqualIgnoringHeaderFolding(
            attachments[1].get_content_bytes(), email_content
        )

        # the message attachment (its payload) is fully parsed
        # (see the original in test_files/sample_email.txt)
        att_message = attachments[1].get_payload(0)
        self.assertEqual(att_message.get_content_type(), "multipart/alternative")
        self.assertEqual(att_message["Subject"], "Test email")
        self.assertEqual(att_message.text, "Hi Bob, This is a message. Thanks!\n")

        inlines = message.content_id_map
        self.assertEqual(len(inlines), 1)
        inline = inlines["abc123"]
        self.assertEqual(inline.get_filename(), "image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), image_content)
