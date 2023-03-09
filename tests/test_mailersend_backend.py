from calendar import timegm
from datetime import date, datetime
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core import mail
from django.test import override_settings, tag
from django.utils.timezone import (
    get_fixed_timezone,
    override as override_current_timezone,
)

from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailRecipientsRefused,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import attach_inline_image_file

from .mock_requests_backend import RequestsBackendMockAPITestCase
from .utils import (
    SAMPLE_IMAGE_FILENAME,
    decode_att,
    sample_image_content,
    sample_image_path,
)


@tag("mailersend")
@override_settings(
    EMAIL_BACKEND="anymail.backends.mailersend.EmailBackend",
    ANYMAIL={"MAILERSEND_API_TOKEN": "test_api_token"},
)
class MailerSendBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    """TestCase that uses MailerSend EmailBackend with a mocked API"""

    DEFAULT_STATUS_CODE = 202
    DEFAULT_RAW_RESPONSE = b""
    DEFAULT_CONTENT_TYPE = "text/html"

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )

    def set_mock_success(self, message_id="1234567890abcdef"):
        response = self.set_mock_response()
        if message_id is not None:
            response.headers["x-message-id"] = message_id
        return response

    def set_mock_rejected(
        self, rejections, warning_type="ALL_SUPPRESSED", message_id="1234567890abcdef"
    ):
        """rejections should be a dict of {email: [reject_reason, ...], ...}"""
        if warning_type == "ALL_SUPPRESSED":
            message_id = None
        response = self.set_mock_response(
            json_data={
                "warnings": [
                    {
                        "type": warning_type,
                        "recipients": [
                            {"email": email, "reasons": reasons}
                            for email, reasons in rejections.items()
                        ],
                    }
                ]
            }
        )
        if message_id is not None:
            response.headers["x-message-id"] = message_id
        return response


