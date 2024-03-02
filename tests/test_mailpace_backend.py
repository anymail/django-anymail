from base64 import b64encode

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import (
    AnymailAPIError,
    AnymailRecipientsRefused,
    AnymailRequestsAPIError,
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


@tag("mailpace")
@override_settings(
    EMAIL_BACKEND="anymail.backends.mailpace.EmailBackend",
    ANYMAIL={"MAILPACE_SERVER_TOKEN": "test_server_token"},
)
class MailPaceBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "id": 123,
        "status": "queued"
    }"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("mailpace")
class MailPaceBackendStandardEmailTests(MailPaceBackendMockAPITestCase):
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
        self.assert_esp_called("https://app.mailpace.com/api/v1/send")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["MailPace-Server-Token"], "test_server_token")
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["textbody"], "Here is the message.")
        self.assertEqual(data["from"], "from@sender.example.com")
        self.assertEqual(data["to"], "to@example.com")

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
        self.assertEqual(data["to"], "Recipient #1 <to1@example.com>, to2@example.com")
        self.assertEqual(data["cc"], "Carbon Copy <cc1@example.com>, cc2@example.com")
        self.assertEqual(data["bcc"], "Blind Copy <bcc1@example.com>, bcc2@example.com")

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
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject")
        self.assertEqual(data["textbody"], "Body goes here")
        self.assertEqual(data["from"], "from@example.com")
        self.assertEqual(data["to"], "to1@example.com, Also To <to2@example.com>")
        self.assertEqual(data["bcc"], "bcc1@example.com, Also BCC <bcc2@example.com>")
        self.assertEqual(data["cc"], "cc1@example.com, Also CC <cc2@example.com>")
        self.assertEqual(data["replyto"], "another@example.com")

    def test_html_message(self):
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["textbody"], text_content)
        self.assertEqual(data["htmlbody"], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn("Attachments", data)

    def test_html_only_message(self):
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMessage(
            "Subject", html_content, "from@example.com", ["to@example.com"]
        )
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        data = self.get_api_call_json()
        self.assertNotIn("textBody", data)
        self.assertEqual(data["htmlbody"], html_content)

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
            data["replyto"], "reply@example.com, Other <reply2@example.com>"
        )

    def test_sending_attachment(self):
        """Test sending attachments"""
        email = mail.EmailMessage(
            "Subject",
            "content",
            "from@example.com",
            ["to@example.com"],
            attachments=[
                ("file.txt", "file content", "text/plain"),
            ],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["attachments"],
            [
                {
                    "name": "file.txt",
                    "content": b64encode(b"file content").decode("ascii"),
                    "content_type": "text/plain",
                }
            ],
        )

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)  # Read from a png file
        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["htmlbody"], html_content)

        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["name"], image_filename)
        self.assertEqual(attachments[0]["content_type"], "image/png")
        self.assertEqual(decode_att(attachments[0]["content"]), image_data)
        self.assertEqual(attachments[0]["cid"], "cid:%s" % cid)

    def test_tag(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["tags"], "receipt")

    def test_tags(self):
        self.message.tags = ["receipt", "repeat-user"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["tags"], ["receipt", "repeat-user"])

    def test_invalid_response(self):
        """AnymailAPIError raised for non-json response"""
        self.set_mock_response(raw=b"not json")
        with self.assertRaises(AnymailRequestsAPIError):
            self.message.send()

    def test_invalid_success_response(self):
        """AnymailRequestsAPIError raised for success response with invalid json"""
        self.set_mock_response(raw=b"{}")  # valid json, but not a MailPace response
        with self.assertRaises(AnymailRequestsAPIError):
            self.message.send()

    def test_response_blocked_error(self):
        """AnymailRecipientsRefused raised for error response with MailPace blocked address"""
        self.set_mock_response(
            raw=b"""{
                "errors": {
                    "to": ["contains a blocked address"]
                }
            }""",
            status_code=400,
        )
        with self.assertRaises(AnymailRecipientsRefused):
            self.message.send()

    def test_response_maximum_address_error(self):
        """AnymailAPIError raised for error response with MailPace maximum address"""
        self.set_mock_response(
            raw=b"""{
                "errors": {
                    "to": ["number of email addresses exceeds maximum volume"]
                }
            }""",
            status_code=400,
        )
        with self.assertRaises(AnymailRecipientsRefused):
            self.message.send()


@tag("mailpace")
class MailPaceBackendRecipientsRefusedTests(MailPaceBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when any recipients are rejected or invalid
    """

    def test_recipients_invalid(self):
        self.set_mock_response(
            status_code=400,
            raw=b"""{"errors":{"to":["is invalid"]}}""",
        )
        msg = mail.EmailMessage(
            "Subject", "Body", "from@example.com", ["Invalid@LocalHost"]
        )
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients["Invalid@LocalHost"].status, "invalid")

    def test_from_email_invalid(self):
        self.set_mock_response(
            status_code=400,
            raw=b"""{"error":"Email from address not parseable"}""",
        )
        msg = mail.EmailMessage(
            "Subject", "Body", "invalid@localhost", ["to@example.com"]
        )
        with self.assertRaises(AnymailAPIError):
            msg.send()


@tag("mailpace")
class MailPaceBackendSessionSharingTestCase(
    SessionSharingTestCases, MailPaceBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mailpace")
@override_settings(EMAIL_BACKEND="anymail.backends.mailpace.EmailBackend")
class MailPaceBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bMAILPACE_SERVER_TOKEN\b")
        self.assertRegex(errmsg, r"\bANYMAIL_MAILPACE_SERVER_TOKEN\b")
