import json
from datetime import datetime
from email.encoders import encode_7or8bit
from email.mime.application import MIMEApplication
from unittest.mock import ANY, patch

from django.core import mail
from django.core.mail import BadHeaderError
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError, AnymailUnsupportedFeature
from anymail.inbound import AnymailInboundMessage
from anymail.message import AnymailMessage, attach_inline_image_file

from .utils import (
    SAMPLE_IMAGE_FILENAME,
    AnymailTestMixin,
    sample_image_content,
    sample_image_path,
)


@tag("amazon_ses")
@override_settings(EMAIL_BACKEND="anymail.backends.amazon_sesv2.EmailBackend")
class AmazonSESBackendMockAPITestCase(AnymailTestMixin, SimpleTestCase):
    """TestCase that uses the Amazon SES EmailBackend with a mocked boto3 client"""

    def setUp(self):
        super().setUp()

        # Mock boto3.session.Session().client('sesv2').send_raw_email (and any other
        # client operations). (We could also use botocore.stub.Stubber, but mock works
        # well with our test structure.)
        self.patch_boto3_session = patch(
            "anymail.backends.amazon_sesv2.boto3.session.Session", autospec=True
        )
        self.mock_session = self.patch_boto3_session.start()  # boto3.session.Session
        self.addCleanup(self.patch_boto3_session.stop)
        #: boto3.session.Session().client
        self.mock_client = self.mock_session.return_value.client
        #: boto3.session.Session().client('sesv2', ...)
        self.mock_client_instance = self.mock_client.return_value
        self.set_mock_response()

        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )

    DEFAULT_SEND_RESPONSE = {
        "MessageId": "1111111111111111-bbbbbbbb-3333-7777-aaaa-eeeeeeeeeeee-000000",
        "ResponseMetadata": {
            "RequestId": "900dd7f3-0399-4a1b-9d9f-bed91f46924a",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {
                "date": "Tue, 21 Feb 2023 22:59:46 GMT",
                "content-type": "application/json",
                "content-length": "76",
                "connection": "keep-alive",
                "x-amzn-requestid": "900dd7f3-0399-4a1b-9d9f-bed91f46924a",
            },
            "RetryAttempts": 0,
        },
    }

    def set_mock_response(self, response=None, operation_name="send_email"):
        mock_operation = getattr(self.mock_client_instance, operation_name)
        mock_operation.return_value = response or self.DEFAULT_SEND_RESPONSE
        return mock_operation.return_value

    def set_mock_failure(self, response, operation_name="send_email"):
        from botocore.exceptions import ClientError

        mock_operation = getattr(self.mock_client_instance, operation_name)
        mock_operation.side_effect = ClientError(
            response, operation_name=operation_name
        )

    def get_session_params(self):
        if self.mock_session.call_args is None:
            raise AssertionError("boto3 Session was not created")
        (args, kwargs) = self.mock_session.call_args
        if args:
            raise AssertionError(
                "boto3 Session created with unexpected positional args %r" % args
            )
        return kwargs

    def get_client_params(self, service="sesv2"):
        """Returns kwargs params passed to mock boto3 client constructor

        Fails test if boto3 client wasn't constructed with named service
        """
        if self.mock_client.call_args is None:
            raise AssertionError("boto3 client was not created")
        (args, kwargs) = self.mock_client.call_args
        if len(args) != 1:
            raise AssertionError(
                "boto3 client created with unexpected positional args %r" % args
            )
        if args[0] != service:
            raise AssertionError(
                "boto3 client created with service %r, not %r" % (args[0], service)
            )
        return kwargs

    def get_send_params(self, operation_name="send_email"):
        """Returns kwargs params passed to the mock send API.

        Fails test if API wasn't called.
        """
        self.mock_client.assert_called_with("sesv2", config=ANY)
        mock_operation = getattr(self.mock_client_instance, operation_name)
        if mock_operation.call_args is None:
            raise AssertionError("API was not called")
        (args, kwargs) = mock_operation.call_args
        return kwargs

    def get_sent_message(self):
        """Returns a parsed version of the send_email Content.Raw.Data param"""
        params = self.get_send_params(operation_name="send_email")
        raw_mime = params["Content"]["Raw"]["Data"]
        parsed = AnymailInboundMessage.parse_raw_mime_bytes(raw_mime)
        return parsed

    def assert_esp_not_called(self, msg=None, operation_name="send_email"):
        mock_operation = getattr(self.mock_client_instance, operation_name)
        if mock_operation.called:
            raise AssertionError(msg or "ESP API was called and shouldn't have been")