@tag("mailersend")
class MailerSendBackendStandardEmailTests(MailerSendBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@example.com",
            ["to@example.com"],
            fail_silently=False,
        )

        self.assert_esp_called("/v1/email")

        headers = self.get_api_call_headers()
        self.assertEqual(headers["Authorization"], "Bearer test_api_token")

        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["text"], "Here is the message.")
        self.assertEqual(data["from"], {"email": "from@example.com"})
        self.assertEqual(data["to"], [{"email": "to@example.com"}])

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
        self.assertEqual(
            data["from"], {"email": "from@example.com", "name": "From Name"}
        )
        self.assertEqual(
            data["to"],
            [
                {"email": "to1@example.com", "name": "Recipient #1"},
                {"email": "to2@example.com"},
            ],
        )
        self.assertEqual(
            data["cc"],
            [
                {"email": "cc1@example.com", "name": "Carbon Copy"},
                {"email": "cc2@example.com"},
            ],
        )
        self.assertEqual(
            data["bcc"],
            [
                {"email": "bcc1@example.com", "name": "Blind Copy"},
                {"email": "bcc2@example.com"},
            ],
        )

    def test_custom_headers(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            headers={
                "Reply-To": "another@example.com",
                "In-Reply-To": "12345@example.com",
                "X-MyHeader": "my value",
                "Message-ID": "mycustommsgid@example.com",
                "Precedence": "Bulk",
            },
        )
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "extra_headers"):
            email.send()

    def test_supported_custom_headers(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            headers={
                "Reply-To": "another@example.com",
                "In-Reply-To": "12345@example.com",
                "Precedence": "Bulk",
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["reply_to"], {"email": "another@example.com"})
        self.assertEqual(data["in_reply_to"], "12345@example.com")
        self.assertIs(data["precedence_bulk"], True)

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

    def test_reply_to(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["Reply Name <reply@example.com>"],
        )
        email.send()

        data = self.get_api_call_json()
        self.assertEqual(
            data["reply_to"], {"email": "reply@example.com", "name": "Reply Name"}
        )

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(
            filename="test.txt", content=text_content, mimetype="text/plain"
        )

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        # Should work with a MIMEBase object (also tests no filename)...
        pdf_content = b"PDF\xb4 pretend this is valid pdf params"
        mimeattachment = MIMEBase("application", "pdf")
        mimeattachment.set_payload(pdf_content)
        self.message.attach(mimeattachment)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["disposition"], "attachment")
        self.assertEqual(attachments[0]["filename"], "test.txt")
        self.assertEqual(
            decode_att(attachments[0]["content"]).decode("ascii"), text_content
        )
        self.assertEqual(attachments[1]["disposition"], "attachment")
        self.assertEqual(attachments[1]["filename"], "test.png")
        self.assertEqual(decode_att(attachments[1]["content"]), png_content)
        self.assertEqual(attachments[2]["disposition"], "attachment")
        self.assertEqual(attachments[2]["filename"], "attachment.pdf")  # generated
        self.assertEqual(decode_att(attachments[2]["content"]), pdf_content)

    def test_unicode_attachment_correctly_decoded(self):
        # Slight modification from the Django unicode docs:
        # http://django.readthedocs.org/en/latest/ref/unicode.html#email
        self.message.attach(
            "Une pièce jointe.html", "<p>\u2019</p>", mimetype="text/html"
        )
        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)
        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["html"], html_content)

        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["disposition"], "inline")
        self.assertEqual(data["attachments"][0]["filename"], image_filename)
        self.assertEqual(data["attachments"][0]["id"], cid)
        self.assertEqual(decode_att(data["attachments"][0]["content"]), image_data)

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        # option 1: attach as a file
        self.message.attach_file(image_path)

        # option 2: construct the MIMEImage and attach it directly
        image = MIMEImage(image_data)
        self.message.attach(image)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["disposition"], "attachment")
        self.assertEqual(attachments[0]["filename"], image_filename)
        self.assertEqual(decode_att(attachments[0]["content"]), image_data)
        self.assertNotIn("id", attachments[0])  # not inline
        self.assertEqual(attachments[1]["disposition"], "attachment")
        self.assertEqual(attachments[1]["filename"], "attachment.png")  # generated
        self.assertEqual(decode_att(attachments[1]["content"]), image_data)
        self.assertNotIn("id", attachments[0])  # not inline

    def test_multiple_html_alternatives(self):
        # Multiple text/html alternatives not allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>But not second html</p>", "text/html")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_html_alternative(self):
        # Only html alternatives allowed
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_alternatives_fail_silently(self):
        # Make sure fail_silently is respected
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        sent = self.message.send(fail_silently=True)
        self.assert_esp_not_called("API should not be called when send fails silently")
        self.assertEqual(sent, 0)

    def test_suppress_empty_address_lists(self):
        """Empty cc, bcc, and reply_to shouldn't generate empty headers"""
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("cc", data)
        self.assertNotIn("bcc", data)
        self.assertNotIn("reply_to", data)

    # MailerSend requires at least one "to" address
    # def test_empty_to(self):
    #     self.message.to = []
    #     self.message.cc = ["cc@example.com"]
    #     self.message.send()
    #     data = self.get_api_call_json()

    def test_api_failure(self):
        raw_errors = {
            "message": "Helpful ESP explanation",
            "errors": {"some.field": ["The some.field must be valid."]},
        }
        self.set_mock_response(
            status_code=422, reason="UNPROCESSABLE ENTITY", json_data=raw_errors
        )
        # Error string includes ESP response:
        with self.assertRaisesMessage(AnymailAPIError, "Helpful ESP explanation"):
            self.message.send()

    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        self.set_mock_response(status_code=422)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)


