import json
from datetime import datetime, timezone
from textwrap import dedent
from unittest.mock import ANY

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings, tag

from anymail.exceptions import AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.mailersend import MailerSendInboundWebhookView

from .test_mailersend_webhooks import (
    TEST_WEBHOOK_SIGNING_SECRET,
    MailerSendWebhookTestCase,
)
from .utils import sample_image_content
from .webhook_cases import WebhookBasicAuthTestCase


@tag("mailersend")
@override_settings(ANYMAIL_MAILERSEND_INBOUND_SECRET=TEST_WEBHOOK_SIGNING_SECRET)
class MailerSendInboundSecurityTestCase(
    MailerSendWebhookTestCase, WebhookBasicAuthTestCase
):
    should_warn_if_no_auth = False  # because we check webhook signature

    def call_webhook(self):
        return self.client_post_signed(
            "/anymail/mailersend/inbound/",
            {"type": "inbound.message", "data": {"raw": "..."}},
            secret=TEST_WEBHOOK_SIGNING_SECRET,
        )

    # Additional tests are in WebhookBasicAuthTestCase

    def test_verifies_correct_signature(self):
        response = self.client_post_signed(
            "/anymail/mailersend/inbound/",
            {"type": "inbound.message", "data": {"raw": "..."}},
            secret=TEST_WEBHOOK_SIGNING_SECRET,
        )
        self.assertEqual(response.status_code, 200)

    def test_verifies_missing_signature(self):
        response = self.client.post(
            "/anymail/mailersend/inbound/",
            content_type="application/json",
            data=json.dumps({"type": "inbound.message", "data": {"raw": "..."}}),
        )
        self.assertEqual(response.status_code, 400)

    def test_verifies_bad_signature(self):
        # This also verifies that the error log references the correct setting to check.
        with self.assertLogs() as logs:
            response = self.client_post_signed(
                "/anymail/mailersend/inbound/",
                {"type": "inbound.message", "data": {"raw": "..."}},
                secret="wrong signing key",
            )
        # SuspiciousOperation causes 400 response (even in test client):
        self.assertEqual(response.status_code, 400)
        self.assertIn("check Anymail MAILERSEND_INBOUND_SECRET", logs.output[0])


@tag("mailersend")
class MailerSendInboundSettingsTestCase(MailerSendWebhookTestCase):
    def test_requires_inbound_secret(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "MAILERSEND_INBOUND_SECRET"
        ):
            self.client_post_signed(
                "/anymail/mailersend/inbound/",
                {
                    "type": "inbound.message",
                    "data": {"object": "message", "raw": "..."},
                },
            )

    @override_settings(
        ANYMAIL={
            "MAILERSEND_INBOUND_SECRET": "inbound secret",
            "MAILERSEND_WEBHOOK_SIGNING_SECRET": "webhook secret",
        }
    )
    def test_webhook_signing_secret_is_different(self):
        response = self.client_post_signed(
            "/anymail/mailersend/inbound/",
            {
                "type": "inbound.message",
                "data": {"object": "message", "raw": "..."},
            },
            secret="inbound secret",
        )
        self.assertEqual(response.status_code, 200)

    @override_settings(ANYMAIL_MAILERSEND_INBOUND_SECRET="settings secret")
    def test_inbound_secret_view_params(self):
        """Webhook signing secret can be provided as a view param"""
        view = MailerSendInboundWebhookView.as_view(inbound_secret="view-level secret")
        view_instance = view.view_class(**view.view_initkwargs)
        self.assertEqual(view_instance.signing_secret, b"view-level secret")