@tag("amazon_ses")
class AmazonSESBackendStandardEmailTests(AmazonSESBackendMockAPITestCase):
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
        params = self.get_send_params()
        # send_email takes a fully-formatted MIME message.
        # This is a simple (if inexact) way to check for expected headers and body:
        raw_mime = params["Content"]["Raw"]["Data"]
        self.assertIsInstance(raw_mime, bytes)  # SendEmail expects Data as bytes
        self.assertIn(b"\nFrom: from@example.com\n", raw_mime)
        self.assertIn(b"\nTo: to@example.com\n", raw_mime)
        self.assertIn(b"\nSubject: Subject here\n", raw_mime)
        self.assertIn(b"\n\nHere is the message", raw_mime)
        # Destination must include all recipients:
        self.assertEqual(params["Destination"], {"ToAddresses": ["to@example.com"]})

    # Since the SES backend generates the MIME message using Django's
    # EmailMessage.message().to_string(), there's not really a need
    # to exhaustively test all the various standard email features.
    # (EmailMessage.message() is well tested in the Django codebase.)
    # Instead, just spot-check a few things...

    def test_destinations(self):
        self.message.to = ["to1@example.com", '"Recipient, second" <to2@example.com>']
        self.message.cc = ["cc1@example.com", "Also cc <cc2@example.com>"]
        self.message.bcc = ["bcc1@example.com", "BCC 2 <bcc2@example.com>"]
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(
            params["Destination"],
            {
                "ToAddresses": [
                    "to1@example.com",
                    '"Recipient, second" <to2@example.com>',
                ],
                "CcAddresses": ["cc1@example.com", "Also cc <cc2@example.com>"],
                "BccAddresses": ["bcc1@example.com", "BCC 2 <bcc2@example.com>"],
            },
        )
        # Bcc's shouldn't appear in the message itself:
        self.assertNotIn(b"bcc", params["Content"]["Raw"]["Data"])

    def test_non_ascii_headers(self):
        self.message.subject = "Thử tin nhắn"  # utf-8 in subject header
        self.message.to = ['"Người nhận" <to@example.com>']  # utf-8 in display name
        self.message.cc = ["cc@thư.example.com"]  # utf-8 in domain
        self.message.send()
        params = self.get_send_params()
        raw_mime = params["Content"]["Raw"]["Data"]
        # Non-ASCII headers must use MIME encoded-word syntax:
        self.assertIn(b"\nSubject: =?utf-8?b?VGjhu60gdGluIG5o4bqvbg==?=\n", raw_mime)
        # Non-ASCII display names as well:
        self.assertIn(
            b"\nTo: =?utf-8?b?TmfGsOG7nWkgbmjhuq1u?= <to@example.com>\n", raw_mime
        )
        # Non-ASCII address domains must use Punycode:
        self.assertIn(b"\nCc: cc@xn--th-e0a.example.com\n", raw_mime)
        # SES doesn't support non-ASCII in the username@ part
        # (RFC 6531 "SMTPUTF8" extension)

        # Destinations must include all recipients (addr-spec only, must use Punycode):
        self.assertEqual(
            params["Destination"],
            {
                "ToAddresses": ["=?utf-8?b?TmfGsOG7nWkgbmjhuq1u?= <to@example.com>"],
                "CcAddresses": ["cc@xn--th-e0a.example.com"],
            },
        )

    def test_attachments(self):
        # These are \u2022 bullets ("\N{BULLET}") below:
        text_content = "• Item one\n• Item two\n• Item three"
        self.message.attach(
            filename="Une pièce jointe.txt",  # utf-8 chars in filename
            content=text_content,
            mimetype="text/plain",
        )

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        # Should work with a MIMEBase object (also tests no filename)...
        pdf_content = b"PDF\xb4 pretend this is valid pdf params"
        mimeattachment = MIMEApplication(pdf_content, "pdf")  # application/pdf
        mimeattachment["Content-Disposition"] = "attachment"
        self.message.attach(mimeattachment)

        self.message.send()
        sent_message = self.get_sent_message()
        attachments = sent_message.attachments
        self.assertEqual(len(attachments), 3)

        self.assertEqual(attachments[0].get_content_type(), "text/plain")
        self.assertEqual(attachments[0].get_filename(), "Une pièce jointe.txt")
        self.assertEqual(attachments[0].get_param("charset"), "utf-8")
        self.assertEqual(attachments[0].get_content_text(), text_content)

        self.assertEqual(attachments[1].get_content_type(), "image/png")
        # not inline:
        self.assertEqual(attachments[1].get_content_disposition(), "attachment")
        self.assertEqual(attachments[1].get_filename(), "test.png")
        self.assertEqual(attachments[1].get_content_bytes(), png_content)

        self.assertEqual(attachments[2].get_content_type(), "application/pdf")
        self.assertIsNone(attachments[2].get_filename())  # no filename specified
        self.assertEqual(attachments[2].get_content_bytes(), pdf_content)

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path, domain="example.com")
        html_content = (
            '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        )
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        sent_message = self.get_sent_message()

        self.assertEqual(sent_message.html, html_content)

        inlines = sent_message.inline_attachments
        self.assertEqual(len(inlines), 1)
        self.assertEqual(inlines[cid].get_content_type(), "image/png")
        self.assertEqual(inlines[cid].get_filename(), image_filename)
        self.assertEqual(inlines[cid].get_content_bytes(), image_data)

        # Make sure neither the html nor the inline image is treated as an attachment:
        params = self.get_send_params()
        raw_mime = params["Content"]["Raw"]["Data"]
        self.assertNotIn(b"\nContent-Disposition: attachment", raw_mime)

    def test_multiple_html_alternatives(self):
        # Multiple alternatives *are* allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>And so is second</p>", "text/html")
        self.message.send()
        params = self.get_send_params()
        raw_mime = params["Content"]["Raw"]["Data"]
        # just check the alternative smade it into the message
        # (assume that Django knows how to format them properly)
        self.assertIn(b"\n\n<p>First html is OK</p>\n", raw_mime)
        self.assertIn(b"\n\n<p>And so is second</p>\n", raw_mime)

    def test_alternative(self):
        # Non-HTML alternatives (including AMP) *are* allowed
        self.message.attach_alternative("<p>AMP HTML</p>", "text/x-amp-html")
        self.message.send()
        params = self.get_send_params()
        raw_mime = params["Content"]["Raw"]["Data"]
        # just check the alternative made it into the message
        # (assume that Python email knows how to format it properly)
        self.assertIn(b"\nContent-Type: text/x-amp-html", raw_mime)

    def test_multiple_from(self):
        # Amazon allows multiple addresses in the From header,
        # but must specify a single one for the FromEmailAddress
        self.message.from_email = "First <from1@example.com>, from2@example.com"
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "multiple from emails"
        ):
            self.message.send()

    def test_commas_in_subject(self):
        """
        There used to be a Python email header bug that added unwanted spaces
        after commas in long subjects
        """
        self.message.subject = (
            "100,000,000 isn't a number you'd really want"
            " to break up in this email subject, right?"
        )
        self.message.send()
        sent_message = self.get_sent_message()
        self.assertEqual(sent_message["Subject"], self.message.subject)

    def test_no_cte_8bit(self):
        """Anymail works around an Amazon SES bug that can corrupt non-ASCII bodies."""
        # (see detailed comments in the backend code)

        # The generated MIMEText for each of these ends up using CTE 8bit by default:
        self.message.body = "Это text body"
        self.message.attach_alternative("<p>Это html body</p>", "text/html")
        self.message.attach("sample.csv", "Это attachment", "text/csv")

        # Also force a CTE 8bit attachment (which normally defaults to CTE base64):
        att = MIMEApplication("Это data".encode("utf8"), "data", encode_7or8bit)
        self.assertEqual(att["Content-Transfer-Encoding"], "8bit")
        self.message.attach(att)

        self.message.send()
        sent_message = self.get_sent_message()

        # Make sure none of the resulting parts use `Content-Transfer-Encoding: 8bit`.
        # (Technically, either quoted-printable or base64 would be OK, but base64 text
        # parts have a reputation for triggering spam filters, so just require
        # quoted-printable for them.)
        part_encodings = [
            (part.get_content_type(), part["Content-Transfer-Encoding"])
            for part in sent_message.walk()
        ]
        self.assertEqual(
            part_encodings,
            [
                ("multipart/mixed", None),
                ("multipart/alternative", None),
                ("text/plain", "quoted-printable"),
                ("text/html", "quoted-printable"),
                ("text/csv", "quoted-printable"),
                ("application/data", "base64"),
            ],
        )

    def test_api_failure(self):
        error_response = {
            "Error": {
                "Code": "MessageRejected",
                "Message": "Email address is not verified. The following identities"
                " failed the check in region US-EAST-1: to@example.com",
            },
            "ResponseMetadata": {
                "RequestId": "c44b0ae2-e086-45ca-8820-b76a9b9f430a",
                "HTTPStatusCode": 403,
                "HTTPHeaders": {
                    "date": "Tue, 21 Feb 2023 23:49:31 GMT",
                    "content-type": "application/json",
                    "content-length": "196",
                    "connection": "keep-alive",
                    "x-amzn-requestid": "c44b0ae2-e086-45ca-8820-b76a9b9f430a",
                    "x-amzn-errortype": "MessageRejected",
                },
                "RetryAttempts": 0,
            },
        }

        self.set_mock_failure(error_response)
        with self.assertRaises(AnymailAPIError) as cm:
            self.message.send()
        err = cm.exception
        # AWS error is included in Anymail message:
        self.assertIn(
            "Email address is not verified. The following identities failed "
            "the check in region US-EAST-1: to@example.com",
            str(err),
        )
        # Raw AWS response is available on the exception:
        self.assertEqual(err.response, error_response)

    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        self.set_mock_failure(
            {
                "Error": {
                    "Type": "Sender",
                    "Code": "InvalidParameterValue",
                    "Message": "That is not allowed",
                }
            }
        )
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)

    def test_prevents_header_injection(self):
        # Since we build the raw MIME message, we're responsible for preventing header
        # injection. django.core.mail.EmailMessage.message() implements most of that
        # (for the SMTP backend); spot check some likely cases just to be sure...
        with self.assertRaises(BadHeaderError):
            mail.send_mail(
                "Subject\r\ninjected", "Body", "from@example.com", ["to@example.com"]
            )
        with self.assertRaises(BadHeaderError):
            mail.send_mail(
                "Subject",
                "Body",
                '"Display-Name\nInjected" <from@example.com>',
                ["to@example.com"],
            )
        with self.assertRaises(BadHeaderError):
            mail.send_mail(
                "Subject",
                "Body",
                "from@example.com",
                ['"Display-Name\rInjected" <to@example.com>'],
            )
        with self.assertRaises(BadHeaderError):
            mail.EmailMessage(
                "Subject",
                "Body",
                "from@example.com",
                ["to@example.com"],
                headers={"X-Header": "custom header value\r\ninjected"},
            ).send()