@tag("mailersend")
class MailerSendBackendAnymailFeatureTests(MailerSendBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "bounce-handler@bounces.example.com"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "envelope_sender"):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": "mailer, send"}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "metadata"):
            self.message.send()

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        with override_current_timezone(utc_plus_6):
            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["send_at"], timegm((2016, 3, 4, 13, 6, 7))
            )  # 05:06 UTC-8 == 13:06 UTC

            # Timezone-naive datetime assumed to be Django current_timezone
            self.message.send_at = datetime(
                2022, 10, 11, 12, 13, 14, 567
            )  # microseconds should get stripped
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["send_at"], timegm((2022, 10, 11, 6, 13, 14))
            )  # 12:13 UTC+6 == 06:13 UTC

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["send_at"], timegm((2022, 10, 21, 18, 0, 0))
            )  # 00:00 UTC+6 == 18:00-1d UTC

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["send_at"], 1651820889)

    def test_tags(self):
        self.message.tags = ["receipt", "repeat-user"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["tags"], ["receipt", "repeat-user"])

    def test_tracking(self):
        # Test one way...
        self.message.track_opens = True
        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["settings"]["track_opens"], True)
        self.assertEqual(data["settings"]["track_clicks"], False)

        # ...and the opposite way
        self.message.track_opens = False
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["settings"]["track_opens"], False)
        self.assertEqual(data["settings"]["track_clicks"], True)

    def test_template_id(self):
        message = mail.EmailMultiAlternatives(
            from_email="from@example.com", to=["to@example.com"]
        )
        message.template_id = "zyxwvut98765"
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["template_id"], "zyxwvut98765")
        # With a template, MailerSend always ignores "text" and "html" params.
        # For "subject", "from_email", and "reply_to" params, MailerSend ignores them
        # if the corresponding field is set in the template's "Default settings",
        # otherwise it uses the params. (And "subject" and "from_email" are required
        # if no default setting for the template.)
        # For "tags", MailerSend uses the param value if provided, otherwise
        # the template default if any. (It does not attempt to combine them.)

    @override_settings(ANYMAIL_MAILERSEND_BATCH_SEND_MODE="expose-to-list")
    def test_merge_data_expose_to_list(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.cc = ["cc@example.com"]
        self.message.body = "Hi {{ name }}. Welcome to {{ group }} at {{ site }}."
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice", "group": "Developers"},
            "bob@example.com": {"name": "Bob"},  # and leave group undefined
            "nobody@example.com": {"name": "Not a recipient for this message"},
        }
        self.message.merge_global_data = {"group": "Users", "site": "ExampleCo"}

        self.message.send()
        # BATCH_SEND_MODE="expose-to-list" uses 'email' API endpoint:
        self.assert_esp_called("/v1/email")
        data = self.get_api_call_json()
        # personalization param covers all recipients:
        self.assertEqual(
            data["personalization"],
            [
                {
                    "email": "alice@example.com",
                    "data": {
                        "name": "Alice",
                        "group": "Developers",
                        "site": "ExampleCo",
                    },
                },
                {
                    "email": "bob@example.com",
                    "data": {"name": "Bob", "group": "Users", "site": "ExampleCo"},
                },
                # No personalization record for "nobody@example.com" -- including a
                # personalization for email not found in "to" param causes API error.
            ],
        )

    @override_settings(ANYMAIL_MAILERSEND_BATCH_SEND_MODE="use-bulk-email")
    def test_merge_data_use_bulk_email(self):
        self.set_mock_response(
            json_data={
                "message": "The bulk email is being processed.",
                "bulk_email_id": "12345abcde",
            }
        )
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.cc = ["cc@example.com"]
        self.message.body = "Hi {{ name }}. Welcome to {{ group }} at {{ site }}."
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice", "group": "Developers"},
            "bob@example.com": {"name": "Bob"},  # and leave group undefined
            "nobody@example.com": {"name": "Not a recipient for this message"},
        }
        self.message.merge_global_data = {"group": "Users", "site": "ExampleCo"}

        self.message.send()
        # BATCH_SEND_MODE="use-bulk-email" uses 'bulk-email' API endpoint:
        self.assert_esp_called("/v1/bulk-email")
        data = self.get_api_call_json()
        self.assertEqual(len(data), 2)  # batch of 2 separate emails
        # "to" split to separate messages:
        self.assertEqual(data[0]["to"], [{"email": "alice@example.com"}])
        self.assertEqual(data[1]["to"], [{"email": "bob@example.com", "name": "Bob"}])
        # "cc" appears in both:
        self.assertEqual(data[0]["cc"], [{"email": "cc@example.com"}])
        self.assertEqual(data[1]["cc"], [{"email": "cc@example.com"}])
        # "personalization" param matches only single recipient:
        self.assertEqual(
            data[0]["personalization"],
            [
                {
                    "email": "alice@example.com",
                    "data": {
                        "name": "Alice",
                        "group": "Developers",
                        "site": "ExampleCo",
                    },
                }
            ],
        )
        self.assertEqual(
            data[1]["personalization"],
            [
                {
                    "email": "bob@example.com",
                    "data": {"name": "Bob", "group": "Users", "site": "ExampleCo"},
                }
            ],
        )

    def test_merge_data_single_recipient(self):
        # BATCH_SEND_MODE=None default uses 'email' for single recipient
        self.message.to = ["Bob <bob@example.com>"]
        self.message.cc = ["cc@example.com"]
        self.message.body = "Hi {{ name }}. Welcome to {{ group }} at {{ site }}."
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice", "group": "Developers"},
            "bob@example.com": {"name": "Bob"},  # and leave group undefined
            "nobody@example.com": {"name": "Not a recipient for this message"},
        }
        self.message.merge_global_data = {"group": "Users", "site": "ExampleCo"}

        self.message.send()
        self.assert_esp_called("/v1/email")
        data = self.get_api_call_json()
        self.assertEqual(
            data["personalization"],
            [
                {
                    "email": "bob@example.com",
                    "data": {"name": "Bob", "group": "Users", "site": "ExampleCo"},
                },
                # No personalization record for merge_data emails not in "to" list.
            ],
        )

    def test_merge_data_ambiguous(self):
        # Multiple recipients require a non-default MAILERSEND_BATCH_SEND_MODE
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.cc = ["cc@example.com"]
        self.message.body = "Hi {{ name }}. Welcome to {{ group }} at {{ site }}."
        # (even an empty merge_data dict should trigger Anymail batch send)
        self.message.merge_data = {}

        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "MAILERSEND_BATCH_SEND_MODE"
        ):
            self.message.send()

    def test_merge_metadata(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.merge_metadata = {
            "alice@example.com": {"order_id": 123},
            "bob@example.com": {"order_id": 678, "tier": "premium"},
        }

        with self.assertRaisesMessage(AnymailUnsupportedFeature, "merge_metadata"):
            self.message.send()

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("cc", data)
        self.assertNotIn("bcc", data)
        self.assertNotIn("reply_to", data)
        self.assertNotIn("html", data)
        self.assertNotIn("attachments", data)
        self.assertNotIn("template_id", data)
        self.assertNotIn("tags", data)
        self.assertNotIn("variables", data)
        self.assertNotIn("personalization", data)
        self.assertNotIn("precedence_bulk", data)
        self.assertNotIn("send_at", data)
        self.assertNotIn("in_reply_to", data)
        self.assertNotIn("settings", data)

    def test_esp_extra(self):
        self.message.track_clicks = True  # test deep merge of "settings"
        self.message.esp_extra = {
            "variables": [
                {
                    "email": "to@example.com",
                    "substitutions": [{"var": "order_id", "value": "12345"}],
                }
            ],
            "settings": {
                "track_content": True,
            },
        }
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["variables"],
            [
                {
                    "email": "to@example.com",
                    "substitutions": [{"var": "order_id", "value": "12345"}],
                }
            ],
        )
        self.assertEqual(
            data["settings"],
            {
                "track_content": True,
                "track_clicks": True,  # deep merge
            },
        )

    def test_esp_extra_settings_overrides(self):
        """esp_extra can override batch_send_mode and api_token settings"""
        self.message.merge_data = {}  # trigger batch send
        self.message.esp_extra = {
            "api_token": "token-from-esp-extra",
            "batch_send_mode": "use-bulk-email",
            "hypothetical_future_mailersend_param": 123,
        }
        self.message.send()
        self.assert_esp_called("/v1/bulk-email")  # batch_send_mode from esp_extra
        headers = self.get_api_call_headers()
        self.assertEqual(headers["Authorization"], "Bearer token-from-esp-extra")

        data = self.get_api_call_json()
        self.assertEqual(len(data), 1)  # payload burst for batch
        self.assertNotIn("api_token", data[0])  # not in API payload
        self.assertNotIn("batch_send_mode", data[0])  # not sent to API
        # But other esp_extra params sent:
        self.assertEqual(data[0]["hypothetical_future_mailersend_param"], 123)

    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        self.set_mock_success(message_id="12345abcde")
        msg = mail.EmailMessage(
            "Subject", "Message", "from@example.com", ["to1@example.com"]
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(msg.anymail_status.message_id, "12345abcde")
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "12345abcde",
        )

    @override_settings(
        ANYMAIL_IGNORE_RECIPIENT_STATUS=True  # exception is tested later
    )
    def test_send_all_rejected(self):
        """The anymail_status should be 'rejected' when all recipients rejected"""
        self.set_mock_rejected(
            {"to1@example.com": ["blocklisted"], "to2@example.com": ["hard_bounced"]}
        )
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com", "to2@example.com"],
        )
        msg.send()
        self.assertEqual(msg.anymail_status.status, {"rejected"})
        recipients = msg.anymail_status.recipients
        self.assertEqual(recipients["to1@example.com"].status, "rejected")
        self.assertIsNone(recipients["to1@example.com"].message_id)
        self.assertEqual(recipients["to2@example.com"].status, "rejected")
        self.assertIsNone(recipients["to2@example.com"].message_id)

    def test_send_some_rejected(self):
        """
        The anymail_status should identify which recipients are rejected.
        """
        self.set_mock_rejected(
            {"to1@example.com": ["blocklisted"]},
            warning_type="SOME_SUPPRESSED",
            message_id="12345abcde",
        )
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com", "to2@example.com"],
        )
        msg.send()
        self.assertEqual(msg.anymail_status.status, {"rejected", "queued"})
        recipients = msg.anymail_status.recipients
        self.assertEqual(recipients["to1@example.com"].status, "rejected")
        self.assertIsNone(recipients["to1@example.com"].message_id)
        self.assertEqual(recipients["to2@example.com"].status, "queued")
        self.assertEqual(recipients["to2@example.com"].message_id, "12345abcde")

    # noinspection PyUnresolvedReferences
    @override_settings(ANYMAIL_MAILERSEND_BATCH_SEND_MODE="use-bulk-email")
    def test_bulk_send_response(self):
        self.set_mock_response(
            json_data={
                "message": "The bulk email is being processed.",
                "bulk_email_id": "12345abcde",
            }
        )
        self.message.merge_data = {}  # trigger batch behavior
        self.message.send()
        # Unknown status for bulk send (until you poll the status API):
        self.assertEqual(self.message.anymail_status.status, {"unknown"})
        # Unknown message_id for bulk send, so provide batch id with "bulk:" prefix:
        self.assertEqual(self.message.anymail_status.message_id, "bulk:12345abcde")

    # noinspection PyUnresolvedReferences
    def test_send_failed_anymail_status(self):
        """If the send fails, anymail_status should contain initial values"""
        self.set_mock_response(status_code=400)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertIsNone(self.message.anymail_status.esp_response)

    # noinspection PyUnresolvedReferences
    def test_unhandled_warnings(self):
        # Non-suppression warnings should turn a 202 accepted response into an error
        response_content = {"warnings": [{"type": "UNKNOWN_WARNING"}]}
        self.set_mock_response(status_code=202, json_data=response_content)
        with self.assertRaisesMessage(AnymailAPIError, "UNKNOWN_WARNING"):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(
            self.message.anymail_status.esp_response.json(), response_content
        )

    def test_json_serialization_errors(self):
        """Try to provide more information about non-json-serializable data"""
        self.message.tags = [Decimal("19.99")]  # yeah, don't do this
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
            print(self.get_api_call_json())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to MailerSend", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("mailersend")
