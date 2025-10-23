from __future__ import annotations

from base64 import b64encode
from datetime import datetime
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag
from django.utils.timezone import timezone

from anymail.exceptions import (
    AnymailAPIError,
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


@tag("mailtrap")
@override_settings(
    EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend",
    ANYMAIL={"MAILTRAP_API_TOKEN": "test_api_token"},
)
class MailtrapBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "success": true,
        "message_ids": ["1df37d17-0286-4d8b-8edf-bc4ec5be86e6"]
    }"""

    def setUp(self):
        super().setUp()
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )

    def set_mock_response_message_ids(self, message_ids: list[str] | int):
        """
        Set a "success" mock response payload with multiple message_ids.
        Call with either the count of ids to generate or the list of desired ids.
        """
        if isinstance(message_ids, int):
            message_ids = [f"message-id-{i}" for i in range(message_ids)]
        self.set_mock_response(
            json_data={
                "success": True,
                "message_ids": message_ids,
            },
        )


@tag("mailtrap")
class MailtrapBackendStandardEmailTests(MailtrapBackendMockAPITestCase):
    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@sender.example.com",
            ["to@example.com"],
            fail_silently=False,
        )
        # Uses transactional API
        self.assert_esp_called("https://send.api.mailtrap.io/api/send")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["Api-Token"], "test_api_token")
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["text"], "Here is the message.")
        self.assertEqual(data["from"], {"email": "from@sender.example.com"})
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
        self.set_mock_response_message_ids(6)
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["from"], {"name": "From Name", "email": "from@example.com"}
        )
        self.assertEqual(
            data["to"],
            [
                {"name": "Recipient #1", "email": "to1@example.com"},
                {"email": "to2@example.com"},
            ],
        )
        self.assertEqual(
            data["cc"],
            [
                {"name": "Carbon Copy", "email": "cc1@example.com"},
                {"email": "cc2@example.com"},
            ],
        )
        self.assertEqual(
            data["bcc"],
            [
                {"name": "Blind Copy", "email": "bcc1@example.com"},
                {"email": "bcc2@example.com"},
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
        self.assertCountEqual(data["headers"], {"X-Custom": "string", "X-Num": 123})

    def test_extra_headers_serialization_error(self):
        self.message.extra_headers = {"X-Custom": Decimal(12.5)}
        with self.assertRaisesMessage(AnymailSerializationError, "Decimal"):
            self.message.send()

    def test_reply_to(self):
        # Reply-To is handled as a header, rather than API "reply_to" field,
        # to support multiple addresses.
        self.message.reply_to = ["reply@example.com", "Other <reply2@example.com>"]
        self.message.extra_headers = {"X-Other": "Keep"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["headers"],
            {
                "Reply-To": "reply@example.com, Other <reply2@example.com>",
                "X-Other": "Keep",
            },
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
        self.assertEqual(attachments[0]["type"], "text/plain")
        self.assertEqual(
            decode_att(attachments[0]["content"]).decode("ascii"), text_content
        )
        self.assertEqual(attachments[0].get("disposition", "attachment"), "attachment")
        self.assertNotIn("content_id", attachments[0])

        # ContentType inferred from filename:
        self.assertEqual(attachments[1]["type"], "image/png")
        self.assertEqual(attachments[1]["filename"], "test.png")
        self.assertEqual(decode_att(attachments[1]["content"]), png_content)
        # make sure image not treated as inline:
        self.assertEqual(attachments[1].get("disposition", "attachment"), "attachment")
        self.assertNotIn("content_id", attachments[1])

        self.assertEqual(attachments[2]["type"], "application/pdf")
        self.assertEqual(attachments[2]["filename"], "attachment")  # default
        self.assertEqual(decode_att(attachments[2]["content"]), pdf_content)
        self.assertEqual(attachments[2].get("disposition", "attachment"), "attachment")
        self.assertNotIn("content_id", attachments[2])

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
                    "type": "text/html",
                    "content": b64encode("<p>\u2019</p>".encode("utf-8")).decode(
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
        self.assertEqual(data["html"], html_content)

        attachments = data["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["filename"], image_filename)
        self.assertEqual(attachments[0]["type"], "image/png")
        self.assertEqual(decode_att(attachments[0]["content"]), image_data)
        self.assertEqual(attachments[0]["disposition"], "inline")
        self.assertEqual(attachments[0]["content_id"], cid)

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
                    "type": "image/png",
                    "content": image_data_b64,
                },
                {
                    "filename": "attachment",  # the unnamed one
                    "type": "image/png",
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
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "alternative part with type 'application/json'"
        ):
            self.message.send()

    def test_alternatives_fail_silently(self):
        # Make sure fail_silently is respected
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        sent = self.message.send(fail_silently=True)
        self.assert_esp_not_called("API should not be called when send fails silently")
        self.assertEqual(sent, 0)

    def test_multiple_from_emails(self):
        self.message.from_email = 'first@example.com, "From, also" <second@example.com>'
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature, "multiple from emails"
        ):
            self.message.send()

    def test_api_failure(self):
        self.set_mock_response(
            status_code=400,
            json_data={"success": False, "errors": ["helpful error message"]},
        )
        with self.assertRaisesMessage(
            AnymailAPIError, r"Mailtrap API response 400"
        ) as cm:
            self.message.send()
        # Error message includes response details:
        self.assertIn("helpful error message", str(cm.exception))

    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        self.set_mock_response(status_code=500)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)


@tag("mailtrap")
class MailtrapBackendAnymailFeatureTests(MailtrapBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "anything@bounces.example.com"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "envelope_sender"):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["custom_variables"], {"user_id": "12345", "items": "6"})

    def test_send_at(self):
        self.message.send_at = datetime(2023, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["category"], "receipt")

    def test_multiple_tags(self):
        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple tags"):
            self.message.send()

    @override_settings(ANYMAIL_IGNORE_UNSUPPORTED_FEATURES=True)
    def test_multiple_tags_ignore_unsupported_features(self):
        # First tag only when ignoring unsupported features
        self.message.tags = ["receipt", "repeat-user"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["category"], "receipt")

    def test_track_opens(self):
        self.message.track_opens = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_opens"):
            self.message.send()

    def test_track_clicks(self):
        self.message.track_clicks = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_clicks"):
            self.message.send()

    def test_non_batch_template(self):
        # Mailtrap's usual /send endpoint works for template sends
        # without per-recipient customization
        message = AnymailMessage(
            # Omit subject and body (Mailtrap prohibits them with templates)
            from_email="from@example.com",
            to=["to@example.com"],
            template_id="template-uuid",
            merge_global_data={"name": "Alice", "group": "Developers"},
        )
        message.send()
        self.assert_esp_called("/send")
        data = self.get_api_call_json()
        self.assertEqual(data["template_uuid"], "template-uuid")
        self.assertEqual(
            data["template_variables"], {"name": "Alice", "group": "Developers"}
        )
        # Make sure Django default subject and body didn't end up in the payload:
        self.assertNotIn("subject", data)
        self.assertNotIn("text", data)
        self.assertNotIn("html", data)

    # TODO: merge_data, merge_metadata, merge_headers and batch sending API
    # TODO: does Mailtrap support inline templates?

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
        self.assertNotIn("attachments", data)
        self.assertNotIn("headers", data)
        self.assertNotIn("custom_variables", data)
        self.assertNotIn("category", data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            "future_mailtrap_option": "some-value",
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["future_mailtrap_option"], "some-value")

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        response_content = {
            "success": True,
            # Transactional API response lists message ids in to, cc, bcc order
            "message_ids": [
                "id-to1",
                "id-to2",
                "id-cc1",
                "id-cc2",
                "id-bcc1",
                "id-bcc2",
            ],
        }
        self.set_mock_response(json_data=response_content)
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["Recipient <to1@example.com>", "to2@example.com"],
            cc=["CC <cc1@example.com>", "cc2@example.com"],
            bcc=["BCC <bcc1@example.com>", "bcc2@example.com"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"sent"})
        self.assertEqual(
            msg.anymail_status.message_id,
            {"id-to1", "id-to2", "id-cc1", "id-cc2", "id-bcc1", "id-bcc2"},
        )
        recipients = msg.anymail_status.recipients
        self.assertEqual(recipients["to1@example.com"].status, "sent")
        self.assertEqual(recipients["to1@example.com"].message_id, "id-to1")
        self.assertEqual(recipients["to2@example.com"].status, "sent")
        self.assertEqual(recipients["to2@example.com"].message_id, "id-to2")
        self.assertEqual(recipients["cc1@example.com"].status, "sent")
        self.assertEqual(recipients["cc1@example.com"].message_id, "id-cc1")
        self.assertEqual(recipients["cc2@example.com"].status, "sent")
        self.assertEqual(recipients["cc2@example.com"].message_id, "id-cc2")
        self.assertEqual(recipients["bcc1@example.com"].status, "sent")
        self.assertEqual(recipients["bcc1@example.com"].message_id, "id-bcc1")
        self.assertEqual(recipients["bcc2@example.com"].status, "sent")
        self.assertEqual(recipients["bcc2@example.com"].message_id, "id-bcc2")
        self.assertEqual(msg.anymail_status.esp_response.json(), response_content)

    def test_wrong_message_id_count(self):
        self.set_mock_response_message_ids(2)
        with self.assertRaisesMessage(AnymailAPIError, "Expected 1 message_ids, got 2"):
            self.message.send()

    # noinspection PyUnresolvedReferences
    @override_settings(
        ANYMAIL={"MAILTRAP_API_TOKEN": "test-token", "MAILTRAP_TEST_INBOX_ID": 12345}
    )
    def test_sandbox_send(self):
        self.set_mock_response_message_ids(["sandbox-single-id"])
        self.message.to = ["Recipient #1 <to1@example.com>", "to2@example.com"]
        self.message.send()

        self.assert_esp_called("https://sandbox.api.mailtrap.io/api/send/12345")
        self.assertEqual(self.message.anymail_status.status, {"sent"})
        self.assertEqual(
            self.message.anymail_status.message_id,
            "sandbox-single-id",
        )
        self.assertEqual(
            self.message.anymail_status.recipients["to1@example.com"].message_id,
            "sandbox-single-id",
        )
        self.assertEqual(
            self.message.anymail_status.recipients["to2@example.com"].message_id,
            "sandbox-single-id",
        )

    @override_settings(
        ANYMAIL={"MAILTRAP_API_TOKEN": "test-token", "MAILTRAP_TEST_INBOX_ID": 12345}
    )
    def test_wrong_message_id_count_sandbox(self):
        self.set_mock_response_message_ids(2)
        self.message.to = ["Recipient #1 <to1@example.com>", "to2@example.com"]
        with self.assertRaisesMessage(AnymailAPIError, "Expected 1 message_ids, got 2"):
            self.message.send()

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
        mock_response = self.set_mock_response(
            status_code=200, raw=b"yikes, this isn't a real response"
        )
        with self.assertRaises(AnymailAPIError):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(self.message.anymail_status.esp_response, mock_response)

    def test_send_with_serialization_error(self):
        self.message.extra_headers = {
            "foo": Decimal("1.23")
        }  # Decimal can't be serialized
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
        err = cm.exception
        self.assertIsInstance(err, TypeError)
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")

    def test_error_response(self):
        self.set_mock_response(
            status_code=401, json_data={"success": False, "error": "Invalid API token"}
        )
        with self.assertRaisesMessage(AnymailAPIError, "Invalid API token"):
            self.message.send()

    def test_unexpected_success_false(self):
        self.set_mock_response(
            status_code=200,
            json_data={"success": False, "message_ids": ["message-id-1"]},
        )
        with self.assertRaisesMessage(
            AnymailAPIError, "Unexpected API failure fields with response status 200"
        ):
            self.message.send()

    def test_unexpected_errors(self):
        self.set_mock_response(
            status_code=200,
            json_data={
                "success": True,
                "errors": ["oops"],
                "message_ids": ["message-id-1"],
            },
        )
        with self.assertRaisesMessage(
            AnymailAPIError, "Unexpected API failure fields with response status 200"
        ):
            self.message.send()

    @override_settings(
        ANYMAIL={
            "MAILTRAP_API_TOKEN": "test-token",
            "MAILTRAP_API_URL": "https://bulk.api.mailtrap.io/api",
        }
    )
    def test_override_api_url(self):
        self.message.send()
        self.assert_esp_called("https://bulk.api.mailtrap.io/api/send")


@tag("mailtrap")
class MailtrapBackendSessionSharingTestCase(
    SessionSharingTestCases, MailtrapBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("mailtrap")
@override_settings(EMAIL_BACKEND="anymail.backends.mailtrap.EmailBackend")
class MailtrapBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_token(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bMAILTRAP_API_TOKEN\b")
        self.assertRegex(errmsg, r"\bANYMAIL_MAILTRAP_API_TOKEN\b")
