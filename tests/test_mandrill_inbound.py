from textwrap import dedent
from unittest.mock import ANY

from django.test import override_settings, tag

from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mandrill import MandrillCombinedWebhookView

from .test_mandrill_webhooks import TEST_WEBHOOK_KEY, mandrill_args
from .webhook_cases import WebhookTestCase


@tag('mandrill')
@override_settings(ANYMAIL_MANDRILL_WEBHOOK_KEY=TEST_WEBHOOK_KEY)
class MandrillInboundTestCase(WebhookTestCase):
    def test_inbound_basics(self):
        raw_event = {
            "event": "inbound",
            "ts": 1507856722,
            "msg": {
                "raw_msg": dedent("""\
                    From: A tester <test@example.org>
                    Date: Thu, 12 Oct 2017 18:03:30 -0700
                    Message-ID: <CAEPk3RKEx@mail.example.org>
                    Subject: Test subject
                    To: "Test, Inbound" <test@inbound.example.com>, other@example.com
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
                "email": "delivered-to@example.com",
                "sender": None,  # Mandrill populates "sender" only for outbound message events
                "spam_report": {
                    "score": 1.7,
                },
                # Anymail ignores Mandrill's other inbound event fields
                # (which are all redundant with raw_msg)
            },
        }

        response = self.client.post(**mandrill_args(events=[raw_event], path='/anymail/mandrill/'))
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.inbound_handler, sender=MandrillCombinedWebhookView,
                                                      event=ANY, esp_name='Mandrill')
        self.assertEqual(self.tracking_handler.call_count, 0)  # Inbound should not dispatch tracking signal

        event = kwargs['event']
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(event.timestamp.isoformat(), "2017-10-13T01:05:22+00:00")
        self.assertIsNone(event.event_id)  # Mandrill doesn't provide inbound event id
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_event)

        message = event.message
        self.assertEqual(message.from_email.display_name, 'A tester')
        self.assertEqual(message.from_email.addr_spec, 'test@example.org')
        self.assertEqual(len(message.to), 2)
        self.assertEqual(message.to[0].display_name, 'Test, Inbound')
        self.assertEqual(message.to[0].addr_spec, 'test@inbound.example.com')
        self.assertEqual(message.to[1].addr_spec, 'other@example.com')
        self.assertEqual(message.subject, 'Test subject')
        self.assertEqual(message.date.isoformat(" "), "2017-10-12 18:03:30-07:00")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(message.html, """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""")

        self.assertIsNone(message.envelope_sender)  # Mandrill doesn't provide sender
        self.assertEqual(message.envelope_recipient, 'delivered-to@example.com')
        self.assertIsNone(message.stripped_text)  # Mandrill doesn't provide stripped plaintext body
        self.assertIsNone(message.stripped_html)  # Mandrill doesn't provide stripped html
        self.assertIsNone(message.spam_detected)  # Mandrill doesn't provide spam boolean
        self.assertEqual(message.spam_score, 1.7)

        # Anymail will also parse attachments (if any) from the raw mime.
        # We don't bother testing that here; see test_inbound for examples.
