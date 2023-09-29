import json
from base64 import b64encode
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import (
    AnymailAPIError,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import attach_inline_image_file

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


@tag("resend")
@override_settings(
    EMAIL_BACKEND="anymail.backends.resend.EmailBackend",
    ANYMAIL={
        "RESEND_API_KEY": "test_api_key",
    },
)
class ResendBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b'{"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}'

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("resend")
class ResendBackendStandardEmailTests(ResendBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@sender.example.com",
            ["to@example.com"],
            fail_silently=False,
        )
        self.assert_esp_called("/emails")
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

    def test_quoted_display_names(self):
        # Resend's API has a bug that rejects a display-name in double quotes
        # (per RFC 5322 section 3.4). Attempting to omit the quotes works, unless
        # the display-name also contains a comma. Try to avoid the whole problem
        # by using RFC 2047 encoded words for addresses Resend will parse incorrectly.
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            '"From, comma" <from@example.com>',
            [
                '"To, comma" <to1@example.com>',
                "non–ascii <to2@example.com>",
                "=?utf-8?q?pre_encoded?= <to3@example.com>",
            ],
            reply_to=['"Reply, comma" <reply1@example.com>'],
        )
        msg.send()
        data = self.get_api_call_json()
        # TODO: Resend gives a "security error" for RFC 2047 in the 'from' param,
        #       so leave as is. (Will cause "invalid parameter" error in actual use.)
        # self.assertEqual(data["from"], "=?utf-8?q?From=2C_comma?= <from@example.com>")
        self.assertEqual(data["from"], '"From, comma" <from@example.com>')
        self.assertEqual(
            data["to"],
            [
                "=?utf-8?q?To=2C_comma?= <to1@example.com>",
                "=?utf-8?b?bm9u4oCTYXNjaWk=?= <to2@example.com>",
                "=?utf-8?q?pre_encoded?= <to3@example.com>",
            ],
        )
        self.assertEqual(
            data["reply_to"], ["=?utf-8?q?Reply=2C_comma?= <reply1@example.com>"]
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
        self.assertEqual(data["reply_to"], ["another@example.com"])
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
        self.assertCountEqual(data["headers"], {"X-Custom": "string", "X-Num": "123"})

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
            reply_to=["reply@example.com", "Other <reply2@example.com>"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["reply_to"], ["reply@example.com", "Other <reply2@example.com>"]
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
        pdf_content = b"PDF\xb4 pretend this is valid pdf data"
        mimeattachment = MIMEBase("application", "pdf")
        mimeattachment.set_payload(pdf_content)
        self.message.attach(mimeattachment)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["filename"], "test.txt")
        self.assertEqual(
            decode_att(attachments[0]["content"]).decode("ascii"), text_content
        )

        self.assertEqual(attachments[1]["filename"], "test.png")
        self.assertEqual(decode_att(attachments[1]["content"]), png_content)

        # unnamed attachment given default name with correct extension for content type
        self.assertEqual(attachments[2]["filename"], "attachment.pdf")
        self.assertEqual(decode_att(attachments[2]["content"]), pdf_content)

    def test_unicode_attachment_correctly_decoded(self):
        self.message.attach(
            "Une pièce jointe.html", "<p>\u2019</p>", mimetype="text/html"
        )
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["attachments"],
            [
                {
                    "filename": "Une pièce jointe.html",
                    "content": b64encode("<p>\u2019</p>".encode("utf-8")).decode(
                        "ascii"
                    ),
                }
            ],
        )

    def test_embedded_images(self):
        # Resend's API doesn't have a way to specify content-id
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)

        cid = attach_inline_image_file(self.message, image_path)  # Read from a png file
        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline content-id"):
            self.message.send()

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        # option 1: attach as a file
        self.message.attach_file(image_path)

        # option 2: construct the MIMEImage and attach it directly
        image = MIMEImage(image_data)
        self.message.attach(image)

        image_data_b64 = b64encode(image_data).decode("ascii")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["attachments"],
            [
                {
                    "filename": image_filename,  # the named one
                    "content": image_data_b64,
                },
                {
                    # For unnamed attachments, Anymail constructs a default name
                    # based on the content_type:
                    "filename": "attachment.png",
                    "content": image_data_b64,
                },
            ],
        )

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
        self.assertNotIn("reply_to", data)

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
            AnymailAPIError, r"Resend API response 400"
        ) as cm:
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])
        self.assertIn("API key is invalid", str(cm.exception))

        # Make sure fail_silently is respected
        self.set_mock_response(status_code=422, json_data=failure_response)
        sent = mail.send_mail(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            fail_silently=True,
        )
        self.assertEqual(sent, 0)


@tag("resend")
class ResendBackendAnymailFeatureTests(ResendBackendMockAPITestCase):
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
        self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt", "reorder test 12"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["headers"]["X-Tag"],
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
                "X-Tag": ["receipt", "reorder test 12"],
                "X-Metadata": '{"user_id": "12345"}',
            },
        )

    def test_track_opens(self):
        self.message.track_opens = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_opens"):
            self.message.send()

    def test_track_clicks(self):
        self.message.track_clicks = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_clicks"):
            self.message.send()

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
        self.assertNotIn("tags", data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            "tags": [{"name": "my_tag", "value": "my_tag_value"}],
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["tags"], [{"name": "my_tag", "value": "my_tag_value"}])

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
        self.assertEqual(
            msg.anymail_status.message_id, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(
            msg.anymail_status.esp_response.content, self.DEFAULT_RAW_RESPONSE
        )

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
        self.message.metadata = {"price": Decimal("19.99")}  # yeah, don't do this
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
            print(self.get_api_call_json())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to Resend", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("resend")
class ResendBackendRecipientsRefusedTests(ResendBackendMockAPITestCase):
    # Resend doesn't check email bounce or complaint lists at time of send --
    # it always just queues the message. You'll need to listen for the "rejected"
    # and "failed" events to detect refused recipients.
    pass


@tag("resend")
class ResendBackendSessionSharingTestCase(
    SessionSharingTestCases, ResendBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("resend")
@override_settings(EMAIL_BACKEND="anymail.backends.resend.EmailBackend")
class ResendBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bRESEND_API_KEY\b")
        self.assertRegex(errmsg, r"\bANYMAIL_RESEND_API_KEY\b")
