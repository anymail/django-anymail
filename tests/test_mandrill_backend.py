from datetime import date, datetime
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag
from django.utils.timezone import (
    get_fixed_timezone,
    override as override_current_timezone,
)

from anymail.exceptions import (
    AnymailAPIError,
    AnymailRecipientsRefused,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import attach_inline_image

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import (
    SAMPLE_IMAGE_FILENAME,
    AnymailTestMixin,
    decode_att,
    sample_image_content,
    sample_image_path,
)


@tag("mandrill")
@override_settings(
    EMAIL_BACKEND="anymail.backends.mandrill.EmailBackend",
    ANYMAIL={"MANDRILL_API_KEY": "test_api_key"},
)
class MandrillBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""[{
        "email": "to@example.com",
        "status": "sent",
        "_id": "abc123",
        "reject_reason": null
    }]"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("mandrill")
class MandrillBackendStandardEmailTests(MandrillBackendMockAPITestCase):
    """Test backend support for Django mail wrappers"""

    def test_send_mail(self):
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@example.com",
            ["to@example.com"],
            fail_silently=False,
        )
        self.assert_esp_called("/messages/send.json")
        data = self.get_api_call_json()
        self.assertEqual(data["key"], "test_api_key")
        self.assertEqual(data["message"]["subject"], "Subject here")
        self.assertEqual(data["message"]["text"], "Here is the message.")
        self.assertNotIn("from_name", data["message"])
        self.assertEqual(data["message"]["from_email"], "from@example.com")
        self.assertEqual(
            data["message"]["to"], [{"email": "to@example.com", "type": "to"}]
        )

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
        self.assertEqual(data["message"]["from_name"], "From Name")
        self.assertEqual(data["message"]["from_email"], "from@example.com")
        self.assertEqual(
            data["message"]["to"],
            [
                {"email": "to1@example.com", "name": "Recipient #1", "type": "to"},
                {"email": "to2@example.com", "type": "to"},
                {"email": "cc1@example.com", "name": "Carbon Copy", "type": "cc"},
                {"email": "cc2@example.com", "type": "cc"},
                {"email": "bcc1@example.com", "name": "Blind Copy", "type": "bcc"},
                {"email": "bcc2@example.com", "type": "bcc"},
            ],
        )

    def test_email_message(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com", "Also To <to2@example.com>"],
            bcc=["bcc1@example.com", "Also BCC <bcc2@example.com>"],
            cc=["cc1@example.com", "Also CC <cc2@example.com>"],
            headers={
                "Reply-To": "another@example.com",
                "X-MyHeader": "my value",
                "Message-ID": "mycustommsgid@example.com",
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["subject"], "Subject")
        self.assertEqual(data["message"]["text"], "Body goes here")
        self.assertEqual(data["message"]["from_email"], "from@example.com")
        self.assertEqual(
            data["message"]["headers"],
            {
                "Reply-To": "another@example.com",
                "X-MyHeader": "my value",
                "Message-ID": "mycustommsgid@example.com",
            },
        )
        # Verify recipients correctly identified as "to", "cc", or "bcc"
        self.assertEqual(
            data["message"]["to"],
            [
                {"email": "to1@example.com", "type": "to"},
                {"email": "to2@example.com", "name": "Also To", "type": "to"},
                {"email": "cc1@example.com", "type": "cc"},
                {"email": "cc2@example.com", "name": "Also CC", "type": "cc"},
                {"email": "bcc1@example.com", "type": "bcc"},
                {"email": "bcc2@example.com", "name": "Also BCC", "type": "bcc"},
            ],
        )
        # Don't use Mandrill's bcc_address "logging" feature for bcc's:
        self.assertNotIn("bcc_address", data["message"])

    def test_html_message(self):
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["text"], text_content)
        self.assertEqual(data["message"]["html"], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertFalse("attachments" in data["message"])

    def test_html_only_message(self):
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMessage(
            "Subject", html_content, "from@example.com", ["to@example.com"]
        )
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        data = self.get_api_call_json()
        self.assertNotIn("text", data["message"])
        self.assertEqual(data["message"]["html"], html_content)

    def test_reply_to(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["reply@example.com", "Other <reply2@example.com>"],
            headers={"X-Other": "Keep"},
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["message"]["headers"]["Reply-To"],
            "reply@example.com, Other <reply2@example.com>",
        )
        # don't lose other headers:
        self.assertEqual(data["message"]["headers"]["X-Other"], "Keep")

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(
            filename="test.txt", content=text_content, mimetype="text/plain"
        )

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        # Should work with a MIMEBase object (also tests no filename)...
        pdf_content = b"PDF\xb4 pretend this is valid pdf data"
        mimeattachment = MIMEBase("application", "pdf")
        mimeattachment.set_payload(pdf_content)
        self.message.attach(mimeattachment)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["message"]["attachments"]
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["type"], "text/plain")
        self.assertEqual(attachments[0]["name"], "test.txt")
        self.assertEqual(
            decode_att(attachments[0]["content"]).decode("ascii"), text_content
        )
        self.assertEqual(attachments[1]["type"], "image/png")  # inferred from filename
        self.assertEqual(attachments[1]["name"], "test.png")
        self.assertEqual(decode_att(attachments[1]["content"]), png_content)
        self.assertEqual(attachments[2]["type"], "application/pdf")
        self.assertEqual(attachments[2]["name"], "")  # none
        self.assertEqual(decode_att(attachments[2]["content"]), pdf_content)
        # Make sure the image attachment is not treated as embedded:
        self.assertFalse("images" in data["message"])

    def test_unicode_attachment_correctly_decoded(self):
        self.message.attach(
            "Une pièce jointe.html", "<p>\u2019</p>", mimetype="text/html"
        )
        self.message.send()
        data = self.get_api_call_json()
        attachments = data["message"]["attachments"]
        self.assertEqual(len(attachments), 1)

    def test_embedded_images(self):
        image_data = sample_image_content()  # Read from a png file

        cid = attach_inline_image(self.message, image_data)
        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["message"]["images"]), 1)
        self.assertEqual(data["message"]["images"][0]["type"], "image/png")
        self.assertEqual(data["message"]["images"][0]["name"], cid)
        self.assertEqual(
            decode_att(data["message"]["images"][0]["content"]), image_data
        )
        # Make sure neither the html nor the inline image is treated as an attachment:
        self.assertFalse("attachments" in data["message"])

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        # option 1: attach as a file:
        self.message.attach_file(image_path)

        # option 2: construct the MIMEImage and attach it directly:
        image = MIMEImage(image_data)
        self.message.attach(image)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["message"]["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["type"], "image/png")
        self.assertEqual(attachments[0]["name"], image_filename)
        self.assertEqual(decode_att(attachments[0]["content"]), image_data)
        self.assertEqual(attachments[1]["type"], "image/png")
        self.assertEqual(attachments[1]["name"], "")  # unknown -- not attached as file
        self.assertEqual(decode_att(attachments[1]["content"]), image_data)
        # Make sure the image attachments are not treated as embedded:
        self.assertFalse("images" in data["message"])

    def test_multiple_html_alternatives(self):
        # Multiple alternatives not allowed
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

    def test_api_failure(self):
        self.set_mock_response(status_code=400)
        with self.assertRaisesMessage(AnymailAPIError, "Mandrill API response 400"):
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])

        # Make sure fail_silently is respected
        self.set_mock_response(status_code=400)
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            fail_silently=True,
        )
        self.assertEqual(sent, 0)

    def test_api_error_includes_details(self):
        """AnymailAPIError should include ESP's error message"""
        self.set_mock_response(
            status_code=400,
            raw=b"""{
             "status": "error",
             "code": 12,
             "name": "Error_Name",
             "message": "Helpful explanation from Mandrill"
        }""",
        )
        with self.assertRaisesMessage(
            AnymailAPIError, "Helpful explanation from Mandrill"
        ):
            self.message.send()

        # Non-JSON error response:
        self.set_mock_response(status_code=500, raw=b"Invalid API key")
        with self.assertRaisesMessage(AnymailAPIError, "Invalid API key"):
            self.message.send()

        # No content in the error response:
        self.set_mock_response(status_code=502, raw=None)
        with self.assertRaises(AnymailAPIError):
            self.message.send()


