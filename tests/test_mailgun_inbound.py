import json
from datetime import datetime, timezone
from io import BytesIO
from textwrap import dedent
from unittest.mock import ANY

from django.test import override_settings, tag

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailgun import MailgunInboundWebhookView

from .test_mailgun_webhooks import (
    TEST_WEBHOOK_SIGNING_KEY,
    mailgun_sign_legacy_payload,
    mailgun_sign_payload,
    querydict_to_postdict,
)
from .utils import (
    encode_multipart,
    make_fileobj,
    sample_email_content,
    sample_image_content,
)
from .webhook_cases import WebhookTestCase


@tag("mailgun")
@override_settings(ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY=TEST_WEBHOOK_SIGNING_KEY)
class MailgunInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "token": "06c96bafc3f42a66b9edd546347a2fe18dc23461fe80dc52f0",
                "timestamp": "1461261330",
                "recipient": "test@inbound.example.com",
                "sender": "envelope-from@example.org",
                "message-headers": json.dumps(
                    [
                        [
                            "X-Mailgun-Spam-Rules",
                            "DKIM_SIGNED, DKIM_VALID, DKIM_VALID_AU, ...",
                        ],
                        ["X-Mailgun-Dkim-Check-Result", "Pass"],
                        ["X-Mailgun-Spf", "Pass"],
                        ["X-Mailgun-Sscore", "1.7"],
                        ["X-Mailgun-Sflag", "No"],
                        ["X-Mailgun-Incoming", "Yes"],
                        ["X-Envelope-From", "<envelope-from@example.org>"],
                        ["Received", "from mail.example.org by mxa.mailgun.org ..."],
                        [
                            "Received",
                            "by mail.example.org for <test@inbound.example.com> ...",
                        ],
                        [
                            "Dkim-Signature",
                            "v=1; a=rsa-sha256; c=relaxed/relaxed; d=example.org; ...",
                        ],
                        ["Mime-Version", "1.0"],
                        [
                            "Received",
                            "by 10.10.1.71 with HTTP;"
                            " Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
                        ],
                        ["From", '"Displayed From" <from+test@example.org>'],
                        ["Date", "Wed, 11 Oct 2017 18:31:04 -0700"],
                        ["Message-Id", "<CAEPk3R+4Zr@mail.example.org>"],
                        ["Subject", "Test subject"],
                        [
                            "To",
                            '"Test Inbound" <test@inbound.example.com>,'
                            " other@example.com",
                        ],
                        ["Cc", "cc@example.com"],
                        [
                            "Content-Type",
                            'multipart/mixed; boundary="089e0825ccf874a0bb055b4f7e23"',
                        ],
                    ]
                ),
                "body-plain": "Test body plain",
                "body-html": "<div>Test body html</div>",
                "stripped-html": "stripped html body",
                "stripped-text": "stripped plaintext body",
            }
        )
        response = self.client.post("/anymail/mailgun/inbound/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailgunInboundWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp, datetime(2016, 4, 21, 17, 55, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(
            event.event_id, "06c96bafc3f42a66b9edd546347a2fe18dc23461fe80dc52f0"
        )
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(querydict_to_postdict(event.esp_event.POST), raw_event)

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
        self.assertEqual(message.text, "Test body plain")
        self.assertEqual(message.html, "<div>Test body html</div>")

        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "test@inbound.example.com")
        self.assertEqual(message.stripped_text, "stripped plaintext body")
        self.assertEqual(message.stripped_html, "stripped html body")
        self.assertIs(message.spam_detected, False)
        self.assertEqual(message.spam_score, 1.7)

        # AnymailInboundMessage - other headers
        self.assertEqual(message["Message-ID"], "<CAEPk3R+4Zr@mail.example.org>")
        self.assertEqual(
            message.get_all("Received"),
            [
                "from mail.example.org by mxa.mailgun.org ...",
                "by mail.example.org for <test@inbound.example.com> ...",
                "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
            ],
        )

    def test_attachments(self):
        att1 = BytesIO("test attachment".encode("utf-8"))
        att1.name = "test.txt"
        image_content = sample_image_content()
        att2 = BytesIO(image_content)
        att2.name = "image.png"
        email_content = sample_email_content()
        att3 = BytesIO(email_content)
        att3.name = "\\share\\mail\\forwarded.msg"
        att3.content_type = 'message/rfc822; charset="us-ascii"'
        raw_event = mailgun_sign_legacy_payload(
            {
                "message-headers": "[]",
                "attachment-count": "3",
                "content-id-map": """{"<abc123>": "attachment-2"}""",
                "attachment-1": att1,
                "attachment-2": att2,  # inline
                "attachment-3": att3,
            }
        )

        response = self.client.post("/anymail/mailgun/inbound/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailgunInboundWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        message = event.message
        attachments = message.attachments  # AnymailInboundMessage convenience accessor
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].get_filename(), "test.txt")
        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_content_text(), "test attachment")
        # Django strips paths:
        self.assertEqual(attachments[1].get_filename(), "forwarded.msg")
        self.assertEqual(attachments[1].get_content_type(), "message/rfc822")
        self.assertEqualIgnoringHeaderFolding(
            attachments[1].get_content_bytes(), email_content
        )

        inlines = message.inline_attachments
        self.assertEqual(len(inlines), 1)
        inline = inlines["abc123"]
        self.assertEqual(inline.get_filename(), "image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), image_content)

    def test_filtered_attachment_filenames(self):
        # Make sure the inbound webhook can deal with missing fields caused by
        # Django's multipart/form-data filename filtering. (The attachments are lost,
        # but shouldn't cause errors in the inbound webhook.)
        filenames = [
            "",
            "path\\",
            "path/" ".",
            "path\\.",
            "path/.",
            "..",
            "path\\..",
            "path/..",
        ]
        num_attachments = len(filenames)
        payload = {
            "attachment-%d"
            % (i + 1): make_fileobj(
                "content", filename=filenames[i], content_type="text/pdf"
            )
            for i in range(num_attachments)
        }
        payload.update(
            {
                "message-headers": "[]",
                "attachment-count": str(num_attachments),
            }
        )

        # Must do our own multipart/form-data encoding for empty filenames:
        response = self.client.post(
            "/anymail/mailgun/inbound/",
            data=encode_multipart("BoUnDaRy", mailgun_sign_legacy_payload(payload)),
            content_type="multipart/form-data; boundary=BoUnDaRy",
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailgunInboundWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )

        # Different Django releases strip different filename patterns.
        # Just verify that at least some attachments got dropped (so the test is valid)
        # without causing an error in the inbound webhook:
        attachments = kwargs["event"].message.attachments
        self.assertLess(len(attachments), num_attachments)

    def test_unusual_content_id_map(self):
        # Under unknown conditions, Mailgun appears to generate a content-id-map with
        # multiple empty keys (and possibly other duplicate keys). We still want to
        # correctly identify inline attachments from it.
        raw_event = mailgun_sign_legacy_payload(
            {
                "message-headers": "[]",
                "attachment-count": "4",
                "content-id-map": '{"": "attachment-1", "": "attachment-2",'
                ' "<abc>": "attachment-3", "<abc>": "attachment-4"}',
                "attachment-1": make_fileobj("att1"),
                "attachment-2": make_fileobj("att2"),
                "attachment-3": make_fileobj("att3"),
                "attachment-4": make_fileobj("att4"),
            }
        )

        response = self.client.post("/anymail/mailgun/inbound/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailgunInboundWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        message = event.message
        self.assertEqual(len(message.attachments), 0)  # all inlines
        inlines = [part for part in message.walk() if part.is_inline_attachment()]
        self.assertEqual(len(inlines), 4)
        self.assertEqual(inlines[0]["Content-ID"], "")
        self.assertEqual(inlines[1]["Content-ID"], "")
        self.assertEqual(inlines[2]["Content-ID"], "<abc>")
        self.assertEqual(inlines[3]["Content-ID"], "<abc>")

    def test_inbound_mime(self):
        # Mailgun provides the full, raw MIME message if the webhook url ends in 'mime'
        raw_event = mailgun_sign_legacy_payload(
            {
                "token": "06c96bafc3f42a66b9edd546347a2fe18dc23461fe80dc52f0",
                "timestamp": "1461261330",
                "recipient": "test@inbound.example.com",
                "sender": "envelope-from@example.org",
                "body-mime": dedent(
                    """\
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
                """  # NOQA: E501
                ),
            }
        )

        response = self.client.post("/anymail/mailgun/inbound_mime/", data=raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailgunInboundWebhookView,
            event=ANY,
            esp_name="Mailgun",
        )
        event = kwargs["event"]
        message = event.message
        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "test@inbound.example.com")
        self.assertEqual(message.subject, "Raw MIME test")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""",
        )

    def test_misconfigured_tracking(self):
        raw_event = mailgun_sign_payload(
            {
                "event-data": {
                    "event": "clicked",
                    "timestamp": 1534109600.089676,
                    "recipient": "recipient@example.com",
                    "url": "https://example.com/test",
                }
            }
        )
        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set Mailgun's *clicked tracking* webhook"
            " to Anymail's Mailgun *inbound* webhook URL.",
        ):
            self.client.post(
                "/anymail/mailgun/inbound/",
                data=json.dumps(raw_event),
                content_type="application/json",
            )

    def test_misconfigured_store_action(self):
        # store() notification includes "attachments" json;
        # forward() includes "attachment-count"
        raw_event = mailgun_sign_legacy_payload(
            {
                "token": "06c96bafc3f42a66b9edd546347a2fe18dc23461fe80dc52f0",
                "timestamp": "1461261330",
                "recipient": "test@inbound.example.com",
                "sender": "envelope-from@example.org",
                "body-plain": "Test body plain",
                "body-html": "<div>Test body html</div>",
                "attachments": json.dumps(
                    [
                        {
                            "url": "https://storage.mailgun.net/v3/domains/example.com"
                            "/messages/MESSAGE_KEY/attachments/0",
                            "content-type": "application/pdf",
                            "name": "attachment.pdf",
                            "size": 20202,
                        }
                    ]
                ),
            }
        )
        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have configured Mailgun's receiving route using the store()"
            " action. Anymail's inbound webhook requires the forward() action.",
        ):
            self.client.post("/anymail/mailgun/inbound/", data=raw_event)

    def test_misconfigured_tracking_legacy(self):
        raw_event = mailgun_sign_legacy_payload(
            {
                "domain": "example.com",
                "message-headers": "[]",
                "recipient": "recipient@example.com",
                "event": "delivered",
            }
        )
        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set Mailgun's *delivered tracking* webhook"
            " to Anymail's Mailgun *inbound* webhook URL.",
        ):
            self.client.post("/anymail/mailgun/inbound/", data=raw_event)
