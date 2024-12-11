import json
from base64 import b64encode
from textwrap import dedent
from unittest.mock import ANY

from django.test import tag

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.postmark import PostmarkInboundWebhookView

from .utils import sample_email_content, sample_image_content, test_file_content
from .webhook_cases import WebhookTestCase


@tag("postmark")
class PostmarkInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        # without "Include raw email content in JSON payload"
        raw_event = {
            "FromFull": {
                "Email": "from+test@example.org",
                "Name": "Displayed From",
                "MailboxHash": "test",
            },
            "ToFull": [
                {
                    "Email": "test@inbound.example.com",
                    "Name": "Test Inbound",
                    "MailboxHash": "",
                },
                {"Email": "other@example.com", "Name": "", "MailboxHash": ""},
            ],
            "CcFull": [{"Email": "cc@example.com", "Name": "", "MailboxHash": ""}],
            "BccFull": [
                # Postmark provides Bcc if delivered-to address is not in To field:
                {
                    "Email": "test@inbound.example.com",
                    "Name": "",
                    "MailboxHash": "",
                }
            ],
            "OriginalRecipient": "test@inbound.example.com",
            "ReplyTo": "from+test@milter.example.org",
            "Subject": "Test subject",
            "MessageID": "22c74902-a0c1-4511-804f2-341342852c90",
            "Date": "Wed, 11 Oct 2017 18:31:04 -0700",
            "TextBody": "Test body plain",
            "HtmlBody": "<div>Test body html</div>",
            "StrippedTextReply": "stripped plaintext body",
            "Tag": "",
            "Headers": [
                {"Name": "Return-Path", "Value": "<envelope-from@example.org>"},
                {
                    "Name": "Received",
                    "Value": "from mail.example.org by inbound.postmarkapp.com ...",
                },
                {
                    "Name": "X-Spam-Checker-Version",
                    "Value": "SpamAssassin 3.4.0 (2014-02-07) on p-pm-smtp-inbound01b-aws-useast2b",  # NOQA: E501
                },
                {"Name": "X-Spam-Status", "Value": "No"},
                {"Name": "X-Spam-Score", "Value": "1.7"},
                {"Name": "X-Spam-Tests", "Value": "SPF_PASS"},
                {
                    "Name": "Received",
                    "Value": "by mail.example.org for <test@inbound.example.com> ...",
                },
                {
                    "Name": "Received",
                    "Value": "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
                },
                {
                    "Name": "Return-Path",
                    "Value": "<fake-return-path@postmark-should-have-removed>",
                },
                {"Name": "MIME-Version", "Value": "1.0"},
                {"Name": "Message-ID", "Value": "<CAEPk3R+4Zr@mail.example.org>"},
            ],
        }

        response = self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=PostmarkInboundWebhookView,
            event=ANY,
            esp_name="Postmark",
        )
        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        # Postmark doesn't provide inbound event timestamp:
        self.assertIsNone(event.timestamp)
        self.assertEqual(event.event_id, "22c74902-a0c1-4511-804f2-341342852c90")
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
        self.assertEqual([str(e) for e in message.bcc], ["test@inbound.example.com"])
        self.assertEqual(message.subject, "Test subject")
        self.assertEqual(message.date.isoformat(" "), "2017-10-11 18:31:04-07:00")
        self.assertEqual(message.text, "Test body plain")
        self.assertEqual(message.html, "<div>Test body html</div>")

        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "test@inbound.example.com")
        self.assertEqual(message.stripped_text, "stripped plaintext body")
        # Postmark doesn't provide stripped html:
        self.assertIsNone(message.stripped_html)
        self.assertIs(message.spam_detected, False)
        self.assertEqual(message.spam_score, 1.7)

        # AnymailInboundMessage - other headers
        self.assertEqual(message["Message-ID"], "<CAEPk3R+4Zr@mail.example.org>")
        self.assertEqual(message["Reply-To"], "from+test@milter.example.org")
        self.assertEqual(
            message.get_all("Received"),
            [
                "from mail.example.org by inbound.postmarkapp.com ...",
                "by mail.example.org for <test@inbound.example.com> ...",
                "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
            ],
        )

    def test_attachments(self):
        image_content = sample_image_content()
        email_content = sample_email_content()
        raw_event = {
            "Attachments": [
                {
                    "Name": "test.txt",
                    "Content": b64encode("test attachment".encode("utf-8")).decode(
                        "ascii"
                    ),
                    "ContentType": "text/plain",
                    "ContentLength": len("test attachment"),
                },
                {
                    "Name": "image.png",
                    "Content": b64encode(image_content).decode("ascii"),
                    "ContentType": "image/png",
                    "ContentID": "abc123",
                    "ContentLength": len(image_content),
                },
                {
                    "Name": "bounce.txt",
                    "Content": b64encode(email_content).decode("ascii"),
                    "ContentType": 'message/rfc822; charset="us-ascii"',
                    "ContentLength": len(email_content),
                },
            ]
        }

        response = self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=PostmarkInboundWebhookView,
            event=ANY,
            esp_name="Postmark",
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

        inlines = message.content_id_map
        self.assertEqual(len(inlines), 1)
        inline = inlines["abc123"]
        self.assertEqual(inline.get_filename(), "image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), image_content)

    def test_inbound_with_raw_email(self):
        # With "Include raw email content in JSON payload"
        raw_event = {
            # (Postmark's "RawEmail" actually uses \n rather than \r\n)
            "RawEmail": dedent(
                """\
                Received: from mail.example.org by inbound.postmarkapp.com ...
                X-Spam-Checker-Version: SpamAssassin 3.4.0 (2014-02-07)
                \ton p-pm-smtp-inbound01b-aws-useast2b
                X-Spam-Status: No
                X-Spam-Score: 1.7
                X-Spam-Tests: SPF_PASS
                Received: by mail.example.org for <test@inbound.example.com> ...
                Received: by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)
                MIME-Version: 1.0
                Message-ID: <CAEPk3R+4Zr@mail.example.org>
                Return-Path: <fake-return-path@postmark-should-have-removed>
                From: "Displayed From" <from+test@example.org>
                To: Test Inbound <test@inbound.example.com>, other@example.com
                Cc: cc@example.com
                Reply-To: from+test@milter.example.org
                Subject: Test subject
                Date: Wed, 11 Oct 2017 18:31:04 -0700
                Content-Type: multipart/alternative; boundary="BoUnDaRy1"

                --BoUnDaRy1
                Content-Type: text/plain; charset="utf-8"
                Content-Transfer-Encoding: 7bit

                Test body plain
                --BoUnDaRy1
                Content-Type: multipart/related; boundary="bOuNdArY2"

                --bOuNdArY2
                Content-Type: text/html; charset="utf-8"
                Content-Transfer-Encoding: quoted-printable

                <div>Test body html</div>
                --bOuNdArY2
                Content-Type: text/plain
                Content-Transfer-Encoding: quoted-printable
                Content-Disposition: attachment; filename="attachment.txt"

                This is an attachment
                --bOuNdArY2--

                --BoUnDaRy1--
                """
            ),
            "BccFull": [
                # Postmark provides Bcc if delivered-to address is not in To field
                # (but not in RawEmail)
                {
                    "Email": "test@inbound.example.com",
                    "Name": "",
                    "MailboxHash": "",
                }
            ],
            "OriginalRecipient": "test@inbound.example.com",
            "MessageID": "22c74902-a0c1-4511-804f2-341342852c90",
            "StrippedTextReply": "stripped plaintext body",
            "Tag": "",
            "Headers": [
                {"Name": "Return-Path", "Value": "<envelope-from@example.org>"},
                # ... All the other headers would be here ...
                # This is a fake header (not in RawEmail) to make sure we only
                # add headers in one place:
                {
                    "Name": "X-No-Duplicates",
                    "Value": "headers only from RawEmail",
                },
            ],
            "Attachments": [
                # ... Real attachments would appear here. ...
                # This is a fake one (not in RawEmail) to make sure we only
                # add attachments in one place:
                {
                    "Name": "no-duplicates.txt",
                    "Content": b64encode("fake attachment".encode("utf-8")).decode(
                        "ascii"
                    ),
                    "ContentType": "text/plain",
                    "ContentLength": len("fake attachment"),
                },
            ],
        }

        response = self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=PostmarkInboundWebhookView,
            event=ANY,
            esp_name="Postmark",
        )
        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        # Postmark doesn't provide inbound event timestamp:
        self.assertIsNone(event.timestamp)
        self.assertEqual(event.event_id, "22c74902-a0c1-4511-804f2-341342852c90")
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
        self.assertEqual([str(e) for e in message.bcc], ["test@inbound.example.com"])
        self.assertEqual(message.subject, "Test subject")
        self.assertEqual(message.date.isoformat(" "), "2017-10-11 18:31:04-07:00")
        self.assertEqual(message.text, "Test body plain")
        self.assertEqual(message.html, "<div>Test body html</div>")

        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "test@inbound.example.com")
        self.assertEqual(message.stripped_text, "stripped plaintext body")
        # Postmark doesn't provide stripped html:
        self.assertIsNone(message.stripped_html)
        self.assertIs(message.spam_detected, False)
        self.assertEqual(message.spam_score, 1.7)

        # AnymailInboundMessage - other headers
        self.assertEqual(message["Message-ID"], "<CAEPk3R+4Zr@mail.example.org>")
        self.assertEqual(message["Reply-To"], "from+test@milter.example.org")
        self.assertEqual(
            message.get_all("Received"),
            [
                "from mail.example.org by inbound.postmarkapp.com ...",
                "by mail.example.org for <test@inbound.example.com> ...",
                "by 10.10.1.71 with HTTP; Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
            ],
        )

        # Attachments (from RawEmail only, not also from parsed):
        attachments = message.attachments
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "attachment.txt")
        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_content_text(), "This is an attachment")

        # Make sure we didn't load headers from both RawEmail and parsed:
        self.assertNotIn("X-No-Duplicates", message)

    def test_misconfigured_tracking(self):
        errmsg = (
            "You seem to have set Postmark's *Delivery* webhook"
            " to Anymail's Postmark *inbound* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client.post(
                "/anymail/postmark/inbound/",
                content_type="application/json",
                data=json.dumps({"RecordType": "Delivery"}),
            )

    def test_check_payload(self):
        # Postmark's "Check" button in the inbound webhook dashboard posts a static
        # payload that doesn't match their docs or actual inbound message payloads.
        # (Its attachments have "Data" rather than "Content".)
        # They apparently have no plans to fix it, so make sure Anymail can handle it.
        for filename in [
            # Actual test payloads from 2023-05-05:
            "postmark-inbound-test-payload.json",
            "postmark-inbound-test-payload-with-raw.json",
        ]:
            with self.subTest(filename=filename):
                self.inbound_handler.reset_mock()  # (subTest doesn't setUp/tearDown)
                test_payload = test_file_content(filename)
                response = self.client.post(
                    "/anymail/postmark/inbound/",
                    content_type="application/json",
                    data=test_payload,
                )
                self.assertEqual(response.status_code, 200)
                self.assert_handler_called_once_with(
                    self.inbound_handler,
                    sender=PostmarkInboundWebhookView,
                    event=ANY,
                    esp_name="Postmark",
                )
                # Don't care about the actual test message contents here,
                # just want to make sure it parses and signals inbound without error.

    def test_spammy_address(self):
        # This long FromFull.Name caused an error in AnymailInboundMessage construction,
        # due to folding introduced in EmailAddress.formataddr()
        from_name = (
            "* * * 💲 Snag Your Free Gift! Click Here: "
            "https://spam.example.com/uploads/phish.php?123456 💲 * * *"
        )
        raw_event = {
            "MessageStream": "inbound",
            "FromFull": {
                "Email": "noreply@spam.example.com",
                "Name": from_name,
            },
        }
        response = self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=PostmarkInboundWebhookView,
            event=ANY,
            esp_name="Postmark",
        )
        message = kwargs["event"].message
        self.assertEqual(message.from_email.display_name, from_name)