@tag("mandrill")
class MandrillBackendAnymailFeatureTests(MandrillBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "anything@bounces.example.com"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["return_path_domain"], "bounces.example.com")

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["metadata"], {"user_id": "12345", "items": 6})

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        with override_current_timezone(utc_plus_6):
            # Timezone-naive datetime assumed to be Django current_timezone
            self.message.send_at = datetime(2022, 10, 11, 12, 13, 14, 567)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["send_at"], "2022-10-11 06:13:14"
            )  # 12:13 UTC+6 == 06:13 UTC

            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["send_at"], "2016-03-04 13:06:07"
            )  # 05:06 UTC-8 == 13:06 UTC

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["send_at"], "2022-10-21 18:00:00"
            )  # 00:00 UTC+6 == 18:00-1d UTC

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["send_at"], "2022-05-06 07:08:09")

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "2013-11-12 01:02:03"
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["send_at"], "2013-11-12 01:02:03")

    def test_tags(self):
        self.message.tags = ["receipt", "repeat-user"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["tags"], ["receipt", "repeat-user"])

    def test_tracking(self):
        # Test one way...
        self.message.track_opens = True
        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["track_opens"], True)
        self.assertEqual(data["message"]["track_clicks"], False)

        # ...and the opposite way
        self.message.track_opens = False
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["track_opens"], False)
        self.assertEqual(data["message"]["track_clicks"], True)

    def test_template_id(self):
        self.message.template_id = "welcome_template"
        self.message.send()
        data = self.get_api_call_json()
        # template requires different send API:
        self.assert_esp_called("/messages/send-template.json")
        self.assertEqual(data["template_name"], "welcome_template")
        # Mandrill requires template_content with send-template:
        self.assertEqual(data["template_content"], [])

    def test_merge_data(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        # Mandrill template_id is not required to use merge.
        # You can just supply template content as the message (e.g.):
        self.message.body = "Hi *|name|*. Welcome to *|group|* at *|site|*."
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice", "group": "Developers"},
            "bob@example.com": {"name": "Bob"},  # and leave :group undefined
        }
        self.message.merge_global_data = {
            "group": "Users",
            "site": "ExampleCo",
        }
        self.message.send()
        # didn't specify template_id, so use normal send:
        self.assert_esp_called("/messages/send.json")
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["message"]["merge_vars"],
            [
                {
                    "rcpt": "alice@example.com",
                    "vars": [
                        {"name": "group", "content": "Developers"},
                        {"name": "name", "content": "Alice"},
                    ],
                },
                {
                    "rcpt": "bob@example.com",
                    "vars": [{"name": "name", "content": "Bob"}],
                },
            ],
        )
        self.assertCountEqual(
            data["message"]["global_merge_vars"],
            [
                {"name": "group", "content": "Users"},
                {"name": "site", "content": "ExampleCo"},
            ],
        )
        # merge_data implies batch:
        self.assertIs(data["message"]["preserve_recipients"], False)

    def test_merge_metadata(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.merge_metadata = {
            "alice@example.com": {"order_id": 123, "tier": "premium"},
            "bob@example.com": {"order_id": 678},
        }
        self.message.metadata = {"notification_batch": "zx912"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["message"]["recipient_metadata"],
            [
                {
                    "rcpt": "alice@example.com",
                    "values": {"order_id": 123, "tier": "premium"},
                },
                {
                    "rcpt": "bob@example.com",
                    "values": {"order_id": 678},
                },
            ],
        )
        # merge_metadata implies batch:
        self.assertIs(data["message"]["preserve_recipients"], False)

    def test_missing_from(self):
        """Make sure a missing from_email omits from* from API call.

        (Allows use of from email/name from template)
        """
        # You must set from_email=None after constructing the EmailMessage
        # (or you will end up with Django's settings.DEFAULT_FROM_EMAIL instead)
        self.message.from_email = None
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("from_email", data["message"])
        self.assertNotIn("from_name", data["message"])

    def test_missing_subject(self):
        """Make sure a missing subject omits subject from API call.

        (Allows use of template subject)
        """
        self.message.subject = None
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("subject", data["message"])

    def test_esp_extra(self):
        self.message.esp_extra = {
            # Mandrill send param that goes at top level of API payload:
            "ip_pool": "Bulk Pool",
            "message": {
                # param that goes within message dict:
                "subaccount": "Marketing Dept."
            },
        }
        self.message.tags = ["test-tag"]  # make sure non-esp_extra params are merged
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["ip_pool"], "Bulk Pool")
        self.assertEqual(data["message"]["subaccount"], "Marketing Dept.")
        self.assertEqual(data["message"]["tags"], ["test-tag"])

    def test_esp_extra_recipient_metadata(self):
        """Anymail allows pythonic recipient_metadata dict"""
        self.message.esp_extra = {
            "message": {
                "recipient_metadata": {
                    # Anymail expands simple python dicts into the more-verbose
                    # rcpt/values lists the Mandrill API uses
                    "customer@example.com": {"cust_id": "67890", "order_id": "54321"},
                    "guest@example.com": {"cust_id": "94107", "order_id": "43215"},
                }
            }
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["message"]["recipient_metadata"],
            [
                {
                    "rcpt": "customer@example.com",
                    "values": {"cust_id": "67890", "order_id": "54321"},
                },
                {
                    "rcpt": "guest@example.com",
                    "values": {"cust_id": "94107", "order_id": "43215"},
                },
            ],
        )

        # You can also just supply it in Mandrill's native form
        self.message.esp_extra = {
            "message": {
                "recipient_metadata": [
                    {
                        "rcpt": "customer@example.com",
                        "values": {"cust_id": "80806", "order_id": "70701"},
                    },
                    {
                        "rcpt": "guest@example.com",
                        "values": {"cust_id": "21212", "order_id": "10305"},
                    },
                ]
            }
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["message"]["recipient_metadata"],
            [
                {
                    "rcpt": "customer@example.com",
                    "values": {"cust_id": "80806", "order_id": "70701"},
                },
                {
                    "rcpt": "guest@example.com",
                    "values": {"cust_id": "21212", "order_id": "10305"},
                },
            ],
        )

    def test_esp_extra_template_content(self):
        """Anymail allows pythonic template_content dict"""
        self.message.template_id = (
            "welcome_template"  # forces send-template API and default template_content
        )
        self.message.esp_extra = {
            "template_content": {
                # Anymail expands simple python dicts into the more-verbose name/content
                # structures the Mandrill API uses
                "HEADLINE": "<h1>Specials Just For *|FNAME|*</h1>",
                "OFFER_BLOCK": "<p><em>Half off</em> all fruit</p>",
            }
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["template_content"],
            [
                {"name": "HEADLINE", "content": "<h1>Specials Just For *|FNAME|*</h1>"},
                {
                    "name": "OFFER_BLOCK",
                    "content": "<p><em>Half off</em> all fruit</p>",
                },
            ],
        )

        # You can also just supply it in Mandrill's native form
        self.message.esp_extra = {
            "template_content": [
                {
                    "name": "HEADLINE",
                    "content": "<h1>Exciting offers for *|FNAME|*</h1>",
                },
                {"name": "OFFER_BLOCK", "content": "<p><em>25% off</em> all fruit</p>"},
            ]
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["template_content"],
            [
                {
                    "name": "HEADLINE",
                    "content": "<h1>Exciting offers for *|FNAME|*</h1>",
                },
                {"name": "OFFER_BLOCK", "content": "<p><em>25% off</em> all fruit</p>"},
            ],
        )

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        self.assert_esp_called("/messages/send.json")
        data = self.get_api_call_json()
        self.assertNotIn("global_merge_vars", data["message"])
        self.assertNotIn("merge_vars", data["message"])
        self.assertNotIn("metadata", data["message"])
        self.assertNotIn("send_at", data)
        self.assertNotIn("tags", data["message"])
        self.assertNotIn("template_content", data["message"])
        self.assertNotIn("template_name", data["message"])
        self.assertNotIn("track_clicks", data["message"])
        self.assertNotIn("track_opens", data["message"])

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        response_content = (
            b'[{"email": "to1@example.com", "status": "sent", "_id": "abc123"}]'
        )
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"sent"})
        self.assertEqual(msg.anymail_status.message_id, "abc123")
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "sent"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id, "abc123"
        )
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    # noinspection PyUnresolvedReferences
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
        self.message.metadata = {"total": Decimal("19.99")}
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
            print(self.get_api_call_data())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to Mandrill", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")

    def test_no_extraneous_fields(self):
        """Don't send empty fields that have no effect on sending"""
        mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])
        data = self.get_api_call_json()
        # Simple send should contain exactly this, nothing more:
        self.assertEqual(
            data,
            {
                "key": "test_api_key",
                "message": {
                    "from_email": "from@example.com",
                    "to": [{"email": "to@example.com", "type": "to"}],
                    "subject": "Subject",
                    "text": "Body",
                },
            },
        )


