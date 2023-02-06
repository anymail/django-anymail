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


@tag("postmark")
@override_settings(
    EMAIL_BACKEND="anymail.backends.postmark.EmailBackend",
    ANYMAIL={"POSTMARK_SERVER_TOKEN": "test_server_token"},
)
class PostmarkBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "To": "to@example.com",
        "SubmittedAt": "2016-03-12T15:27:50.4468803-05:00",
        "MessageID": "b4007d94-33f1-4e78-a783-97417d6c80e6",
        "ErrorCode":0,
        "Message":"OK"
    }"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("postmark")
class PostmarkBackendStandardEmailTests(PostmarkBackendMockAPITestCase):
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
        self.assert_esp_called("/email")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-Postmark-Server-Token"], "test_server_token")
        data = self.get_api_call_json()
        self.assertEqual(data["Subject"], "Subject here")
        self.assertEqual(data["TextBody"], "Here is the message.")
        self.assertEqual(data["From"], "from@sender.example.com")
        self.assertEqual(data["To"], "to@example.com")

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
        self.assertEqual(data["From"], "From Name <from@example.com>")
        self.assertEqual(data["To"], "Recipient #1 <to1@example.com>, to2@example.com")
        self.assertEqual(data["Cc"], "Carbon Copy <cc1@example.com>, cc2@example.com")
        self.assertEqual(data["Bcc"], "Blind Copy <bcc1@example.com>, bcc2@example.com")

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
                # should override backend msgid:
                "Message-ID": "mycustommsgid@sales.example.com",
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Subject"], "Subject")
        self.assertEqual(data["TextBody"], "Body goes here")
        self.assertEqual(data["From"], "from@example.com")
        self.assertEqual(data["To"], "to1@example.com, Also To <to2@example.com>")
        self.assertEqual(data["Bcc"], "bcc1@example.com, Also BCC <bcc2@example.com>")
        self.assertEqual(data["Cc"], "cc1@example.com, Also CC <cc2@example.com>")
        self.assertEqual(data["ReplyTo"], "another@example.com")
        self.assertCountEqual(
            data["Headers"],
            [
                {"Name": "Message-ID", "Value": "mycustommsgid@sales.example.com"},
                {"Name": "X-MyHeader", "Value": "my value"},
            ],
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
        self.assertEqual(data["TextBody"], text_content)
        self.assertEqual(data["HtmlBody"], html_content)
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
        self.assertNotIn("TextBody", data)
        self.assertEqual(data["HtmlBody"], html_content)

    def test_extra_headers(self):
        self.message.extra_headers = {"X-Custom": "string", "X-Num": 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["Headers"],
            [{"Name": "X-Custom", "Value": "string"}, {"Name": "X-Num", "Value": 123}],
        )

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
            headers={"X-Other": "Keep"},
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["ReplyTo"], "reply@example.com, Other <reply2@example.com>"
        )
        # don't lose other headers:
        self.assertEqual(data["Headers"], [{"Name": "X-Other", "Value": "Keep"}])

    def test_reply_to_header(self):
        # Reply-To needs to be moved out of headers, into dedicated param
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            headers={
                "reply-to": "reply@example.com, Other <reply2@example.com>",
                "X-Other": "Keep",
            },
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["ReplyTo"], "reply@example.com, Other <reply2@example.com>"
        )
        # don't lose other headers:
        self.assertEqual(data["Headers"], [{"Name": "X-Other", "Value": "Keep"}])

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
        attachments = data["Attachments"]
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["Name"], "test.txt")
        self.assertEqual(attachments[0]["ContentType"], "text/plain")
        self.assertEqual(
            decode_att(attachments[0]["Content"]).decode("ascii"), text_content
        )
        self.assertNotIn("ContentID", attachments[0])

        # ContentType inferred from filename:
        self.assertEqual(attachments[1]["ContentType"], "image/png")
        self.assertEqual(attachments[1]["Name"], "test.png")
        self.assertEqual(decode_att(attachments[1]["Content"]), png_content)
        # make sure image not treated as inline:
        self.assertNotIn("ContentID", attachments[1])

        self.assertEqual(attachments[2]["ContentType"], "application/pdf")
        self.assertEqual(attachments[2]["Name"], "")  # none
        self.assertEqual(decode_att(attachments[2]["Content"]), pdf_content)
        self.assertNotIn("ContentID", attachments[2])

    def test_unicode_attachment_correctly_decoded(self):
        self.message.attach(
            "Une pièce jointe.html", "<p>\u2019</p>", mimetype="text/html"
        )
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["Attachments"],
            [
                {
                    "Name": "Une pièce jointe.html",
                    "ContentType": "text/html",
                    "Content": b64encode("<p>\u2019</p>".encode("utf-8")).decode(
                        "ascii"
                    ),
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
        self.assertEqual(data["HtmlBody"], html_content)

        attachments = data["Attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["Name"], image_filename)
        self.assertEqual(attachments[0]["ContentType"], "image/png")
        self.assertEqual(decode_att(attachments[0]["Content"]), image_data)
        self.assertEqual(attachments[0]["ContentID"], "cid:%s" % cid)

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
            data["Attachments"],
            [
                {
                    "Name": image_filename,  # the named one
                    "ContentType": "image/png",
                    "Content": image_data_b64,
                },
                {
                    "Name": "",  # the unnamed one
                    "ContentType": "image/png",
                    "Content": image_data_b64,
                },
            ],
        )

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

    def test_suppress_empty_address_lists(self):
        """Empty to, cc, bcc, and reply_to shouldn't generate empty fields"""
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("Cc", data)
        self.assertNotIn("Bcc", data)
        self.assertNotIn("ReplyTo", data)

        # Test empty `to`--but send requires at least one recipient somewhere (like cc)
        self.message.to = []
        self.message.cc = ["cc@example.com"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("To", data)

    def test_multiple_from_emails(self):
        """
        Postmark accepts multiple addresses in from_email (though only uses the first)
        """
        self.message.from_email = 'first@example.com, "From, also" <second@example.com>'
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["From"], 'first@example.com, "From, also" <second@example.com>'
        )

        # Make sure the far-more-likely scenario of a single from_email
        # with an unquoted display-name issues a reasonable error:
        self.message.from_email = "Unquoted, display-name <from@example.com>"
        with self.assertRaises(AnymailInvalidAddress):
            self.message.send()

    def test_api_failure(self):
        self.set_mock_response(status_code=500)
        with self.assertRaisesMessage(AnymailAPIError, "Postmark API response 500"):
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])

        # Make sure fail_silently is respected
        self.set_mock_response(status_code=500)
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
        # JSON error response:
        error_response = b"""{
            "ErrorCode": 451,
            "Message": "Helpful explanation from Postmark."
        }"""
        self.set_mock_response(status_code=200, raw=error_response)
        with self.assertRaisesMessage(
            AnymailAPIError, "Helpful explanation from Postmark"
        ):
            self.message.send()

        # Non-JSON error response:
        self.set_mock_response(status_code=500, raw=b"Ack! Bad proxy!")
        with self.assertRaisesMessage(AnymailAPIError, "Ack! Bad proxy!"):
            self.message.send()

        # No content in the error response:
        self.set_mock_response(status_code=502, raw=None)
        with self.assertRaises(AnymailAPIError):
            self.message.send()