@tag("mailersend")
@override_settings(ANYMAIL_MAILERSEND_INBOUND_SECRET=TEST_WEBHOOK_SIGNING_SECRET)
class MailerSendInboundTestCase(MailerSendWebhookTestCase):
    # Since Anymail just parses the raw MIME message through the Python email
    # package, there aren't really a lot of different cases to test here.
    # (We don't need to re-test the whole email.parser.)

    def test_inbound(self):
        # This is an actual (sanitized) inbound payload received from MailerSend:
        raw_event = {
            "type": "inbound.message",
            "inbound_id": "[inbound-route-id-redacted]",
            "url": "https://test.anymail.dev/anymail/mailersend/inbound/",
            "created_at": "2023-03-04T02:22:16.417935Z",
            "data": {
                "object": "message",
                "id": "6402ab57f79d39d7e10f2523",
                "recipients": {
                    "rcptTo": [{"email": "envelope-recipient@example.com"}],
                    "to": {
                        "raw": "Recipient <to@example.com>",
                        "data": [{"email": "to@example.com", "name": "Recipient"}],
                    },
                },
                "from": {
                    "email": "sender@example.org",
                    "name": "Sender Name",
                    "raw": "Sender Name <sender@example.org>",
                },
                "sender": {"email": "envelope-sender@example.org"},
                "subject": "Testing inbound \ud83c\udf0e",
                "date": "Fri, 3 Mar 2023 18:22:03 -0800",
                "headers": {
                    "X-Envelope-From": "<envelope-sender@example.org>",
                    # Multiple-instance headers appear as arrays:
                    "Received": [
                        "from example.org (mail.example.org [10.10.10.10])\r\n"
                        " by inbound.mailersend.net with ESMTPS id ...\r\n"
                        " Sat, 04 Mar 2023 02:22:15 +0000 (UTC)",
                        "by mail.example.org with SMTP id ...\r\n"
                        " for <envelope-recipient@example.com>;\r\n"
                        " Fri, 03 Mar 2023 18:22:15 -0800 (PST)",
                    ],
                    "DKIM-Signature": "v=1; a=rsa-sha256; c=relaxed/relaxed; ...",
                    "MIME-Version": "1.0",
                    "From": "Sender Name <sender@example.org>",
                    "Date": "Fri, 3 Mar 2023 18:22:03 -0800",
                    "Message-ID": "<AzjSdSHsmvXUeZGTPQ@mail.example.org>",
                    "Subject": "=?UTF-8?Q?Testing_inbound_=F0=9F=8C=8E?=",
                    "To": "Recipient <to@example.com>",
                    "Content-Type": 'multipart/mixed; boundary="000000000000e5575c05f609bab6"',
                },
                "text": "This is a *test*!\r\n\r\n[image: sample_image.png]\r\n",
                "html": (
                    "<p>This is a <b>test</b>!</p>"
                    '<img src="cid:ii_letc8ro50" alt="sample_image.png">'
                ),
                "raw": dedent(
                    """\
                    X-Envelope-From: <envelope-sender@example.org>
                    Received: from example.org (mail.example.org [10.10.10.10])
                     by inbound.mailersend.net with ESMTPS id ...
                     Sat, 04 Mar 2023 02:22:15 +0000 (UTC)
                    Received: by mail.example.org with SMTP id ...
                     for <envelope-recipient@example.com>;
                     Fri, 03 Mar 2023 18:22:15 -0800 (PST)
                    DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; ...
                    MIME-Version: 1.0
                    From: Sender Name <sender@example.org>
                    Date: Fri, 3 Mar 2023 18:22:03 -0800
                    Message-ID: <AzjSdSHsmvXUeZGTPQ@mail.example.org>
                    Subject: =?UTF-8?Q?Testing_inbound_=F0=9F=8C=8E?=
                    To: Recipient <to@example.com>
                    Content-Type: multipart/mixed; boundary="000000000000e5575c05f609bab6"

                    --000000000000e5575c05f609bab6
                    Content-Type: multipart/related; boundary="000000000000e5575b05f609bab5"

                    --000000000000e5575b05f609bab5
                    Content-Type: multipart/alternative; boundary="000000000000e5575a05f609bab4"

                    --000000000000e5575a05f609bab4
                    Content-Type: text/plain; charset="UTF-8"

                    This is a *test*!

                    [image: sample_image.png]

                    --000000000000e5575a05f609bab4
                    Content-Type: text/html; charset="UTF-8"

                    <p>This is a <b>test</b>!</p>
                    <img src="cid:ii_letc8ro50" alt="sample_image.png">

                    --000000000000e5575a05f609bab4--
                    --000000000000e5575b05f609bab5
                    Content-Type: image/png; name="sample_image.png"
                    Content-Disposition: inline; filename="sample_image.png"
                    Content-Transfer-Encoding: base64
                    Content-ID: <ii_letc8ro50>

                    iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlz
                    AAALEgAACxIB0t1+/AAAABR0RVh0Q3JlYXRpb24gVGltZQAzLzEvMTNoZNRjAAAAHHRFWHRTb2Z0
                    d2FyZQBBZG9iZSBGaXJld29ya3MgQ1M1cbXjNgAAAZ1JREFUWIXtl7FKA0EQhr+TgIFgo5BXyBUp
                    fIGksLawUNAXWFFfwCJgBAtfIJFMLXgQn8BSwdpCiPcKAdOIoI2x2Dmyd7kYwXhp9odluX/uZv6d
                    nZu7DXowxiKZi0IAUHKCvxcsoAIEpST4IawVGb0Hb0BlpcigefACvAAvwAsoTTGGlwwzBAyivLUP
                    EZrOM10AhGOH2wWugVVlHoAdhJHrPC8DNR0JGsAAQ9mxNzBOMNjS4Qrq69U5EKmf12ywWVsQI4QI
                    IbCn3Gnmnk7uk1bokfooI7QRDlQIGCdzPwiYh0idtXNs2zq3UqwVEiDcu/R0DVjUnFpItuPSscfA
                    FXCGSfEAdZ2fVeQ68OjYWwi3ycVvMhABGwgfKXZScHeZ+4c6VzN8FbuYukvOykCs+z8PJ0xqIXYE
                    d4ALoKlVH2IIgUHWwd/6gNAFPjPcCPvKNTDcYAj1lXzKc7GIRrSZI6yJzcQ+dtV9bD+IkHThBj34
                    4j9/yYxupaQbXPJLNqsGFgeZ6qwpLP1b4AV4AV5AoKfjpR5OwR6VKwULCAC+AQV4W9Ps4uZQAAAA
                    AElFTkSuQmCC
                    --000000000000e5575b05f609bab5--
                    --000000000000e5575c05f609bab6
                    Content-Type: text/csv; charset="US-ASCII"; name="sample_data.csv"
                    Content-Disposition: attachment; filename="sample_data.csv"
                    Content-Transfer-Encoding: quoted-printable

                    Product,Price
                    Widget,33.20
                    --000000000000e5575c05f609bab6--"""
                ).replace("\n", "\r\n"),
                "attachments": [
                    {
                        "file_name": "sample_image.png",
                        "content_type": "image/png",
                        "content_disposition": "inline",
                        "content_id": "ii_letc8ro50",
                        "size": 579,
                        "content": (
                            "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhki"
                            "AAAAAlwSFlzAAALEgAACxIB0t1+/AAAABR0RVh0Q3JlYXRpb24gVGltZQAzLzEvMT"
                            "NoZNRjAAAAHHRFWHRTb2Z0d2FyZQBBZG9iZSBGaXJld29ya3MgQ1M1cbXjNgAAAZ1"
                            "JREFUWIXtl7FKA0EQhr+TgIFgo5BXyBUpfIGksLawUNAXWFFfwCJgBAtfIJFMLXgQ"
                            "n8BSwdpCiPcKAdOIoI2x2Dmyd7kYwXhp9odluX/uZv6dnZu7DXowxiKZi0IAUHKCv"
                            "xcsoAIEpST4IawVGb0Hb0BlpcigefACvAAvwAsoTTGGlwwzBAyivLUPEZrOM10AhG"
                            "OH2wWugVVlHoAdhJHrPC8DNR0JGsAAQ9mxNzBOMNjS4Qrq69U5EKmf12ywWVsQI4Q"
                            "IIbCn3Gnmnk7uk1bokfooI7QRDlQIGCdzPwiYh0idtXNs2zq3UqwVEiDcu/R0DVjU"
                            "nFpItuPSscfAFXCGSfEAdZ2fVeQ68OjYWwi3ycVvMhABGwgfKXZScHeZ+4c6VzN8F"
                            "buYukvOykCs+z8PJ0xqIXYEd4ALoKlVH2IIgUHWwd/6gNAFPjPcCPvKNTDcYAj1lX"
                            "zKc7GIRrSZI6yJzcQ+dtV9bD+IkHThBj344j9/yYxupaQbXPJLNqsGFgeZ6qwpLP1"
                            "b4AV4AV5AoKfjpR5OwR6VKwULCAC+AQV4W9Ps4uZQAAAAAElFTkSuQmCC"
                        ),
                    },
                    {
                        "file_name": "sample_data.csv",
                        "content_type": "text/csv",
                        "content_disposition": "attachment",
                        "size": 26,
                        "content": "UHJvZHVjdCxQcmljZQpXaWRnZXQsMzMuMjA=",
                    },
                ],
                "spf_check": {"code": "+", "value": None},
                "dkim_check": False,
                "created_at": "2023-03-04T02:22:15.525000Z",
            },
        }
        response = self.client_post_signed("/anymail/mailersend/inbound/", raw_event)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=MailerSendInboundWebhookView,
            event=ANY,
            esp_name="MailerSend",
        )
        # AnymailInboundEvent
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            # "2023-03-04T02:22:15.525000Z"
            datetime(2023, 3, 4, 2, 22, 15, microsecond=525000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.event_id, "6402ab57f79d39d7e10f2523")
        self.assertIsInstance(event.message, AnymailInboundMessage)

        # (The raw_event subject contains a "\N{EARTH GLOBE AMERICAS}" (🌎)
        # character in the escaped form "\ud83c\udf0e", which won't compare equal
        # until unescaped. Passing through json dumps/loads resolves the escapes.)
        self.assertEqual(event.esp_event, json.loads(json.dumps(raw_event)))

        # AnymailInboundMessage - convenience properties
        message = event.message

        self.assertEqual(message.from_email.display_name, "Sender Name")
        self.assertEqual(message.from_email.addr_spec, "sender@example.org")
        self.assertEqual(str(message.to[0]), "Recipient <to@example.com>")
        self.assertEqual(message.subject, "Testing inbound 🌎")
        self.assertEqual(message.date.isoformat(" "), "2023-03-03 18:22:03-08:00")
        self.assertEqual(
            message.text, "This is a *test*!\r\n\r\n[image: sample_image.png]\r\n"
        )
        self.assertHTMLEqual(
            message.html,
            "<p>This is a <b>test</b>!</p>"
            '<img src="cid:ii_letc8ro50" alt="sample_image.png">',
        )

        self.assertEqual(message.envelope_sender, "envelope-sender@example.org")
        self.assertEqual(message.envelope_recipient, "envelope-recipient@example.com")

        # MailerSend inbound doesn't provide these:
        self.assertIsNone(message.stripped_text)
        self.assertIsNone(message.stripped_html)
        self.assertIsNone(message.spam_detected)
        self.assertIsNone(message.spam_score)

        # AnymailInboundMessage - other headers
        self.assertEqual(message["Message-ID"], "<AzjSdSHsmvXUeZGTPQ@mail.example.org>")
        self.assertEqual(
            message.get_all("Received"),
            [
                "from example.org (mail.example.org [10.10.10.10]) by inbound.mailersend.net"
                " with ESMTPS id ... Sat, 04 Mar 2023 02:22:15 +0000 (UTC)",
                "by mail.example.org with SMTP id ... for <envelope-recipient@example.com>;"
                " Fri, 03 Mar 2023 18:22:15 -0800 (PST)",
            ],
        )

        inlines = message.content_id_map
        self.assertEqual(len(inlines), 1)
        inline = inlines["ii_letc8ro50"]
        self.assertEqual(inline.get_filename(), "sample_image.png")
        self.assertEqual(inline.get_content_type(), "image/png")
        self.assertEqual(inline.get_content_bytes(), sample_image_content())

        attachments = message.attachments
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].get_filename(), "sample_data.csv")
        self.assertEqual(attachments[0].get_content_type(), "text/csv")
        self.assertEqual(
            attachments[0].get_content_text(), "Product,Price\r\nWidget,33.20"
        )

    def test_misconfigured_inbound(self):
        errmsg = (
            "You seem to have set MailerSend's *activity.sent* webhook"
            " to Anymail's MailerSend *inbound* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client_post_signed(
                "/anymail/mailersend/inbound/",
                {
                    "type": "activity.sent",
                    "data": {"object": "activity", "type": "sent"},
                },
            )
