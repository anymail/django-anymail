import json
from datetime import date, datetime
from decimal import Decimal

from django.core import mail
from django.test import SimpleTestCase, tag
from django.utils.timezone import (
    get_fixed_timezone,
    override as override_current_timezone,
)

from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import AnymailMessage, attach_inline_image

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import (
    AnymailTestMixin,
    decode_att,
    ignore_fail_silently_warning,
    override_settings,
    sample_image_content,
)


@tag("mailkite")
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.mailkite.EmailBackend",
            "OPTIONS": {"api_key": "test_api_key"},
        },
    },
)
class MailKiteBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    # MailKite's send endpoint returns {"id": ..., "status": ...} (e.g. "queued")
    DEFAULT_RAW_RESPONSE = b'{"id": "msg_test12345", "status": "queued"}'

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("mailkite")
class MailKiteBackendStandardEmailTests(MailKiteBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@sender.example.com",
            ["to@example.com"],
        )
        self.assert_esp_called("/v1/send")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["Authorization"], "Bearer test_api_key")
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["text"], "Here is the message.")
        self.assertEqual(data["from"], "from@sender.example.com")
        self.assertEqual(data["to"], ["to@example.com"])

    def test_name_addr(self):
        """Make sure RFC2822 name-addr format (with display-name) is allowed

        (Test both sender and recipient addresses)
        """
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "From Name <from@example.com>",
            ["Recipient #1 <to1@example.com>", "to2@example.com"],
            cc=["Carbon Copy <cc1@example.com>", "cc2@example.com"],
            bcc=["Blind Copy <bcc1@example.com>", "bcc2@example.com"],
        )
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(data["from"], "From Name <from@example.com>")
        self.assertEqual(
            data["to"], ["Recipient #1 <to1@example.com>", "to2@example.com"]
        )
        self.assertEqual(
            data["cc"], ["Carbon Copy <cc1@example.com>", "cc2@example.com"]
        )
        self.assertEqual(
            data["bcc"], ["Blind Copy <bcc1@example.com>", "bcc2@example.com"]
        )

    def test_email_message(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com", "Also To <to2@example.com>"],
            bcc=["bcc1@example.com", "Also BCC <bcc2@example.com>"],
            cc=["cc1@example.com", "Also CC <cc2@example.com>"],
            reply_to=["another@example.com"],
            headers={
                "X-MyHeader": "my value",
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject")
        self.assertEqual(data["text"], "Body goes here")
        self.assertEqual(data["from"], "from@example.com")
        self.assertEqual(data["to"], ["to1@example.com", "Also To <to2@example.com>"])
        self.assertEqual(
            data["bcc"], ["bcc1@example.com", "Also BCC <bcc2@example.com>"]
        )
        self.assertEqual(data["cc"], ["cc1@example.com", "Also CC <cc2@example.com>"])
        # MailKite's replyTo is a single string (not an array)
        self.assertEqual(data["replyTo"], "another@example.com")
        self.assertCountEqual(
            data["headers"],
            {"X-MyHeader": "my value"},
        )

    def test_html_message(self):
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["text"], text_content)
        self.assertEqual(data["html"], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn("attachments", data)

    def test_html_only_message(self):
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMessage(
            "Subject", html_content, "from@example.com", ["to@example.com"]
        )
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        data = self.get_api_call_json()
        self.assertNotIn("text", data)
        self.assertEqual(data["html"], html_content)

    def test_extra_headers(self):
        self.message.extra_headers = {"X-Custom": "string", "X-Num": 123}
        self.message.send()
        data = self.get_api_call_json()
        # header values must be strings (the ESP requires string-valued headers)
        self.assertEqual(data["headers"], {"X-Custom": "string", "X-Num": "123"})

    def test_reply_to(self):
        # MailKite accepts a single replyTo string; multiple addresses are joined.
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["reply@example.com", "Other <reply2@example.com>"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["replyTo"], "reply@example.com, Other <reply2@example.com>"
        )

    def test_attachments(self):
        # MailKite attachments use {filename, content (base64), contentType}
        # (note: camelCase contentType). There is no content_id / inline field.
        self.message.attach("receipt.pdf", b"%PDF-1.4 fake pdf", "application/pdf")
        self.message.attach("data.csv", b"a,b\n1,2\n", "text/csv")
        self.message.send()
        data = self.get_api_call_json()

        attachments = data["attachments"]
        self.assertEqual(len(attachments), 2)

        self.assertEqual(attachments[0]["filename"], "receipt.pdf")
        self.assertEqual(attachments[0]["contentType"], "application/pdf")
        self.assertEqual(decode_att(attachments[0]["content"]), b"%PDF-1.4 fake pdf")
        self.assertNotIn("content_id", attachments[0])
        # the underscore variant must not leak through:
        self.assertNotIn("content_type", attachments[0])

        self.assertEqual(attachments[1]["filename"], "data.csv")
        self.assertEqual(attachments[1]["contentType"], "text/csv")
        self.assertEqual(decode_att(attachments[1]["content"]), b"a,b\n1,2\n")

    def test_attachment_generated_filename(self):
        # No filename + a known mimetype -> a default name is generated
        self.message.attach(None, "data", "text/plain")
        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], "attachment.txt")
        self.assertEqual(attachments[0]["contentType"], "text/plain")

    def test_missing_attachment_filename_unknown_type(self):
        self.message.attach(None, "data", "text/x-unknown-type")
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "unnamed attachments of type text/x-unknown-type"
        ):
            self.message.send()

    def test_inline_attachment_unsupported(self):
        # The MailKite send API has no Content-ID / inline field.
        attach_inline_image(self.message, sample_image_content(), "test.png")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline attachments"):
            self.message.send()

    def test_multiple_html_alternatives(self):
        # Multiple alternatives not allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>But not second html</p>", "text/html")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple html parts"):
            self.message.send()

    def test_html_alternative(self):
        # Only html alternatives allowed
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    @ignore_fail_silently_warning()
    def test_alternatives_fail_silently(self):
        # Make sure fail_silently is respected
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        sent = self.message.send(fail_silently=True)
        self.assert_esp_not_called("API should not be called when send fails silently")
        self.assertEqual(sent, 0)

    def test_suppress_empty_address_lists(self):
        """Empty to, cc, bcc, and replyTo shouldn't generate empty fields"""
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("cc", data)
        self.assertNotIn("bcc", data)
        self.assertNotIn("replyTo", data)

        # Test empty `to`--but send requires at least one recipient somewhere (like cc)
        self.message.to = []
        self.message.cc = ["cc@example.com"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("to", data)

    def test_api_failure(self):
        failure_response = {
            "statusCode": 400,
            "message": "API key is invalid",
            "name": "validation_error",
        }
        self.set_mock_response(status_code=400, json_data=failure_response)
        with self.assertRaisesMessage(
            AnymailAPIError, r"MailKite API response 400"
        ) as cm:
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])
        self.assertIn("API key is invalid", str(cm.exception))

    @ignore_fail_silently_warning()
    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        failure_response = {
            "statusCode": 400,
            "message": "API key is invalid",
            "name": "validation_error",
        }
        self.set_mock_response(status_code=422, json_data=failure_response)
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            fail_silently=True,
        )
        self.assertEqual(sent, 0)


