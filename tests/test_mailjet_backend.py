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


@tag("mailjet")
@override_settings(
    EMAIL_BACKEND="anymail.backends.mailjet.EmailBackend",
    ANYMAIL={
        "MAILJET_API_KEY": "API KEY HERE",
        "MAILJET_SECRET_KEY": "SECRET KEY HERE",
    },
)
class MailjetBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "Messages": [{
            "Status": "success",
            "To": [{
                "Email": "to@example.com",
                "MessageUUID": "cb927469-36fd-4c02-bce4-0d199929a207",
                "MessageID": 70650219165027410,
                "MessageHref": "https://api.mailjet.com/v3/message/70650219165027410"
            }]
        }]
    }"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("mailjet")
class MailjetBackendStandardEmailTests(MailjetBackendMockAPITestCase):
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
        self.assert_esp_called("/v3.1/send")

        auth = self.get_api_call_auth()
        self.assertEqual(auth, ("API KEY HERE", "SECRET KEY HERE"))

        data = self.get_api_call_json()
        self.assertEqual(len(data["Messages"]), 1)
        message = data["Messages"][0]
        self.assertEqual(data["Globals"]["Subject"], "Subject here")
        self.assertEqual(data["Globals"]["TextPart"], "Here is the message.")
        self.assertEqual(data["Globals"]["From"], {"Email": "from@sender.example.com"})
        self.assertEqual(message["To"], [{"Email": "to@example.com"}])

    def test_name_addr(self):
        """Make sure RFC2822 name-addr format (with display-name) is allowed

        (Test both sender and recipient addresses)
        """
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "From Name <from@example.com>",
            ['"Recipient, #1" <to1@example.com>', "to2@example.com"],
            cc=["Carbon Copy <cc1@example.com>", "cc2@example.com"],
            bcc=["Blind Copy <bcc1@example.com>", "bcc2@example.com"],
        )
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["Messages"]), 1)
        message = data["Messages"][0]
        self.assertEqual(
            data["Globals"]["From"], {"Email": "from@example.com", "Name": "From Name"}
        )
        self.assertEqual(
            message["To"],
            [
                {"Email": "to1@example.com", "Name": "Recipient, #1"},
                {"Email": "to2@example.com"},
            ],
        )
        self.assertEqual(
            data["Globals"]["Cc"],
            [
                {"Email": "cc1@example.com", "Name": "Carbon Copy"},
                {"Email": "cc2@example.com"},
            ],
        )
        self.assertEqual(
            data["Globals"]["Bcc"],
            [
                {"Email": "bcc1@example.com", "Name": "Blind Copy"},
                {"Email": "bcc2@example.com"},
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
            headers={"Reply-To": "another@example.com", "X-MyHeader": "my value"},
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["Messages"]), 1)
        message = data["Messages"][0]
        self.assertEqual(data["Globals"]["Subject"], "Subject")
        self.assertEqual(data["Globals"]["TextPart"], "Body goes here")
        self.assertEqual(data["Globals"]["From"], {"Email": "from@example.com"})
        self.assertEqual(
            message["To"],
            [
                {"Email": "to1@example.com"},
                {"Email": "to2@example.com", "Name": "Also To"},
            ],
        )
        self.assertEqual(
            data["Globals"]["Cc"],
            [
                {"Email": "cc1@example.com"},
                {"Email": "cc2@example.com", "Name": "Also CC"},
            ],
        )
        self.assertEqual(
            data["Globals"]["Bcc"],
            [
                {"Email": "bcc1@example.com"},
                {"Email": "bcc2@example.com", "Name": "Also BCC"},
            ],
        )
        # Reply-To should be moved to own param:
        self.assertEqual(data["Globals"]["Headers"], {"X-MyHeader": "my value"})
        self.assertEqual(data["Globals"]["ReplyTo"], {"Email": "another@example.com"})

    def test_html_message(self):
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()

        data = self.get_api_call_json()
        self.assertEqual(len(data["Messages"]), 1)
        self.assertEqual(data["Globals"]["TextPart"], text_content)
        self.assertEqual(data["Globals"]["HTMLPart"], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn("Attachments", data["Globals"])

    def test_html_only_message(self):
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMessage(
            "Subject", html_content, "from@example.com", ["to@example.com"]
        )
        email.content_subtype = "html"  # Main content is now text/html
        email.send()

        data = self.get_api_call_json()
        self.assertNotIn("TextPart", data["Globals"])
        self.assertEqual(data["Globals"]["HTMLPart"], html_content)

    def test_extra_headers(self):
        self.message.extra_headers = {"X-Custom": "string", "X-Num": 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["Globals"]["Headers"],
            {
                "X-Custom": "string",
                "X-Num": 123,
            },
        )

    def test_extra_headers_serialization_error(self):
        self.message.extra_headers = {"X-Custom": Decimal(12.5)}
        with self.assertRaisesMessage(AnymailSerializationError, "Decimal"):
            self.message.send()

    @override_settings(ANYMAIL_IGNORE_UNSUPPORTED_FEATURES=True)
    def test_reply_to(self):
        # Mailjet only allows single reply-to. Verify correct handling for that
        # when ignoring unsupported features.
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
        # only the first reply_to:
        self.assertEqual(data["Globals"]["ReplyTo"], {"Email": "reply@example.com"})
        # don't lose other headers:
        self.assertEqual(data["Globals"]["Headers"], {"X-Other": "Keep"})

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
        attachments = data["Globals"]["Attachments"]
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["Filename"], "test.txt")
        self.assertEqual(attachments[0]["ContentType"], "text/plain")
        self.assertEqual(
            decode_att(attachments[0]["Base64Content"]).decode("ascii"), text_content
        )
        self.assertNotIn("ContentID", attachments[0])

        # inferred from filename:
        self.assertEqual(attachments[1]["ContentType"], "image/png")
        self.assertEqual(attachments[1]["Filename"], "test.png")
        self.assertEqual(decode_att(attachments[1]["Base64Content"]), png_content)
        # make sure image not treated as inline:
        self.assertNotIn("ContentID", attachments[1])

        self.assertEqual(attachments[2]["ContentType"], "application/pdf")
        self.assertEqual(attachments[2]["Filename"], "")  # none
        self.assertEqual(decode_att(attachments[2]["Base64Content"]), pdf_content)
        self.assertNotIn("ContentID", attachments[2])

        self.assertNotIn("InlinedAttachments", data["Globals"])

    def test_unicode_attachment_correctly_decoded(self):
        self.message.attach(
            "Une pièce jointe.html", "<p>\u2019</p>", mimetype="text/html"
        )
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["Globals"]["Attachments"],
            [
                {
                    "Filename": "Une pièce jointe.html",
                    "ContentType": "text/html",
                    "Base64Content": b64encode("<p>\u2019</p>".encode("utf-8")).decode(
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
        self.assertEqual(data["Globals"]["HTMLPart"], html_content)

        attachments = data["Globals"]["InlinedAttachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["Filename"], image_filename)
        self.assertEqual(attachments[0]["ContentID"], cid)
        self.assertEqual(attachments[0]["ContentType"], "image/png")
        self.assertEqual(decode_att(attachments[0]["Base64Content"]), image_data)

        self.assertNotIn("Attachments", data["Globals"])

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        # option 1: attach as a file:
        self.message.attach_file(image_path)

        # option 2: construct the MIMEImage and attach it directly:
        image = MIMEImage(image_data)
        self.message.attach(image)

        image_data_b64 = b64encode(image_data).decode("ascii")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["Globals"]["Attachments"],
            [
                {
                    "Filename": image_filename,  # the named one
                    "ContentType": "image/png",
                    "Base64Content": image_data_b64,
                },
                {
                    "Filename": "",  # the unnamed one
                    "ContentType": "image/png",
                    "Base64Content": image_data_b64,
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
        self.assertNotIn("Cc", data["Globals"])
        self.assertNotIn("Bcc", data["Globals"])
        self.assertNotIn("ReplyTo", data["Globals"])

    def test_empty_to_list(self):
        # Mailjet v3.1 doesn't support cc-only or bcc-only messages
        self.message.to = []
        self.message.cc = ["cc@example.com"]
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "messages without any `to` recipients"
        ):
            self.message.send()

    def test_api_failure(self):
        self.set_mock_response(status_code=500)
        with self.assertRaisesMessage(AnymailAPIError, "Mailjet API response 500"):
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
        # JSON error response - global error:
        error_response = json.dumps(
            {
                "ErrorIdentifier": "06df1144-c6f3-4ca7-8885-7ec5d4344113",
                "ErrorCode": "mj-0002",
                "ErrorMessage": "Helpful explanation from Mailjet.",
                "StatusCode": 400,
            }
        ).encode("utf-8")
        self.set_mock_response(status_code=400, raw=error_response)
        with self.assertRaisesMessage(
            AnymailAPIError, "Helpful explanation from Mailjet"
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


@tag("mailjet")
class MailjetBackendAnymailFeatureTests(MailjetBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "bounce-handler@bounces.example.com"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["Globals"]["Sender"], {"Email": "bounce-handler@bounces.example.com"}
        )

    def test_metadata(self):
        # Mailjet expects the payload to be a single string
        # https://dev.mailjet.com/guides/#tagging-email-messages
        self.message.metadata = {"user_id": "12345", "items": 6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertJSONEqual(
            data["Globals"]["EventPayload"], {"user_id": "12345", "items": 6}
        )

    def test_send_at(self):
        self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Globals"]["CustomCampaign"], "receipt")

        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple tags"):
            self.message.send()

    def test_track_opens(self):
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Globals"]["TrackOpens"], "enabled")

    def test_track_clicks(self):
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Globals"]["TrackClicks"], "enabled")

        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Globals"]["TrackClicks"], "disabled")

    def test_template(self):
        # template_id can be str or int (but must be numeric ID-not the template's name)
        self.message.template_id = "1234567"
        self.message.merge_global_data = {"name": "Alice", "group": "Developers"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Globals"]["TemplateID"], 1234567)  # must be integer
        # TemplateLanguage required to use variables:
        self.assertEqual(data["Globals"]["TemplateLanguage"], True)
        self.assertEqual(
            data["Globals"]["Variables"], {"name": "Alice", "group": "Developers"}
        )

    def test_template_populate_from_sender(self):
        # v3.1 API allows omitting From param to use template's sender
        self.message.template_id = "1234567"
        # must set from_email to None after constructing EmailMessage:
        self.message.from_email = None
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("From", data["Globals"])  # use template's sender as From

    def test_merge_data(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice", "group": "Developers"},
            "bob@example.com": {"name": "Bob"},
        }
        self.message.merge_global_data = {
            "group": "Default Group",
            "global": "Global value",
        }
        self.message.send()
        data = self.get_api_call_json()
        messages = data["Messages"]
        # with merge_data, each 'to' gets separate message:
        self.assertEqual(len(messages), 2)

        self.assertEqual(messages[0]["To"], [{"Email": "alice@example.com"}])
        self.assertEqual(
            messages[1]["To"], [{"Email": "bob@example.com", "Name": "Bob"}]
        )

        # global merge_data is sent in Globals
        self.assertEqual(
            data["Globals"]["Variables"],
            {"group": "Default Group", "global": "Global value"},
        )

        # per-recipient merge_data is sent in Messages
        # (and Mailjet will merge with Globals)
        self.assertEqual(
            messages[0]["Variables"], {"name": "Alice", "group": "Developers"}
        )
        self.assertEqual(messages[1]["Variables"], {"name": "Bob"})

    def test_merge_metadata(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.merge_metadata = {
            "alice@example.com": {"order_id": 123, "tier": "premium"},
            "bob@example.com": {"order_id": 678},
        }
        self.message.metadata = {"notification_batch": "zx912"}
        self.message.send()

        data = self.get_api_call_json()
        messages = data["Messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["To"][0]["Email"], "alice@example.com")
        # metadata and merge_metadata[recipient] are combined:
        self.assertJSONEqual(
            messages[0]["EventPayload"],
            {"order_id": 123, "tier": "premium", "notification_batch": "zx912"},
        )
        self.assertEqual(messages[1]["To"][0]["Email"], "bob@example.com")
        self.assertJSONEqual(
            messages[1]["EventPayload"],
            {"order_id": 678, "notification_batch": "zx912"},
        )

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("CustomCampaign", data["Globals"])
        self.assertNotIn("EventPayload", data["Globals"])
        self.assertNotIn("HTMLPart", data["Globals"])
        self.assertNotIn("TemplateID", data["Globals"])
        self.assertNotIn("TemplateLanguage", data["Globals"])
        self.assertNotIn("Variables", data["Globals"])
        self.assertNotIn("TrackOpens", data["Globals"])
        self.assertNotIn("TrackClicks", data["Globals"])

    def test_esp_extra(self):
        # Anymail deep merges Mailjet esp_extra into the v3.1 Send API payload.
        # Most options you'd want to override are in Globals, though a few are
        # at the root. Note that it's *not* possible to merge into Messages
        # (though you could completely replace it).
        self.message.esp_extra = {
            "Globals": {
                "TemplateErrorDeliver": True,
                "TemplateErrorReporting": "bugs@example.com",
            },
            "SandboxMode": True,
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["Globals"]["TemplateErrorDeliver"], True)
        self.assertEqual(data["Globals"]["TemplateErrorReporting"], "bugs@example.com")
        self.assertIs(data["SandboxMode"], True)
        # Make sure the backend params are also still there
        self.assertEqual(data["Globals"]["Subject"], "Subject")

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        response_content = json.dumps(
            {
                "Messages": [
                    {
                        "Status": "success",
                        "To": [
                            {
                                "Email": "to1@example.com",
                                "MessageUUID": "cb927469-36fd-4c02-bce4-0d199929a207",
                                "MessageID": 12345678901234500,
                                "MessageHref": "https://api.mailjet.com/v3/message"
                                "/12345678901234500",
                            }
                        ],
                    }
                ]
            }
        ).encode("utf-8")
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage(
            "Subject", "Message", "from@example.com", ["to1@example.com"]
        )
        sent = msg.send()

        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"sent"})
        self.assertEqual(msg.anymail_status.message_id, "12345678901234500")
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "sent"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id,
            "12345678901234500",
        )
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    # noinspection PyUnresolvedReferences
    def test_mixed_status(self):
        """The status should include an entry for each recipient"""
        # Mailjet's v3.1 API will partially fail a batch send, allowing valid emails
        # to go out. The API response doesn't identify the failed email addresses;
        # make sure we represent them correctly in the anymail_status.
        response_content = json.dumps(
            {
                "Messages": [
                    {
                        "Status": "success",
                        "CustomID": "",
                        "To": [
                            {
                                "Email": "to-good@example.com",
                                "MessageUUID": "556e896a-e041-4836-bb35-8bb75ee308c5",
                                "MessageID": 12345678901234500,
                                "MessageHref": "https://api.mailjet.com/v3/REST"
                                "/message/12345678901234500",
                            }
                        ],
                        "Cc": [],
                        "Bcc": [],
                    },
                    {
                        "Errors": [
                            {
                                "ErrorIdentifier": "f480a5a2-0334-4e08"
                                "-b2b7-f372ce5669e0",
                                "ErrorCode": "mj-0013",
                                "StatusCode": 400,
                                "ErrorMessage": '"invalid@123.4" is an invalid'
                                " email address.",
                                "ErrorRelatedTo": ["To[0].Email"],
                            }
                        ],
                        "Status": "error",
                    },
                ]
            }
        ).encode("utf-8")
        # Mailjet uses 400 for partial success:
        self.set_mock_response(raw=response_content, status_code=400)
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to-good@example.com", "invalid@123.4"],
        )
        sent = msg.send()

        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"sent", "failed"})
        self.assertEqual(
            msg.anymail_status.recipients["to-good@example.com"].status, "sent"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to-good@example.com"].message_id,
            "12345678901234500",
        )
        self.assertEqual(
            msg.anymail_status.recipients["invalid@123.4"].status, "failed"
        )
        self.assertEqual(
            msg.anymail_status.recipients["invalid@123.4"].message_id, None
        )
        self.assertEqual(msg.anymail_status.message_id, {"12345678901234500", None})
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
        self.assertIn("Don't know how to send this data to Mailjet", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")

    def test_merge_data_null_values(self):
        # Mailjet doesn't accept None (null) as a merge value;
        # returns "HTTP/1.1 500 Cannot convert data from Null value"
        self.message.merge_global_data = {"Some": None}
        self.set_mock_response(
            status_code=500, reason="Cannot convert data from Null value", raw=None
        )
        with self.assertRaisesMessage(
            AnymailAPIError, "Cannot convert data from Null value"
        ):
            self.message.send()


@tag("mailjet")
class MailjetBackendSessionSharingTestCase(
    SessionSharingTestCases, MailjetBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mailjet")
@override_settings(EMAIL_BACKEND="anymail.backends.mailjet.EmailBackend")
class MailjetBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bMAILJET_API_KEY\b")

    @override_settings(ANYMAIL={"MAILJET_API_KEY": "dummy"})
    def test_missing_secret_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bMAILJET_SECRET_KEY\b")
