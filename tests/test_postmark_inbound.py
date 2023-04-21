import json
from base64 import b64encode
from unittest.mock import ANY

from django.test import tag

from anymail.exceptions import AnymailConfigurationError, AnymailWarning
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.postmark import PostmarkInboundWebhookView

from .utils import sample_email_content, sample_image_content
from .webhook_cases import WebhookTestCase


@tag("postmark")
class PostmarkInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
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
                {
                    "Email": "bcc@example.com",
                    "Name": "Postmark documents blind cc on inbound email (?)",
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
                {
                    "Name": "Received",
                    "Value": "from mail.example.org by inbound.postmarkapp.com ...",
                },
                {
                    "Name": "X-Spam-Checker-Version",
                    "Value": "SpamAssassin 3.4.0 (2014-02-07)"
                    " onp-pm-smtp-inbound01b-aws-useast2b",
                },
                {"Name": "X-Spam-Status", "Value": "No"},
                {"Name": "X-Spam-Score", "Value": "1.7"},
                {"Name": "X-Spam-Tests", "Value": "SPF_PASS"},
                {
                    "Name": "Received-SPF",
                    "Value": "Pass (sender SPF authorized) identity=mailfrom;"
                    " client-ip=333.3.3.3;"
                    " helo=mail-02.example.org;"
                    " envelope-from=envelope-from@example.org;"
                    " receiver=test@inbound.example.com",
                },
                {
                    "Name": "Received",
                    "Value": "by mail.example.org for <test@inbound.example.com> ...",
                },
                {
                    "Name": "Received",
                    "Value": "by 10.10.1.71 with HTTP;"
                    " Wed, 11 Oct 2017 18:31:04 -0700 (PDT)",
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
                # This is an attachement like send by the test webhook
                # A workaround is implemented to handle it.
                # Once Postmark solves the bug on their side this workaround
                # can be reverted.
                {
                    "Name": "test.txt",
                    "ContentType": "text/plain",
                    "Data": "VGhpcyBpcyBhdHRhY2htZW50IGNvbnRlbnRzLCBiYXNlLTY0IGVuY29kZWQu",
                    "ContentLength": 45,
                },
            ]
        }

        with self.assertWarnsRegex(
            AnymailWarning, r"Received a test webhook attachment. "
        ):
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
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0].get_filename(), "test.txt")
        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_content_text(), "test attachment")
        self.assertEqual(attachments[1].get_content_type(), "message/rfc822")
        self.assertEqualIgnoringHeaderFolding(
            attachments[1].get_content_bytes(), email_content
        )

        # Attachment of test webhook
        self.assertEqual(attachments[2].get_filename(), "test.txt")
        self.assertEqual(attachments[2].get_content_type(), "text/plain")
        self.assertEqual(
            attachments[2].get_content_text(),
            "This is attachment contents, base-64 encoded.",
        )

        inlines = message.inline_attachments
        self.assertEqual(len(inlines), 1)
        inline = inlines["abc123"]
        self.assertEqual(inline.get_filename(), "image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), image_content)

    def test_envelope_sender(self):
        # Anymail extracts envelope-sender from Postmark Received-SPF header
        raw_event = {
            "Headers": [
                {
                    "Name": "Received-SPF",
                    "Value": "Pass (sender SPF authorized) identity=mailfrom;"
                    " client-ip=333.3.3.3;"
                    " helo=mail-02.example.org;"
                    " envelope-from=envelope-from@example.org;"
                    " receiver=test@inbound.example.com",
                }
            ],
        }
        response = self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(raw_event),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.get_kwargs(self.inbound_handler)["event"].message.envelope_sender,
            "envelope-from@example.org",
        )

        # Allow neutral SPF response
        self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(
                {
                    "Headers": [
                        {
                            "Name": "Received-SPF",
                            "Value": "Neutral (no SPF record exists)"
                            " identity=mailfrom;"
                            " envelope-from=envelope-from@example.org",
                        }
                    ]
                }
            ),
        )
        self.assertEqual(
            self.get_kwargs(self.inbound_handler)["event"].message.envelope_sender,
            "envelope-from@example.org",
        )

        # Ignore fail/softfail
        self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(
                {
                    "Headers": [
                        {
                            "Name": "Received-SPF",
                            "Value": "Fail (sender not SPF authorized)"
                            " identity=mailfrom;"
                            " envelope-from=spoofed@example.org",
                        }
                    ]
                }
            ),
        )
        self.assertIsNone(
            self.get_kwargs(self.inbound_handler)["event"].message.envelope_sender
        )

        # Ignore garbage
        self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(
                {
                    "Headers": [
                        {
                            "Name": "Received-SPF",
                            "Value": "ThisIsNotAValidReceivedSPFHeader@example.org",
                        }
                    ]
                }
            ),
        )
        self.assertIsNone(
            self.get_kwargs(self.inbound_handler)["event"].message.envelope_sender
        )

        # Ignore multiple Received-SPF headers
        self.client.post(
            "/anymail/postmark/inbound/",
            content_type="application/json",
            data=json.dumps(
                {
                    "Headers": [
                        {
                            "Name": "Received-SPF",
                            "Value": "Fail (sender not SPF authorized)"
                            " identity=mailfrom;"
                            " envelope-from=spoofed@example.org",
                        },
                        {
                            "Name": "Received-SPF",
                            "Value": "Pass (malicious sender added this)"
                            " identity=mailfrom;"
                            " envelope-from=spoofed@example.org",
                        },
                    ]
                }
            ),
        )
        self.assertIsNone(
            self.get_kwargs(self.inbound_handler)["event"].message.envelope_sender
        )

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