@tag("mailkite")
class MailKiteBackendAnymailFeatureTests(MailKiteBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "anything@bounces.example.com"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "envelope_sender"):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            json.loads(data["headers"]["X-Metadata"]),
            {"user_id": "12345", "items": 6},
        )

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        with override_current_timezone(utc_plus_6):
            # Timezone-naive datetime assumed to be Django current_timezone
            self.message.send_at = datetime(2022, 10, 11, 12, 13, 14, 123456)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2022-10-11T12:13:14.123+06:00")

            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2016-03-04T05:06:07-08:00")

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2022-10-22T00:00:00+06:00")

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2022-05-06T07:08:09+00:00")

            # String passed unchanged (caller is responsible for formatting)
            self.message.send_at = "2022-10-13T18:02:00Z"
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2022-10-13T18:02:00Z")

    def test_scheduled_response_status(self):
        # A future send_at parks the message; MailKite responds 202 with an
        # ssnd_… id and status "scheduled", which normalizes to "queued".
        self.set_mock_response(
            status_code=202,
            json_data={
                "id": "ssnd_test12345",
                "status": "scheduled",
                "scheduledAt": 1767222896000,
            },
        )
        self.message.send_at = "2026-01-01T00:34:56Z"
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})
        self.assertEqual(self.message.anymail_status.message_id, "ssnd_test12345")
        self.assertEqual(
            self.message.anymail_status.recipients["to@example.com"].status, "queued"
        )

    def test_tags(self):
        self.message.tags = ["receipt", "reorder test 12"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            json.loads(data["headers"]["X-Tags"]),
            ["receipt", "reorder test 12"],
        )

    def test_headers_metadata_tags_interaction(self):
        # Three features that use custom headers must not clobber each other
        self.message.extra_headers = {"X-Custom": "custom value"}
        self.message.metadata = {"user_id": "12345"}
        self.message.tags = ["receipt", "reorder test 12"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["headers"],
            {
                "X-Custom": "custom value",
                "X-Tags": '["receipt", "reorder test 12"]',
                "X-Metadata": '{"user_id": "12345"}',
            },
        )

    def test_template_id(self):
        self.message.template_id = "tpl_welcome"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["templateId"], "tpl_welcome")

    def test_template_with_merge_global_data(self):
        # MailKite renders templates server-side from templateData.
        message = AnymailMessage(
            from_email="from@example.com",
            to=["to@example.com"],
            template_id="tpl_welcome",
            merge_global_data={"name": "Ann", "team": "MailKite"},
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["templateId"], "tpl_welcome")
        self.assertEqual(data["templateData"], {"name": "Ann", "team": "MailKite"})

    def test_merge_global_data_without_template(self):
        # merge_global_data maps to templateData even without a template
        message = AnymailMessage(
            from_email="from@example.com",
            to=["to@example.com"],
            merge_global_data={"name": "Ann"},
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["templateData"], {"name": "Ann"})

    def test_merge_data(self):
        # Setting merge_data switches to the batch endpoint: one personalized
        # message per `to` recipient.
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "alice@example.com", "id": "msg_a", "status": "sent"},
                    {"to": "Bob <bob@example.com>", "id": "msg_b", "status": "sent"},
                ],
                "sent": 2,
                "scheduled": 0,
                "failed": 0,
            }
        )
        message = AnymailMessage(
            subject="Hello {{name}} ({{group}})",
            body="Hi {{name}}",
            from_email="from@example.com",
            to=["alice@example.com", "Bob <bob@example.com>"],
            merge_data={
                "alice@example.com": {"name": "Alice", "group": "Developers"},
                "bob@example.com": {"name": "Bob"},
            },
            merge_global_data={"group": "Users", "site": "ExampleCo"},
        )
        message.send()
        self.assert_esp_called("/v1/send/batch")
        data = self.get_api_call_json()
        self.assertNotIn("to", data)
        # merge_global_data is the shared default; per-recipient wins key-by-key
        self.assertEqual(data["templateData"], {"group": "Users", "site": "ExampleCo"})
        self.assertEqual(
            data["recipients"],
            [
                {
                    "to": "alice@example.com",
                    "templateData": {"name": "Alice", "group": "Developers"},
                },
                {
                    "to": "Bob <bob@example.com>",
                    "templateData": {"name": "Bob"},
                },
            ],
        )
        # Per-recipient message ids from the batch response:
        self.assertEqual(message.anymail_status.status, {"sent"})
        self.assertEqual(
            message.anymail_status.recipients["alice@example.com"].message_id, "msg_a"
        )
        self.assertEqual(
            message.anymail_status.recipients["bob@example.com"].message_id, "msg_b"
        )

    def test_empty_merge_data(self):
        # Empty merge_data still switches to batch mode (one message per
        # recipient), just with no per-recipient substitutions.
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "alice@example.com", "id": "msg_a", "status": "sent"},
                    {"to": "Bob <bob@example.com>", "id": "msg_b", "status": "sent"},
                ],
                "sent": 2,
                "scheduled": 0,
                "failed": 0,
            }
        )
        message = AnymailMessage(
            subject="Subject",
            body="Body",
            from_email="from@example.com",
            to=["alice@example.com", "Bob <bob@example.com>"],
            merge_data={},
        )
        message.send()
        self.assert_esp_called("/v1/send/batch")
        data = self.get_api_call_json()
        self.assertEqual(
            data["recipients"],
            [{"to": "alice@example.com"}, {"to": "Bob <bob@example.com>"}],
        )

    def test_merge_metadata(self):
        # Per-recipient metadata: `metadata` merged with the recipient's
        # merge_metadata entry, carried in a per-recipient X-Metadata header.
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "alice@example.com", "id": "msg_a", "status": "sent"},
                    {"to": "bob@example.com", "id": "msg_b", "status": "sent"},
                ],
                "sent": 2,
                "scheduled": 0,
                "failed": 0,
            }
        )
        message = AnymailMessage(
            subject="Subject",
            body="Body",
            from_email="from@example.com",
            to=["alice@example.com", "bob@example.com"],
            metadata={"kind": "welcome", "batch": 11},
            merge_metadata={
                "alice@example.com": {"user_id": 123},
                "bob@example.com": {"user_id": 456, "kind": "vip-welcome"},
            },
        )
        message.send()
        data = self.get_api_call_json()
        # Shared metadata still travels as the shared X-Metadata header:
        self.assertEqual(
            json.loads(data["headers"]["X-Metadata"]), {"kind": "welcome", "batch": 11}
        )
        # Each recipient's header is metadata updated with their entry:
        self.assertEqual(
            json.loads(data["recipients"][0]["headers"]["X-Metadata"]),
            {"kind": "welcome", "batch": 11, "user_id": 123},
        )
        self.assertEqual(
            json.loads(data["recipients"][1]["headers"]["X-Metadata"]),
            {"kind": "vip-welcome", "batch": 11, "user_id": 456},
        )

    def test_merge_headers(self):
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "alice@example.com", "id": "msg_a", "status": "sent"},
                    {"to": "bob@example.com", "id": "msg_b", "status": "sent"},
                ],
                "sent": 2,
                "scheduled": 0,
                "failed": 0,
            }
        )
        message = AnymailMessage(
            subject="Subject",
            body="Body",
            from_email="from@example.com",
            to=["alice@example.com", "bob@example.com"],
            headers={"List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
            merge_headers={
                "alice@example.com": {
                    "List-Unsubscribe": "<https://example.com/a/>",
                },
                "bob@example.com": {
                    "List-Unsubscribe": "<https://example.com/b/>",
                },
            },
        )
        message.send()
        data = self.get_api_call_json()
        # Shared headers stay shared; per-recipient headers win key-by-key:
        self.assertEqual(
            data["headers"],
            {"List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
        )
        self.assertEqual(
            data["recipients"][0]["headers"],
            {"List-Unsubscribe": "<https://example.com/a/>"},
        )
        self.assertEqual(
            data["recipients"][1]["headers"],
            {"List-Unsubscribe": "<https://example.com/b/>"},
        )

    def test_batch_partial_failure(self):
        # A batch can partially succeed; failed recipients get status "failed"
        # (or "rejected" for suppressed addresses) and no exception is raised.
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "ok@example.com", "id": "msg_ok", "status": "sent"},
                    {
                        "to": "bounced@example.com",
                        "status": "failed",
                        "error": "Suppressed (unsubscribed or bounced)",
                        "code": "recipient_suppressed",
                    },
                    {
                        "to": "broken@example.com",
                        "status": "failed",
                        "error": "send failed",
                        "code": "send_failed",
                    },
                ],
                "sent": 1,
                "scheduled": 0,
                "failed": 2,
            }
        )
        message = AnymailMessage(
            subject="Subject",
            body="Body",
            from_email="from@example.com",
            to=["ok@example.com", "bounced@example.com", "broken@example.com"],
            merge_data={},
        )
        sent = message.send()
        self.assertEqual(sent, 1)  # Anymail counts partial batch success as 1
        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["ok@example.com"].status, "sent")
        self.assertEqual(recipients["ok@example.com"].message_id, "msg_ok")
        self.assertEqual(recipients["bounced@example.com"].status, "rejected")
        self.assertIsNone(recipients["bounced@example.com"].message_id)
        self.assertEqual(recipients["broken@example.com"].status, "failed")
        self.assertEqual(message.anymail_status.status, {"sent", "rejected", "failed"})

    def test_batch_scheduled(self):
        # send_at works with batch: every message is parked (one ssnd_… each),
        # normalized to Anymail's "queued".
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "alice@example.com", "id": "ssnd_a", "status": "scheduled"},
                    {"to": "bob@example.com", "id": "ssnd_b", "status": "scheduled"},
                ],
                "sent": 0,
                "scheduled": 2,
                "failed": 0,
            }
        )
        message = AnymailMessage(
            subject="Subject",
            body="Body",
            from_email="from@example.com",
            to=["alice@example.com", "bob@example.com"],
            merge_data={"alice@example.com": {"name": "Alice"}},
        )
        message.send_at = "2026-10-11T12:13:14Z"
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["scheduledAt"], "2026-10-11T12:13:14Z")
        self.assertEqual(message.anymail_status.status, {"queued"})
        self.assertEqual(
            message.anymail_status.recipients["alice@example.com"].message_id, "ssnd_a"
        )

    def test_batch_cc_bcc_unsupported(self):
        # Batch sends one message per `to` recipient; there is no cc/bcc.
        message = AnymailMessage(
            subject="Subject",
            body="Body",
            from_email="from@example.com",
            to=["alice@example.com"],
            cc=["cc@example.com"],
            merge_data={},
        )
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "cc or bcc with batch send"
        ):
            message.send()

    def test_track_opens(self):
        # Per-send override of the from-domain's open-tracking default
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackOpens"], True)

        self.message.track_opens = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackOpens"], False)

    def test_track_opens_default_omitted(self):
        # Unset track_opens must not send the field (domain default applies)
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("trackOpens", data)

    def test_track_clicks(self):
        # Per-send override of the from-domain's click-tracking default
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackClicks"], True)

        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackClicks"], False)

    def test_track_clicks_default_omitted(self):
        # Unset track_clicks must not send the field (domain default applies)
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("trackClicks", data)

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("headers", data)
        self.assertNotIn("attachments", data)
        self.assertNotIn("templateId", data)
        self.assertNotIn("templateData", data)
        self.assertNotIn("replyTo", data)

    def test_esp_extra(self):
        self.message.esp_extra = {"inReplyTo": "<a1b2@mail.example.com>"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["inReplyTo"], "<a1b2@mail.example.com>")

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["Recipient <to1@example.com>"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(msg.anymail_status.message_id, "msg_test12345")
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "msg_test12345",
        )
        self.assertEqual(
            msg.anymail_status.esp_response.content, self.DEFAULT_RAW_RESPONSE
        )

    def test_response_status_is_passed_through(self):
        # When the ESP returns e.g. "sent", that becomes the recipient status.
        self.set_mock_response(json_data={"id": "msg_abc", "status": "sent"})
        msg = mail.EmailMessage(
            "Subject", "Message", "from@example.com", ["to@example.com"]
        )
        msg.send()
        self.assertEqual(msg.anymail_status.status, {"sent"})
        self.assertEqual(msg.anymail_status.message_id, "msg_abc")
        self.assertEqual(msg.anymail_status.recipients["to@example.com"].status, "sent")

    # noinspection PyUnresolvedReferences
    @ignore_fail_silently_warning()
    def test_send_failed_anymail_status(self):
        """If the send fails, anymail_status should contain initial values"""
        self.set_mock_response(status_code=500)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertIsNone(self.message.anymail_status.esp_response)

    # noinspection PyUnresolvedReferences
    def test_send_unparsable_response(self):
        """
        If the send succeeds, but a non-JSON API response, should raise an API exception
        """
        mock_response = self.set_mock_response(
            status_code=200, raw=b"yikes, this isn't a real response"
        )
        with self.assertRaises(AnymailAPIError):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(self.message.anymail_status.esp_response, mock_response)

    def test_json_serialization_errors(self):
        """Try to provide more information about non-json-serializable data"""
        self.message.metadata = {"price": Decimal("19.99")}  # yeah, don't do this
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to MailKite", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("mailkite")
class MailKiteBackendRecipientsRefusedTests(MailKiteBackendMockAPITestCase):
    # MailKite doesn't check suppression/bounce lists at time of send -- it always
    # just queues the message. Listen for delivery-status events to detect
    # refused recipients.
    pass


@tag("mailkite")
class MailKiteBackendSessionSharingTestCase(
    SessionSharingTestCases, MailKiteBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mailkite")
@override_settings(
    MAILERS={"default": {"BACKEND": "anymail.backends.mailkite.EmailBackend"}},
)
class MailKiteBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaisesRegex(
            AnymailConfigurationError,
            r"'api_key'|\bMAILKITE_API_KEY.*ANYMAIL_MAILKITE_API_KEY",
        ):
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