@tag("postmark")
class PostmarkBackendAnymailFeatureTests(PostmarkBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        # Postmark doesn't allow overriding envelope sender on individual messages.
        # You can configure a custom return-path domain for each server in their
        # control panel.
        self.message.envelope_sender = "anything@bounces.example.com"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "envelope_sender"):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Metadata"], {"user_id": "12345", "items": 6})

    def test_send_at(self):
        self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Tag"], "receipt")

        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple tags"):
            self.message.send()

    def test_track_opens(self):
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["TrackOpens"], True)

    def test_track_clicks(self):
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["TrackLinks"], "HtmlAndText")

        # Also explicit "None" for False (to override server default)
        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["TrackLinks"], "None")

    def test_template(self):
        message = AnymailMessage(
            # Omit subject and body (Postmark prohibits them with templates)
            from_email="from@example.com",
            to=["to@example.com"],
            template_id=1234567,
            merge_global_data={"name": "Alice", "group": "Developers"},
        )
        message.send()
        self.assert_esp_called("/email/withTemplate/")
        data = self.get_api_call_json()
        self.assertEqual(data["TemplateId"], 1234567)
        self.assertEqual(
            data["TemplateModel"], {"name": "Alice", "group": "Developers"}
        )
        # Make sure Django default subject and body didn't end up in the payload:
        self.assertNotIn("Subject", data)
        self.assertNotIn("HtmlBody", data)
        self.assertNotIn("TextBody", data)

    def test_template_alias(self):
        # Anymail template_id can be either Postmark TemplateId or TemplateAlias
        message = AnymailMessage(
            from_email="from@example.com",
            to=["to@example.com"],
            template_id="welcome-message",
        )
        message.send()
        self.assert_esp_called("/email/withTemplate/")
        data = self.get_api_call_json()
        self.assertEqual(data["TemplateAlias"], "welcome-message")
        # Postmark requires TemplateModel (can be empty) with TemplateId/TemplateAlias
        self.assertEqual(data["TemplateModel"], {})

    def test_template_multiple_recipients(self):
        # This is a non-batch (no merge_data) template send
        message = AnymailMessage(
            from_email="from@example.com",
            to=["to@example.com", "Also to <to2@example.com>"],
            template_id=1234567,
        )
        message.send()
        self.assert_esp_called("/email/withTemplate/")
        data = self.get_api_call_json()
        self.assertEqual(data["To"], "to@example.com, Also to <to2@example.com>")
        self.assertEqual(data["TemplateId"], 1234567)

    _mock_batch_response = json.dumps(
        [
            {
                "ErrorCode": 0,
                "Message": "OK",
                "To": "alice@example.com",
                "SubmittedAt": "2016-03-12T15:27:50.4468803-05:00",
                "MessageID": "b7bc2f4a-e38e-4336-af7d-e6c392c2f817",
            },
            {
                "ErrorCode": 0,
                "Message": "OK",
                "To": "bob@example.com",
                "SubmittedAt": "2016-03-12T15:27:50.4468803-05:00",
                "MessageID": "e2ecbbfc-fe12-463d-b933-9fe22915106d",
            },
        ]
    ).encode("utf-8")

    def test_merge_data(self):
        self.set_mock_response(raw=self._mock_batch_response)
        message = AnymailMessage(
            from_email="from@example.com",
            # Postmark only supports merge_data content in a template
            template_id=1234567,
            to=["alice@example.com", "Bob <bob@example.com>"],
            merge_data={
                "alice@example.com": {"name": "Alice", "group": "Developers"},
                "bob@example.com": {"name": "Bob"},  # and leave group undefined
                "nobody@example.com": {"name": "Not a recipient for this message"},
            },
            merge_global_data={"group": "Users", "site": "ExampleCo"},
        )
        message.send()

        self.assert_esp_called("/email/batchWithTemplates")
        data = self.get_api_call_json()
        messages = data["Messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(
            messages[0],
            {
                "From": "from@example.com",
                "To": "alice@example.com",
                "TemplateId": 1234567,
                "TemplateModel": {
                    "name": "Alice",
                    "group": "Developers",
                    "site": "ExampleCo",
                },
            },
        )
        self.assertEqual(
            messages[1],
            {
                "From": "from@example.com",
                "To": "Bob <bob@example.com>",
                "TemplateId": 1234567,
                "TemplateModel": {"name": "Bob", "group": "Users", "site": "ExampleCo"},
            },
        )

        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["alice@example.com"].status, "sent")
        self.assertEqual(
            recipients["alice@example.com"].message_id,
            "b7bc2f4a-e38e-4336-af7d-e6c392c2f817",
        )
        self.assertEqual(recipients["bob@example.com"].status, "sent")
        self.assertEqual(
            recipients["bob@example.com"].message_id,
            "e2ecbbfc-fe12-463d-b933-9fe22915106d",
        )

    def test_merge_data_single_recipient(self):
        self.set_mock_response(raw=self._mock_batch_response)
        message = AnymailMessage(
            from_email="from@example.com",
            # Postmark only supports merge_data content in a template:
            template_id=1234567,
            to=["alice@example.com"],
            merge_data={
                "alice@example.com": {"name": "Alice", "group": "Developers"},
                "nobody@example.com": {"name": "Not a recipient for this message"},
            },
            merge_global_data={"group": "Users", "site": "ExampleCo"},
        )
        message.send()

        # because merge_data is set, it's treated as a batch send
        self.assert_esp_called("/email/batchWithTemplates")
        data = self.get_api_call_json()

        self.assertEqual(
            data,
            {
                "Messages": [
                    {
                        "From": "from@example.com",
                        "To": "alice@example.com",
                        "TemplateId": 1234567,
                        "TemplateModel": {
                            "name": "Alice",
                            "group": "Developers",
                            "site": "ExampleCo",
                        },
                    }
                ]
            },
        )

        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["alice@example.com"].status, "sent")
        self.assertEqual(
            recipients["alice@example.com"].message_id,
            "b7bc2f4a-e38e-4336-af7d-e6c392c2f817",
        )

    def test_merge_data_no_template(self):
        # merge_data={} can be used to force batch sending without a template
        self.set_mock_response(raw=self._mock_batch_response)
        message = AnymailMessage(
            from_email="from@example.com",
            to=["alice@example.com", "Bob <bob@example.com>"],
            merge_data={},
            subject="Test batch send",
            body="Test body",
        )
        message.send()

        self.assert_esp_called("/email/batch")
        data = self.get_api_call_json()
        self.assertEqual(len(data), 2)
        self.assertEqual(
            data[0],
            {
                "From": "from@example.com",
                "To": "alice@example.com",
                "Subject": "Test batch send",
                "TextBody": "Test body",
            },
        )
        self.assertEqual(
            data[1],
            {
                "From": "from@example.com",
                "To": "Bob <bob@example.com>",
                "Subject": "Test batch send",
                "TextBody": "Test body",
            },
        )

        recipients = message.anymail_status.recipients
        self.assertEqual(recipients["alice@example.com"].status, "sent")
        self.assertEqual(
            recipients["alice@example.com"].message_id,
            "b7bc2f4a-e38e-4336-af7d-e6c392c2f817",
        )
        self.assertEqual(recipients["bob@example.com"].status, "sent")
        self.assertEqual(
            recipients["bob@example.com"].message_id,
            "e2ecbbfc-fe12-463d-b933-9fe22915106d",
        )

    def test_merge_metadata(self):
        self.set_mock_response(raw=self._mock_batch_response)
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.merge_metadata = {
            "alice@example.com": {"order_id": 123, "tier": "premium"},
            "bob@example.com": {"order_id": 678},
        }
        self.message.metadata = {"notification_batch": "zx912"}
        self.message.send()

        self.assert_esp_called("/email/batch")
        data = self.get_api_call_json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["To"], "alice@example.com")
        # metadata and merge_metadata[recipient] are combined:
        self.assertEqual(
            data[0]["Metadata"],
            {"order_id": 123, "tier": "premium", "notification_batch": "zx912"},
        )
        self.assertEqual(data[1]["To"], "Bob <bob@example.com>")
        self.assertEqual(
            data[1]["Metadata"], {"order_id": 678, "notification_batch": "zx912"}
        )

    def test_merge_metadata_with_template(self):
        self.set_mock_response(raw=self._mock_batch_response)
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.template_id = 1234567
        self.message.merge_metadata = {
            "alice@example.com": {"order_id": 123},
            "bob@example.com": {"order_id": 678, "tier": "premium"},
        }
        self.message.send()

        self.assert_esp_called("/email/batchWithTemplates")
        data = self.get_api_call_json()
        messages = data["Messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["To"], "alice@example.com")
        # metadata and merge_metadata[recipient] are combined:
        self.assertEqual(messages[0]["Metadata"], {"order_id": 123})
        self.assertEqual(messages[1]["To"], "Bob <bob@example.com>")
        self.assertEqual(messages[1]["Metadata"], {"order_id": 678, "tier": "premium"})

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("Metadata", data)
        self.assertNotIn("Tag", data)
        self.assertNotIn("TemplateId", data)
        self.assertNotIn("TemplateModel", data)
        self.assertNotIn("TrackOpens", data)
        self.assertNotIn("TrackLinks", data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            "FuturePostmarkOption": "some-value",
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["FuturePostmarkOption"], "some-value")

    def test_message_server_token(self):
        # Can override server-token on a per-message basis:
        self.message.esp_extra = {
            "server_token": "token_for_this_message_only",
        }
        self.message.send()
        headers = self.get_api_call_headers()
        self.assertEqual(
            headers["X-Postmark-Server-Token"], "token_for_this_message_only"
        )
        data = self.get_api_call_json()
        self.assertNotIn("server_token", data)  # not in the json

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        response_content = b"""{
            "MessageID":"abcdef01-2345-6789-0123-456789abcdef",
            "ErrorCode":0,
            "To":"Recipient <to1@example.com>",
            "Message":"OK"
        }"""
        self.set_mock_response(raw=response_content)
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
            msg.anymail_status.message_id, "abcdef01-2345-6789-0123-456789abcdef"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "sent"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "abcdef01-2345-6789-0123-456789abcdef",
        )
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    # noinspection PyUnresolvedReferences
    def test_send_without_to_attaches_anymail_status(self):
        """The anymail_status should be attached even if there are no `to` recipients"""
        # Despite Postmark's docs, the "To" field is *not* required
        # if cc or bcc is provided.
        response_content = b"""{
            "SubmittedAt": "2019-01-28T13:54:35.5813997-05:00",
            "MessageID":"abcdef01-2345-6789-0123-456789abcdef",
            "ErrorCode":0,
            "Message":"OK"
        }"""
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            cc=["cc@example.com"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"sent"})
        self.assertEqual(
            msg.anymail_status.message_id, "abcdef01-2345-6789-0123-456789abcdef"
        )
        self.assertEqual(msg.anymail_status.recipients["cc@example.com"].status, "sent")
        self.assertEqual(
            msg.anymail_status.recipients["cc@example.com"].message_id,
            "abcdef01-2345-6789-0123-456789abcdef",
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
        self.message.tags = [Decimal("19.99")]  # yeah, don't do this
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
            print(self.get_api_call_json())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to Postmark", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("postmark")
class PostmarkBackendRecipientsRefusedTests(PostmarkBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid
    """

    def test_recipients_inactive(self):
        self.set_mock_response(
            status_code=422,
            raw=b'{"ErrorCode":406,'
            b'"Message":"You tried to send to a recipient'
            b" that has been marked as inactive.\\n"
            b"Found inactive addresses: hardbounce@example.com, spam@example.com.\\n"
            b"Inactive recipients are ones that have generated"
            b' a hard bounce or a spam complaint."}',
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["HardBounce@example.com", "Hates Spam <spam@example.com>"],
        )
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients["HardBounce@example.com"].status, "rejected")
        self.assertEqual(status.recipients["spam@example.com"].status, "rejected")

    def test_recipients_invalid(self):
        self.set_mock_response(
            status_code=422,
            raw=b"""{
                "ErrorCode":300,
                "Message":"Invalid 'To' address: 'invalid@localhost'."
            }""",
        )
        msg = mail.EmailMessage(
            "Subject", "Body", "from@example.com", ["Invalid@LocalHost"]
        )
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients["Invalid@LocalHost"].status, "invalid")

    def test_recipients_parse_error(self):
        self.set_mock_response(
            status_code=422,
            raw=b"""{
              "ErrorCode": 300,
              "Message": "Error parsing 'Cc': Illegal email domain '+' in address 'user@+'."
            }""",  # NOQA: E501
        )
        msg = mail.EmailMessage("Subject", "Body", "from@example.com", cc=["user@+"])
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients["user@+"].status, "invalid")

    def test_from_email_invalid(self):
        # Invalid 'From' address generates same Postmark ErrorCode 300 as invalid 'To',
        # but should raise a different Anymail error
        self.set_mock_response(
            status_code=422,
            raw=b"""{
                "ErrorCode":300,
                "Message":"Invalid 'From' address: 'invalid@localhost'."
            }""",
        )
        msg = mail.EmailMessage(
            "Subject", "Body", "invalid@localhost", ["to@example.com"]
        )
        with self.assertRaises(AnymailAPIError):
            msg.send()

    def test_reply_to_invalid(self):
        # Make sure 'Reply-To' error doesn't get caught in invalid 'To' logic:
        self.set_mock_response(
            status_code=422,
            raw=b"""{
                "ErrorCode": 300,
                "Message": "Error parsing 'Reply-To': Illegal email domain '+' in address 'invalid@+'."}
            """,  # NOQA: E501
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["to@example.com"],
            reply_to=["invalid@+"],
        )
        with self.assertRaisesMessage(AnymailAPIError, "Error parsing 'Reply-To'"):
            msg.send()

    def test_errorcode_300(self):
        # Various other problems generate same Postmark ErrorCode 300 as invalid 'To',
        # but should raise ordinary API errors
        self.set_mock_response(
            status_code=422,
            raw=b"""{
                "ErrorCode": 300,
                "Message": "Invalid metadata content. Field names are limited to 20 characters..."
            }""",  # NOQA: E501
        )
        msg = mail.EmailMessage(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )
        msg.metadata = {"this-key-name-is-too-long": "data"}
        with self.assertRaisesMessage(AnymailAPIError, "Invalid metadata content"):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_response(
            status_code=422,
            raw=b'{"ErrorCode":406,'
            b'"Message":"You tried to send to a recipient'
            b" that has been marked as inactive.\\n"
            b"Found inactive addresses: hardbounce@example.com, spam@example.com.\\n"
            b"Inactive recipients are ones that have generated"
            b' a hard bounce or a spam complaint."}',
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["HardBounce@example.com", "Hates Spam <spam@example.com>"],
        )
        msg.send(fail_silently=True)
        status = msg.anymail_status
        self.assertEqual(status.recipients["HardBounce@example.com"].status, "rejected")
        self.assertEqual(status.recipients["spam@example.com"].status, "rejected")

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)
    def test_ignore_recipient_status(self):
        self.set_mock_response(
            status_code=422,
            raw=b'{"ErrorCode":406,'
            b'"Message":"You tried to send to a recipient'
            b" that has been marked as inactive.\\n"
            b"Found inactive addresses: hardbounce@example.com, spam@example.com.\\n"
            b"Inactive recipients are ones that have generated"
            b' a hard bounce or a spam complaint. "}',
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            ["HardBounce@example.com", "Hates Spam <spam@example.com>"],
        )
        msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients["HardBounce@example.com"].status, "rejected")
        self.assertEqual(status.recipients["spam@example.com"].status, "rejected")

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        self.set_mock_response(
            status_code=200,
            raw=b'{"To":"hardbounce@example.com, valid@example.com,'
            b' Hates Spam <spam@example.com>",'
            b'"SubmittedAt":"2016-03-12T22:59:06.2505871-05:00",'
            b'"MessageID":"089dce03-feee-408e-9f0c-ee69bf1c5f35",'
            b'"ErrorCode":0,'
            b'"Message":"Message OK, but will not deliver to these inactive addresses:'
            b" hardbounce@example.com, spam@example.com."
            b" Inactive recipients are ones that have generated"
            b' a hard bounce or a spam complaint."}',
        )
        msg = mail.EmailMessage(
            "Subject",
            "Body",
            "from@example.com",
            [
                "HardBounce@example.com",
                "valid@example.com",
                "Hates Spam <spam@example.com>",
            ],
        )
        sent = msg.send()
        # one message sent, successfully, to 1 of 3 recipients:
        self.assertEqual(sent, 1)
        status = msg.anymail_status
        self.assertEqual(status.recipients["HardBounce@example.com"].status, "rejected")
        self.assertEqual(status.recipients["valid@example.com"].status, "sent")
        self.assertEqual(status.recipients["spam@example.com"].status, "rejected")


@tag("postmark")
class PostmarkBackendSessionSharingTestCase(
    SessionSharingTestCases, PostmarkBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("postmark")
@override_settings(EMAIL_BACKEND="anymail.backends.postmark.EmailBackend")
class PostmarkBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bPOSTMARK_SERVER_TOKEN\b")
        self.assertRegex(errmsg, r"\bANYMAIL_POSTMARK_SERVER_TOKEN\b")
