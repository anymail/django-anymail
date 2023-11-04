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
    AnymailInvalidAddress,
    AnymailRecipientsRefused,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import AnymailMessage, attach_inline_image_file

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
        self.assert_esp_called("send/")
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
            reply_to=["reply@example.com", "Other <reply2@example.com>"]
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["replyto"], "reply@example.com, Other <reply2@example.com>"
        )

# TODO: Attachment tests, AnymailFeaturesTests

@tag("mailpace")
class MailPaceBackendRecipientsRefusedTests(MailPaceBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid
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
