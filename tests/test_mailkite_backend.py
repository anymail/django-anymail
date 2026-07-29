from datetime import date, datetime

from django.core import mail
from django.test import SimpleTestCase, tag
from django.utils.timezone import (
    get_fixed_timezone,
    override as override_current_timezone,
)

from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailUnsupportedFeature,
)
from anymail.message import AnymailMessage, attach_inline_image

from .mock_requests_backend import RequestsBackendMockAPITestCase
from .utils import (
    AnymailTestMixin,
    create_text_attachment,
    decode_att,
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
    DEFAULT_RAW_RESPONSE = (
        b'{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "status": "sent"}'
    )

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
        self.assert_esp_called("https://api.mailkite.dev/v1/send")
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
            data["to"],
            ["Recipient #1 <to1@example.com>", "to2@example.com"],
        )
        self.assertEqual(
            data["cc"], ["Carbon Copy <cc1@example.com>", "cc2@example.com"]
        )
        self.assertEqual(
            data["bcc"], ["Blind Copy <bcc1@example.com>", "bcc2@example.com"]
        )

    def test_html_message(self):
        msg = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )
        msg.attach_alternative("<p>HTML body</p>", "text/html")
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(data["text"], "Text Body")
        self.assertEqual(data["html"], "<p>HTML body</p>")

    def test_reply_to(self):
        # MailKite's replyTo is a single string; multiple addresses are
        # comma-joined into one Reply-To value.
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

    def test_extra_headers(self):
        email = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            headers={"X-Extra": "extra value"},
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["headers"], {"X-Extra": "extra value"})

    def test_extra_headers_numeric(self):
        # MailKite (like the API generally) wants header values as strings.
        email = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            headers={"X-Count": 4, "X-Rate": 1.5},
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["headers"], {"X-Count": "4", "X-Rate": "1.5"})

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

    def test_inline_attachments_unsupported(self):
        # MailKite's send API attachment has no content-id / inline field, so
        # inline (cid-referenced) attachments can't be expressed.
        attach_inline_image(self.message, sample_image_content(), "test.png")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline attachments"):
            self.message.send()


@tag("mailkite")
class MailKiteBackendAnymailFeatureTests(MailKiteBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_template_id(self):
        # MailKite server-rendered templates: templateId (+ templateData).
        message = AnymailMessage(
            "Subject",
            "Text Body",
            "from@example.com",
            ["to@example.com"],
            template_id="tpl_abc123",
            merge_global_data={"name": "Sam", "plan": "Pro"},
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["templateId"], "tpl_abc123")
        self.assertEqual(data["templateData"], {"name": "Sam", "plan": "Pro"})

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

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "2013-11-12T01:02:03Z"
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["scheduledAt"], "2013-11-12T01:02:03Z")

    def test_track_opens(self):
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["trackOpens"], True)

    def test_unsupported_tags(self):
        self.message.tags = ["receipt"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "tags"):
            self.message.send()

    def test_unsupported_metadata(self):
        self.message.metadata = {"order_id": "123"}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "metadata"):
            self.message.send()

    def test_unsupported_merge_data(self):
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice"},
            "bob@example.com": {"name": "Bob"},
        }
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "merge_data"):
            self.message.send()

    def test_empty_merge_data_allowed(self):
        # Empty merge_data is a no-op (MailKite has no batch send, so it just
        # degrades to a single message). It must not raise.
        self.message.merge_data = {}
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("templateData", data)

    def test_esp_extra(self):
        # esp_extra is merged into the API payload (e.g. inReplyTo for threading)
        message = AnymailMessage(
            "Subject",
            "Text Body",
            "from@example.com",
            ["to@example.com"],
            esp_extra={"inReplyTo": "<original@example.com>"},
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["inReplyTo"], "<original@example.com>")


@tag("mailkite")
class MailKiteBackendRecipientsStatusTests(MailKiteBackendMockAPITestCase):
    """Test the recipient status parsing for various responses"""

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
        self.assertEqual(msg.anymail_status.status, {"sent"})
        self.assertEqual(
            msg.anymail_status.message_id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "sent"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(
            msg.anymail_status.esp_response.content, self.DEFAULT_RAW_RESPONSE
        )

    def test_scheduled_status(self):
        """A 'scheduled' response marks recipients as queued"""
        self.set_mock_response(raw=b'{"id": "sched_123", "status": "scheduled"}')
        msg = mail.EmailMessage(
            "Subject", "Message", "from@example.com", ["to@example.com"]
        )
        msg.send()
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(msg.anymail_status.message_id, "sched_123")

    def test_all_recipients_share_message_id(self):
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com", "to2@example.com"],
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
        )
        msg.send()
        recipients = msg.anymail_status.recipients
        # MailKite returns a single send-level message id shared by all recipients
        for addr in [
            "to1@example.com",
            "to2@example.com",
            "cc@example.com",
            "bcc@example.com",
        ]:
            self.assertEqual(recipients[addr].message_id, msg.anymail_status.message_id)
            self.assertEqual(recipients[addr].status, "sent")

    def test_invalid_response_raises(self):
        self.set_mock_response(raw=b'{"unexpected": "format"}')
        msg = mail.EmailMessage(
            "Subject", "Message", "from@example.com", ["to@example.com"]
        )
        with self.assertRaises(AnymailAPIError):
            msg.send()

    def test_send_failed_anymail_status(self):
        msg = mail.EmailMessage(
            "Subject", "Message", "from@example.com", ["to@example.com"]
        )
        self.set_mock_response(status_code=500)
        with self.assertRaises(AnymailAPIError):
            msg.send()
        self.assertIsNone(msg.anymail_status.status)
        self.assertIsNone(msg.anymail_status.message_id)


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