@tag("amazon_ses")
class AmazonSESBackendAnymailFeatureTests(AmazonSESBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "bounce-handler@bounces.example.com"
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(
            params["FeedbackForwardingEmailAddress"],
            "bounce-handler@bounces.example.com",
        )

    def test_spoofed_to(self):
        # Amazon SES is one of the few ESPs that actually permits the To header
        # to differ from the envelope recipient...
        self.message.to = ["Envelope <envelope-to@example.com>"]
        self.message.extra_headers["To"] = "Spoofed <spoofed-to@elsewhere.example.org>"
        self.message.send()
        params = self.get_send_params()
        raw_mime = params["Content"]["Raw"]["Data"]
        self.assertEqual(
            params["Destination"],
            {"ToAddresses": ["Envelope <envelope-to@example.com>"]},
        )
        self.assertIn(b"\nTo: Spoofed <spoofed-to@elsewhere.example.org>\n", raw_mime)
        self.assertNotIn(b"envelope-to@example.com", raw_mime)

    def test_metadata(self):
        self.message.metadata = {
            "User ID": 12345,
            # that \n is a header-injection test:
            "items": "Correct horse,Battery,\nStaple",
            "Cart-Total": "22.70",
        }
        self.message.send()

        # Metadata is passed as JSON in a message header field:
        sent_message = self.get_sent_message()
        self.assertJSONEqual(
            sent_message["X-Metadata"],
            '{"User ID": 12345,'
            ' "items": "Correct horse,Battery,\\nStaple",'
            ' "Cart-Total": "22.70"}',
        )

    def test_send_at(self):
        # Amazon SES does not support delayed sending
        self.message.send_at = datetime(2016, 3, 4, 5, 6, 7)
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["Transactional", "Cohort 12/2017"]
        self.message.send()

        # Tags are added as multiple X-Tag message headers:
        sent_message = self.get_sent_message()
        self.assertCountEqual(
            sent_message.get_all("X-Tag"), ["Transactional", "Cohort 12/2017"]
        )

        # Tags are *not* by default used as Amazon SES "Message Tags":
        params = self.get_send_params()
        self.assertNotIn("Tags", params)

    @override_settings(ANYMAIL_AMAZON_SES_MESSAGE_TAG_NAME="Campaign")
    def test_amazon_message_tags(self):
        """
        The Anymail AMAZON_SES_MESSAGE_TAG_NAME setting enables a single Message Tag
        """
        self.message.tags = ["Welcome"]
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(
            params["EmailTags"], [{"Name": "Campaign", "Value": "Welcome"}]
        )

        # Multiple Anymail tags are not supported when using this feature
        self.message.tags = ["Welcome", "Variation_A"]
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature,
            "multiple tags with the AMAZON_SES_MESSAGE_TAG_NAME setting",
        ):
            self.message.send()

    def test_tracking(self):
        # Amazon SES doesn't support overriding click/open-tracking settings
        # on individual messages through any standard API params.
        # (You _can_ use a ConfigurationSet to control this; see esp_extra below.)
        self.message.track_clicks = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_clicks"):
            self.message.send()
        delattr(self.message, "track_clicks")

        self.message.track_opens = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_opens"):
            self.message.send()

    def test_merge_data(self):
        # Amazon SES only supports merging when using templates (see below)
        self.message.merge_data = {}
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "merge_data without template_id"
        ):
            self.message.send()
        delattr(self.message, "merge_data")

        self.message.merge_global_data = {"group": "Users", "site": "ExampleCo"}
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "global_merge_data without template_id"
        ):
            self.message.send()

    @override_settings(
        # only way to use tags with template_id:
        ANYMAIL_AMAZON_SES_MESSAGE_TAG_NAME="Campaign"
    )
    def test_template(self):
        """With template_id, Anymail switches to SESv2 SendBulkEmail"""
        # SendBulkEmail uses a completely different API call and payload
        # structure, so this re-tests a bunch of Anymail features that were handled
        # differently above. (See test_amazon_ses_integration for a more realistic
        # template example.)
        raw_response = {
            "BulkEmailEntryResults": [
                {
                    "Status": "SUCCESS",
                    "MessageId": "1111111111111111-bbbbbbbb-3333-7777",
                },
                {
                    "Status": "ACCOUNT_DAILY_QUOTA_EXCEEDED",
                    "Error": "Daily message quota exceeded",
                },
            ],
            "ResponseMetadata": self.DEFAULT_SEND_RESPONSE["ResponseMetadata"],
        }
        self.set_mock_response(raw_response, operation_name="send_bulk_email")
        message = AnymailMessage(
            template_id="welcome_template",
            from_email='"Example, Inc." <from@example.com>',
            to=["alice@example.com", "罗伯特 <bob@example.com>"],
            cc=["cc@example.com"],
            reply_to=["reply1@example.com", "Reply 2 <reply2@example.com>"],
            merge_data={
                "alice@example.com": {"name": "Alice", "group": "Developers"},
                "bob@example.com": {"name": "Bob"},  # and leave group undefined
                "nobody@example.com": {"name": "Not a recipient for this message"},
            },
            merge_global_data={"group": "Users", "site": "ExampleCo"},
            # (only works with AMAZON_SES_MESSAGE_TAG_NAME when using template):
            tags=["WelcomeVariantA"],
            envelope_sender="bounce@example.com",
            esp_extra={
                "FromEmailAddressIdentityArn": (
                    "arn:aws:ses:us-east-1:123456789012:identity/example.com"
                )
            },
        )
        message.send()

        # templates use a different API call...
        self.assert_esp_not_called(operation_name="send_email")
        params = self.get_send_params(operation_name="send_bulk_email")
        self.assertEqual(
            params["DefaultContent"]["Template"]["TemplateName"], "welcome_template"
        )
        self.assertEqual(
            params["FromEmailAddress"], '"Example, Inc." <from@example.com>'
        )
        bulk_entries = params["BulkEmailEntries"]
        self.assertEqual(len(bulk_entries), 2)
        self.assertEqual(
            bulk_entries[0]["Destination"],
            {"ToAddresses": ["alice@example.com"], "CcAddresses": ["cc@example.com"]},
        )
        self.assertEqual(
            json.loads(
                bulk_entries[0]["ReplacementEmailContent"]["ReplacementTemplate"][
                    "ReplacementTemplateData"
                ]
            ),
            {"name": "Alice", "group": "Developers"},
        )
        self.assertEqual(
            bulk_entries[1]["Destination"],
            {
                # SES requires RFC2047:
                "ToAddresses": ["=?utf-8?b?572X5Lyv54m5?= <bob@example.com>"],
                "CcAddresses": ["cc@example.com"],
            },
        )
        self.assertEqual(
            json.loads(
                bulk_entries[1]["ReplacementEmailContent"]["ReplacementTemplate"][
                    "ReplacementTemplateData"
                ]
            ),
            {"name": "Bob"},
        )
        self.assertEqual(
            json.loads(params["DefaultContent"]["Template"]["TemplateData"]),
            {"group": "Users", "site": "ExampleCo"},
        )
        self.assertEqual(
            params["ReplyToAddresses"],
            ["reply1@example.com", "Reply 2 <reply2@example.com>"],
        )
        self.assertEqual(
            params["DefaultEmailTags"],
            [{"Name": "Campaign", "Value": "WelcomeVariantA"}],
        )
        self.assertEqual(params["FeedbackForwardingEmailAddress"], "bounce@example.com")
        # esp_extra:
        self.assertEqual(
            params["FromEmailAddressIdentityArn"],
            "arn:aws:ses:us-east-1:123456789012:identity/example.com",
        )

        self.assertEqual(message.anymail_status.status, {"queued", "failed"})
        self.assertEqual(
            # different for each recipient
            message.anymail_status.message_id,
            {"1111111111111111-bbbbbbbb-3333-7777", None},
        )
        self.assertEqual(
            message.anymail_status.recipients["alice@example.com"].status, "queued"
        )
        self.assertEqual(
            message.anymail_status.recipients["bob@example.com"].status, "failed"
        )
        self.assertEqual(
            message.anymail_status.recipients["alice@example.com"].message_id,
            "1111111111111111-bbbbbbbb-3333-7777",
        )
        self.assertIsNone(
            message.anymail_status.recipients["bob@example.com"].message_id
        )
        self.assertEqual(message.anymail_status.esp_response, raw_response)

    def test_template_failure(self):
        """Failures to all recipients raise a similar error to non-template sends"""
        raw_response = {
            "BulkEmailEntryResults": [
                {
                    "Status": "TEMPLATE_DOES_NOT_EXIST",
                    "Error": "No template named 'oops'",
                },
                {
                    "Status": "TEMPLATE_DOES_NOT_EXIST",
                    "Error": "No template named 'oops'",
                },
            ],
            "ResponseMetadata": self.DEFAULT_SEND_RESPONSE["ResponseMetadata"],
        }
        self.set_mock_response(raw_response, operation_name="send_bulk_email")
        message = AnymailMessage(
            template_id="oops",
            from_email="from@example.com",
            to=["alice@example.com", "bob@example.com"],
        )
        with self.assertRaisesMessage(AnymailAPIError, "No template named 'oops'"):
            message.send()

    def test_template_unsupported(self):
        """A lot of options are not compatible with SendBulkTemplatedEmail"""
        message = AnymailMessage(template_id="welcome_template", to=["to@example.com"])

        message.subject = "nope, can't change template subject"
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "overriding template subject"
        ):
            message.send()
        message.subject = None

        message.body = "nope, can't change text body"
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "overriding template body content"
        ):
            message.send()
        message.content_subtype = "html"
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "overriding template body content"
        ):
            message.send()
        message.body = None

        message.attach("attachment.txt", "this is an attachment", "text/plain")
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "attachments with template"
        ):
            message.send()
        message.attachments = []

        message.extra_headers = {"X-Custom": "header"}
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "extra_headers with template"
        ):
            message.send()
        message.extra_headers = {}

        message.metadata = {"meta": "data"}
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "metadata with template"
        ):
            message.send()
        message.metadata = None

        message.tags = ["tag 1", "tag 2"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "tags with template"):
            message.send()
        message.tags = None

    def test_send_anymail_message_without_template(self):
        # Make sure SendEmail is used for non-template_id messages
        message = AnymailMessage(
            from_email="from@example.com", to=["to@example.com"], subject="subject"
        )
        message.send()
        self.assert_esp_not_called(operation_name="send_bulk_email")
        # fails if send_email not called:
        self.get_send_params(operation_name="send_email")

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        params = self.get_send_params()
        self.assertNotIn("BulkEmailEntries", params)
        self.assertNotIn("ConfigurationSetName", params)
        self.assertNotIn("DefaultContent", params)
        self.assertNotIn("DefaultContent", params)
        self.assertNotIn("DefaultEmailTags", params)
        self.assertNotIn("EmailTags", params)
        self.assertNotIn("FeedbackForwardingEmailAddress", params)
        self.assertNotIn("FeedbackForwardingEmailAddressIdentityArn", params)
        self.assertNotIn("FromEmailAddressIdentityArn", params)
        self.assertNotIn("ListManagementOptions", params)
        self.assertNotIn("ReplyToAddresses", params)

        sent_message = self.get_sent_message()
        # custom headers not added if not needed:
        self.assertNotIn("X-Metadata", sent_message)
        self.assertNotIn("X-Tag", sent_message)

    def test_esp_extra(self):
        # Values in esp_extra are merged into the Amazon SES SendRawEmail parameters
        self.message.esp_extra = {
            # E.g., if you've set up a configuration set
            # that disables open/click tracking:
            "ConfigurationSetName": "NoTrackingConfigurationSet",
        }
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params["ConfigurationSetName"], "NoTrackingConfigurationSet")

    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(
            msg.anymail_status.message_id,
            "1111111111111111-bbbbbbbb-3333-7777-aaaa-eeeeeeeeeeee-000000",
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "1111111111111111-bbbbbbbb-3333-7777-aaaa-eeeeeeeeeeee-000000",
        )
        self.assertEqual(msg.anymail_status.esp_response, self.DEFAULT_SEND_RESPONSE)

    # Amazon SES doesn't report rejected addresses at send time in a form that can be
    # distinguished from other API errors. If SES rejects *any* recipient you'll get
    # an AnymailAPIError, and the message won't be sent to *all* recipients.

    # noinspection PyUnresolvedReferences
    def test_send_unparsable_response(self):
        """
        If the send succeeds, but result is unexpected format,
        should raise an API exception
        """
        response_content = {"wrong": "format"}
        self.set_mock_response(response_content)
        with self.assertRaisesMessage(
            AnymailAPIError, "parsing Amazon SES send result"
        ):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(self.message.anymail_status.esp_response, response_content)