class MailerSendBackendRecipientsRefusedTests(MailerSendBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid
    """

    def test_recipients_refused(self):
        self.set_mock_rejected(
            {
                "invalid@localhost": ["hard_bounced"],
                "reject@example.com": ["blocklisted"],
            }
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["invalid@localhost", "reject@example.com"],
        )
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_rejected(
            {
                "invalid@localhost": ["hard_bounced"],
                "reject@example.com": ["blocklisted"],
            }
        )
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["invalid@localhost", "reject@example.com"],
            fail_silently=True,
        )
        self.assertEqual(sent, 0)

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        self.set_mock_rejected(
            {
                "invalid@localhost": ["hard_bounced"],
                "reject@example.com": ["blocklisted"],
            },
            warning_type="SOME_SUPPRESSED",
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            [
                "invalid@localhost",
                "valid@example.com",
                "reject@example.com",
                "also.valid@example.com",
            ],
        )
        sent = msg.send()
        # one message sent, successfully, to 2 of 4 recipients:
        self.assertEqual(sent, 1)
        status = msg.anymail_status
        self.assertEqual(status.recipients["invalid@localhost"].status, "rejected")
        self.assertEqual(status.recipients["valid@example.com"].status, "queued")
        self.assertEqual(status.recipients["reject@example.com"].status, "rejected")
        self.assertEqual(status.recipients["also.valid@example.com"].status, "queued")

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)
    def test_settings_override(self):
        """No exception with ignore setting"""
        self.set_mock_rejected(
            {
                "invalid@localhost": ["hard_bounced"],
                "reject@example.com": ["blocklisted"],
            },
        )
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["invalid@localhost", "reject@example.com"],
        )
        self.assertEqual(sent, 1)  # refused message is included in sent count


@tag("mailersend")
class MailerSendBackendConfigurationTests(MailerSendBackendMockAPITestCase):
    """Test various MailerSend client options"""

    @override_settings(
        # clear MAILERSEND_API_TOKEN from MailerSendBackendMockAPITestCase:
        ANYMAIL={}
    )
    def test_missing_api_token(self):
        with self.assertRaises(AnymailConfigurationError) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        # Make sure the error mentions the different places to set the key
        self.assertRegex(errmsg, r"\bMAILERSEND_API_TOKEN\b")
        self.assertRegex(errmsg, r"\bANYMAIL_MAILERSEND_API_TOKEN\b")

    @override_settings(
        ANYMAIL={
            "MAILERSEND_API_URL": "https://api.dev.mailersend.com/v2",
            "MAILERSEND_API_TOKEN": "test_api_key",
        }
    )
    def test_mailersend_api_url(self):
        mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        self.assert_esp_called("https://api.dev.mailersend.com/v2/email")

        # can also override on individual connection
        connection = mail.get_connection(api_url="https://api.mailersend.com/vNext")
        mail.send_mail(
            "Subject",
            "Message",
            "from@example.com",
            ["to@example.com"],
            connection=connection,
        )
        self.assert_esp_called("https://api.mailersend.com/vNext/email")

    @override_settings(ANYMAIL={"MAILERSEND_API_TOKEN": "bad_token"})
    def test_invalid_api_key(self):
        self.set_mock_response(
            status_code=401,
            reason="UNAUTHORIZED",
            json_data={"message": "Unauthenticated."},
        )
        with self.assertRaisesMessage(AnymailAPIError, "Unauthenticated"):
            self.message.send()