@tag("mandrill")
class MandrillBackendRecipientsRefusedTests(MandrillBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid
    """

    def test_recipients_refused(self):
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["invalid@localhost", "reject@test.mandrillapp.com"],
        )
        self.set_mock_response(
            raw=b"""[
            {"email": "invalid@localhost", "status": "invalid"},
            {"email": "reject@test.mandrillapp.com", "status": "rejected"}
        ]"""
        )
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_response(
            raw=b"""[
            {"email": "invalid@localhost", "status": "invalid"},
            {"email": "reject@test.mandrillapp.com", "status": "rejected"}
        ]"""
        )
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["invalid@localhost", "reject@test.mandrillapp.com"],
            fail_silently=True,
        )
        self.assertEqual(sent, 0)

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            [
                "invalid@localhost",
                "valid@example.com",
                "reject@test.mandrillapp.com",
                "also.valid@example.com",
            ],
        )
        self.set_mock_response(
            raw=b"""[
            {"email": "invalid@localhost", "status": "invalid"},
            {"email": "valid@example.com", "status": "sent"},
            {"email": "reject@test.mandrillapp.com", "status": "rejected"},
            {"email": "also.valid@example.com", "status": "queued"}
        ]"""
        )
        sent = msg.send()
        # one message sent, successfully, to 2 of 4 recipients:
        self.assertEqual(sent, 1)
        status = msg.anymail_status
        self.assertEqual(status.recipients["invalid@localhost"].status, "invalid")
        self.assertEqual(status.recipients["valid@example.com"].status, "sent")
        self.assertEqual(
            status.recipients["reject@test.mandrillapp.com"].status, "rejected"
        )
        self.assertEqual(status.recipients["also.valid@example.com"].status, "queued")

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)
    def test_settings_override(self):
        """No exception with ignore setting"""
        self.set_mock_response(
            raw=b"""[
            {"email": "invalid@localhost", "status": "invalid"},
            {"email": "reject@test.mandrillapp.com", "status": "rejected"}
        ]"""
        )
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["invalid@localhost", "reject@test.mandrillapp.com"],
        )
        self.assertEqual(sent, 1)  # refused message is included in sent count


@tag("mandrill")
class MandrillBackendSessionSharingTestCase(
    SessionSharingTestCases, MandrillBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mandrill")
@override_settings(EMAIL_BACKEND="anymail.backends.mandrill.EmailBackend")
class MandrillBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test backend without required settings"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bMANDRILL_API_KEY\b")
        self.assertRegex(errmsg, r"\bANYMAIL_MANDRILL_API_KEY\b")
