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
    create_text_attachment,
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
    DEFAULT_RAW_RESPONSE = b'{"id": "msg_aaaaaaaaaaaaaaaaaaaa", "status": "sent"}'

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
        """Make sure RFC2822 name-addr format (with display-name) is allowed"""
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
        # MailKite takes a single replyTo string:
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
        # header values must be strings (MailKite requires string header values)
        self.assertEqual(data["headers"], {"X-Custom": "string", "X-Num": "123"})

    def test_extra_headers_serialization_error(self):
        self.message.extra_headers = {"X-Custom": Decimal(12.5)}
        with self.assertRaisesMessage(AnymailSerializationError, "Decimal"):
            self.message.send()

    def test_reply_to(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["reply@example.com"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["replyTo"], "reply@example.com")

    def test_multiple_reply_to_unsupported(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["reply@example.com", "Other <reply2@example.com>"],
        )
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple reply_to"):
            email.send()

    def test_non_ascii_headers(self):
        # MailKite correctly encodes non-ASCII display-names and other headers
        # (but requires IDNA encoding for non-ASCII domain names).
        email = mail.EmailMessage(
            from_email='"Odesílatel, z adresy" <from@příklad.example.cz>',
            to=['"Příjemce, na adresu" <to@příklad.example.cz>'],
            subject="Předmět e-mailu",
            reply_to=['"Odpověď, adresa" <reply@příklad.example.cz>'],
            headers={"X-Extra": "Další"},
            body="Prostý text",
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["from"], '"Odesílatel, z adresy" <from@xn--pklad-zsa96e.example.cz>'
        )
        self.assertEqual(
            data["to"], ['"Příjemce, na adresu" <to@xn--pklad-zsa96e.example.cz>']
        )
        self.assertEqual(data["subject"], "Předmět e-mailu")
        self.assertEqual(
            data["replyTo"], '"Odpověď, adresa" <reply@xn--pklad-zsa96e.example.cz>'
        )
        self.assertEqual(data["headers"], {"X-Extra": "Další"})

    def test_attachments(self):
        text_content = "pièce jointe\n"
        self.message.attach(
            create_text_attachment("pièce jointe\n", charset="iso-8859-1")
        )
        self.message.attach("émoticône.img", b";-)", "image/x-emoticon")
        self.message.send()
        data = self.get_api_call_json()

        attachments = data["attachments"]
        self.assertEqual(len(attachments), 2)

        self.assertEqual(
            attachments[0]["contentType"], 'text/plain; charset="iso-8859-1"'
        )
        self.assertEqual(attachments[0]["filename"], "attachment.txt")  # generated
        self.assertEqual(
            decode_att(attachments[0]["content"]).decode("iso-8859-1"), text_content
        )

        self.assertEqual(attachments[1]["contentType"], "image/x-emoticon")
        self.assertEqual(attachments[1]["filename"], "émoticône.img")
        self.assertEqual(decode_att(attachments[1]["content"]), b";-)")

    def test_inline_attachment_unsupported(self):
        # MailKite's send API has no Content-ID field, so it can't place inline
        # images -- raise rather than silently send them as regular attachments.
        image_data = sample_image_content()
        attach_inline_image(self.message, image_data, "test.png")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline attachments"):
            self.message.send()

    def test_missing_attachment_filename_unknown_type(self):
        self.message.attach(None, "data", "text/x-unknown-type")
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "unnamed attachments of type text/x-unknown-type"
        ):
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
        """Empty to, cc, bcc, and reply_to shouldn't generate empty fields"""
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
            "error": "invalid_api_key",
            "message": "The API key is invalid or has been revoked.",
        }
        self.set_mock_response(status_code=401, json_data=failure_response)
        with self.assertRaisesMessage(
            AnymailAPIError, r"MailKite API response 401"
        ) as cm:
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])
        self.assertIn("API key is invalid", str(cm.exception))

    @ignore_fail_silently_warning()
    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        failure_response = {
            "error": "invalid_api_key",
            "message": "The API key is invalid or has been revoked.",
        }
        self.set_mock_response(status_code=401, json_data=failure_response)
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

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "2013-11-12T01:02:03Z"
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2013-11-12T01:02:03Z")

    def test_tags(self):
        self.message.tags = ["receipt", "reorder test 12"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            json.loads(data["headers"]["X-Tags"]),
            ["receipt", "reorder test 12"],
        )

    def test_headers_metadata_tags_interaction(self):
        # Test three features that use custom headers don't clobber each other
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

    # --- Features MailKite supports that Resend does not ---

    def test_track_opens(self):
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackOpens"], True)

    def test_track_clicks(self):
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackClicks"], True)

    def test_template_id(self):
        self.message.template_id = "tpl_welcome"
        self.message.merge_global_data = {"name": "Ann", "plan": "pro"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["templateId"], "tpl_welcome")
        self.assertEqual(data["templateData"], {"name": "Ann", "plan": "pro"})

    _mock_batch_response = {
        "results": [
            {"to": "alice@example.com", "id": "msg_aaaa", "status": "sent"},
            {"to": "bob@example.com", "id": "msg_bbbb", "status": "sent"},
        ],
        "sent": 2,
        "scheduled": 0,
        "failed": 0,
    }

    def test_merge_data(self):
        self.message.merge_data = {"to@example.com": {"customer_id": 3}}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "merge_data"):
            self.message.send()

    def test_empty_merge_data(self):
        # `merge_data = {}` triggers batch send
        self.set_mock_response(json_data=self._mock_batch_response)
        message = AnymailMessage(
            from_email="from@example.com",
            to=["alice@example.com", "Bob <bob@example.com>"],
            merge_data={
                "alice@example.com": {},
                "bob@example.com": {},
            },
        )
        message.send()
        self.assert_esp_called("/v1/send/batch")
        data = self.get_api_call_json()
        # MailKite batch shape: shared fields + recipients[]
        self.assertEqual(data["from"], "from@example.com")
        self.assertEqual(len(data["recipients"]), 2)
        self.assertEqual(data["recipients"][0]["to"], "alice@example.com")
        self.assertEqual(data["recipients"][1]["to"], "Bob <bob@example.com>")

        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["alice@example.com"].status, "queued")
        self.assertEqual(recipients["alice@example.com"].message_id, "msg_aaaa")
        self.assertEqual(recipients["bob@example.com"].status, "queued")
        self.assertEqual(recipients["bob@example.com"].message_id, "msg_bbbb")

    def test_merge_metadata(self):
        self.set_mock_response(json_data=self._mock_batch_response)
        message = AnymailMessage(
            from_email="from@example.com",
            to=["alice@example.com", "Bob <bob@example.com>"],
            merge_metadata={
                "alice@example.com": {"order_id": 123, "tier": "premium"},
                "bob@example.com": {"order_id": 678},
            },
            metadata={"notification_batch": "zx912"},
        )
        message.send()

        # merge_metadata forces batch send API:
        self.assert_esp_called("/v1/send/batch")

        data = self.get_api_call_json()
        self.assertEqual(data["from"], "from@example.com")
        self.assertEqual(len(data["recipients"]), 2)
        self.assertEqual(data["recipients"][0]["to"], "alice@example.com")
        # metadata and merge_metadata[recipient] are combined per-recipient:
        self.assertEqual(
            json.loads(data["recipients"][0]["headers"]["X-Metadata"]),
            {"order_id": 123, "tier": "premium", "notification_batch": "zx912"},
        )
        self.assertEqual(data["recipients"][1]["to"], "Bob <bob@example.com>")
        self.assertEqual(
            json.loads(data["recipients"][1]["headers"]["X-Metadata"]),
            {"order_id": 678, "notification_batch": "zx912"},
        )
        # Shared base metadata is *also* shipped at the top level (per-recipient
        # headers override it for each recipient):
        self.assertEqual(
            json.loads(data["headers"]["X-Metadata"]),
            {"notification_batch": "zx912"},
        )

        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["alice@example.com"].status, "queued")
        self.assertEqual(recipients["alice@example.com"].message_id, "msg_aaaa")
        self.assertEqual(recipients["bob@example.com"].status, "queued")
        self.assertEqual(recipients["bob@example.com"].message_id, "msg_bbbb")

    def test_merge_headers(self):
        self.set_mock_response(json_data=self._mock_batch_response)
        message = AnymailMessage(
            from_email="from@example.com",
            to=["alice@example.com", "Bob <bob@example.com>"],
            headers={
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
            },
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

        # merge_headers forces batch send API:
        self.assert_esp_called("/v1/send/batch")

        data = self.get_api_call_json()
        # Shared headers stay at the top level...
        self.assertEqual(
            data["headers"],
            {
                "List-Unsubscribe": "<mailto:unsubscribe@example.com>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )
        # ...and each recipient overrides the per-recipient header:
        self.assertEqual(len(data["recipients"]), 2)
        self.assertEqual(data["recipients"][0]["to"], "alice@example.com")
        self.assertEqual(
            data["recipients"][0]["headers"],
            {"List-Unsubscribe": "<https://example.com/a/>"},
        )
        self.assertEqual(data["recipients"][1]["to"], "Bob <bob@example.com>")
        self.assertEqual(
            data["recipients"][1]["headers"],
            {"List-Unsubscribe": "<https://example.com/b/>"},
        )

    def test_batch_recipient_rejected(self):
        # A batch can partially succeed: MailKite reports a per-recipient failure
        # in results[], and Anymail should surface it as a "rejected" recipient.
        self.set_mock_response(
            json_data={
                "results": [
                    {"to": "alice@example.com", "id": "msg_aaaa", "status": "sent"},
                    {
                        "to": "bob@example.com",
                        "status": "failed",
                        "error": "recipient suppressed",
                        "code": "recipient_suppressed",
                    },
                ],
                "sent": 1,
                "scheduled": 0,
                "failed": 1,
            }
        )
        message = AnymailMessage(
            from_email="from@example.com",
            to=["alice@example.com", "bob@example.com"],
            merge_data={"alice@example.com": {}, "bob@example.com": {}},
        )
        message.send()
        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["alice@example.com"].status, "queued")
        self.assertEqual(recipients["alice@example.com"].message_id, "msg_aaaa")
        self.assertEqual(recipients["bob@example.com"].status, "rejected")
        self.assertIsNone(recipients["bob@example.com"].message_id)

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
        self.assertNotIn("scheduledAt", data)
        self.assertNotIn("trackOpens", data)
        self.assertNotIn("trackClicks", data)
        self.assertNotIn("templateId", data)
        self.assertNotIn("templateData", data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            "trackOpens": False,
            "headers": {"X-Extra": "from esp_extra"},
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertIs(data["trackOpens"], False)
        self.assertEqual(data["headers"]["X-Extra"], "from esp_extra")

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
        self.assertEqual(msg.anymail_status.message_id, "msg_aaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "msg_aaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(
            msg.anymail_status.esp_response.content, self.DEFAULT_RAW_RESPONSE
        )

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
            print(self.get_api_call_json())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to MailKite", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("mailkite")
class MailKiteBackendRecipientsRefusedTests(MailKiteBackendMockAPITestCase):
    # MailKite checks recipient suppression at send time for batch sends and
    # reports it per-recipient, but for a single send it accepts and queues. So
    # there's no up-front refused-recipient handling to test here (the refused
    # case for batch is covered in MailKiteBackendAnymailFeatureTests).
    pass


@tag("mailkite")
class MailKiteBackendSessionSharingTestCase(
    SessionSharingTestCases, MailKiteBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mailkite")
@override_settings(
    MAILERS={"default": {"BACKEND": "anymail.backends.mailkite.EmailBackend"}}
)
class MailKiteBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaisesRegex(
            AnymailConfigurationError,
            r"'api_key'|\bMAILKITE_API_KEY.*ANYMAIL_MAILKITE_API_KEY",
        ):
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