@tag("amazon_ses")
class AmazonSESBackendConfigurationTests(AmazonSESBackendMockAPITestCase):
    """Test configuration options"""

    def test_boto_default_config(self):
        """By default, boto3 gets credentials from the environment or its config files

        See http://boto3.readthedocs.io/en/stable/guide/configuration.html
        """
        self.message.send()

        session_params = self.get_session_params()
        # no additional params passed to boto3.session.Session():
        self.assertEqual(session_params, {})

        client_params = self.get_client_params()
        # Ignore botocore.config.Config, which doesn't support ==
        config = client_params.pop("config")
        # no additional params passed to session.client('ses'):
        self.assertEqual(client_params, {})
        self.assertRegex(
            config.user_agent_extra, r"django-anymail/\d(\.\w+){1,}-amazon-ses"
        )

    @override_settings(
        ANYMAIL={
            "AMAZON_SES_CLIENT_PARAMS": {
                # Example for testing; it's not a good idea to hardcode credentials in
                # your code. Safer: `os.getenv("MY_SPECIAL_AWS_KEY_ID")` etc.
                "aws_access_key_id": "test-access-key-id",
                "aws_secret_access_key": "test-secret-access-key",
                "region_name": "ap-northeast-1",
                # config can be given as dict of botocore.config.Config params
                "config": {
                    "read_timeout": 30,
                    "retries": {"max_attempts": 2},
                },
            }
        }
    )
    def test_client_params_in_setting(self):
        """
        The Anymail AMAZON_SES_CLIENT_PARAMS setting specifies
        boto3 session.client() params for Anymail
        """
        self.message.send()
        client_params = self.get_client_params()
        # Ignore botocore.config.Config, which doesn't support ==
        config = client_params.pop("config")
        self.assertEqual(
            client_params,
            {
                "aws_access_key_id": "test-access-key-id",
                "aws_secret_access_key": "test-secret-access-key",
                "region_name": "ap-northeast-1",
            },
        )
        self.assertEqual(config.read_timeout, 30)
        self.assertEqual(config.retries, {"max_attempts": 2})

    def test_client_params_in_connection_init(self):
        """
        You can also supply credentials specifically
        for a particular EmailBackend connection instance
        """
        from botocore.config import Config

        boto_config = Config(connect_timeout=30)
        conn = mail.get_connection(
            "anymail.backends.amazon_sesv2.EmailBackend",
            client_params={
                "aws_session_token": "test-session-token",
                "config": boto_config,
            },
        )
        conn.send_messages([self.message])

        client_params = self.get_client_params()
        # Ignore botocore.config.Config, which doesn't support ==
        config = client_params.pop("config")
        self.assertEqual(client_params, {"aws_session_token": "test-session-token"})
        self.assertEqual(config.connect_timeout, 30)

    @override_settings(
        ANYMAIL={"AMAZON_SES_SESSION_PARAMS": {"profile_name": "anymail-testing"}}
    )
    def test_session_params_in_setting(self):
        """
        The Anymail AMAZON_SES_SESSION_PARAMS setting
        specifies boto3.session.Session() params for Anymail
        """
        self.message.send()

        session_params = self.get_session_params()
        self.assertEqual(session_params, {"profile_name": "anymail-testing"})

        client_params = self.get_client_params()
        # Ignore botocore.config.Config, which doesn't support ==
        client_params.pop("config")
        # no additional params passed to session.client('ses'):
        self.assertEqual(client_params, {})

    @override_settings(
        ANYMAIL={"AMAZON_SES_CONFIGURATION_SET_NAME": "MyConfigurationSet"}
    )
    def test_config_set_setting(self):
        """You can supply a default ConfigurationSetName"""
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params["ConfigurationSetName"], "MyConfigurationSet")

        # override on individual message using esp_extra
        self.message.esp_extra = {"ConfigurationSetName": "CustomConfigurationSet"}
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params["ConfigurationSetName"], "CustomConfigurationSet")
