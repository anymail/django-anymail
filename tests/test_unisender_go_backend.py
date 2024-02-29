import json
from base64 import b64encode
from datetime import date, datetime
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, override_settings, tag
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
from anymail.message import AnymailMessage, attach_inline_image_file

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import (
    SAMPLE_IMAGE_FILENAME,
    AnymailTestMixin,
    sample_image_content,
    sample_image_path,
)


@tag("unisender_go")
@override_settings(
    EMAIL_BACKEND="anymail.backends.unisender_go.EmailBackend",
    ANYMAIL={
        "UNISENDER_GO_API_KEY": "test_api_key",
        "UNISENDER_GO_API_URL": "https://go1.unisender.ru/ru/transactional/api/v1",
    },
)
class UnisenderGoBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = json.dumps(
        {
            "status": "success",
            "job_id": "1rctPx-00021H-CcC4",
            "emails": ["to@example.com"],
        }
    ).encode("utf-8")
    DEFAULT_STATUS_CODE = 200
    DEFAULT_CONTENT_TYPE = "application/json"

    def setUp(self):
        super().setUp()

        # Patch uuid4 to generate predictable message_ids for testing
        patch_uuid4 = patch(
            "anymail.backends.unisender_go.uuid.uuid4",
            side_effect=[f"mocked-uuid-{n:d}" for n in range(1, 10)],
        )
        patch_uuid4.start()
        self.addCleanup(patch_uuid4.stop)

        # Simple message useful for many tests
        self.message = AnymailMessage(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )

    def set_mock_response(
        self, success_emails=None, failed_emails=None, job_id=None, **kwargs
    ):
        """
        Pass success_emails and/or failure_emails to generate an appropriate
        API response for those specific emails. Otherwise, arguments are as
        for super call.
        :param success_emails {list[str]}: addr-specs of emails that were delivered
        :param failure_emails {dict[str,str]}: mapping of addr-spec -> failure reason
        :param job_id {str}: optional specific job_id for response
        """
        if success_emails or failed_emails:
            assert "raw" not in kwargs
            assert "json_response" not in kwargs
            assert kwargs.get("status_code", 200) == 200
            kwargs["status_code"] = 200
            kwargs["json_data"] = {
                "status": "success",
                "job_id": job_id or "1rctPx-00021H-CcC4",
                "emails": success_emails or [],
            }
            if failed_emails:
                kwargs["json_data"]["failed_emails"] = failed_emails

        return super().set_mock_response(**kwargs)


@tag("unisender_go")
class UnisenderGoBackendStandardEmailTests(UnisenderGoBackendMockAPITestCase):
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
        self.assert_esp_called(
            "https://go1.unisender.ru/ru/transactional/api/v1/email/send.json"
        )
        http_headers = self.get_api_call_headers()
        self.assertEqual(http_headers["X-API-KEY"], "test_api_key")
        self.assertEqual(http_headers["Accept"], "application/json")
        self.assertEqual(http_headers["Content-Type"], "application/json")

        data = self.get_api_call_json()
        self.assertEqual(data["message"]["subject"], "Subject here")
        self.assertEqual(data["message"]["body"], {"plaintext": "Here is the message."})
        self.assertEqual(data["message"]["from_email"], "from@sender.example.com")
        self.assertEqual(
            data["message"]["recipients"],
            [
                {
                    "email": "to@example.com",
                    # make sure the backend assigned the message_id
                    # for event tracking and notification
                    "metadata": {"anymail_id": "mocked-uuid-1"},
                }
            ],
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
        )
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["from_email"], "from@example.com")
        self.assertEqual(data["message"]["from_name"], "From Name")

        self.assertEqual(len(data["message"]["recipients"]), 2)
        recipient_1 = data["message"]["recipients"][0]
        self.assertEqual(recipient_1["email"], "to1@example.com")
        self.assertEqual(recipient_1["substitutions"]["to_name"], "Recipient #1")

        recipient_2 = data["message"]["recipients"][1]
        self.assertEqual(recipient_2["email"], "to2@example.com")
        self.assertNotIn("substitutions", recipient_2)  # to_name not needed

    def test_cc(self):
        # Unisender Go does not support cc through their web API
        self.message.cc = ["cc@example.com"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "cc"):
            self.message.send()

    def test_bcc(self):
        # Unisender Go does not support bcc through their web API
        self.message.bcc = ["bcc@example.com"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "bcc"):
            self.message.send()

    @override_settings(ANYMAIL_IGNORE_UNSUPPORTED_FEATURES=True)
    def test_ignore_unsupported_cc_bcc(self):
        self.message.cc = ["cc@example.com"]
        self.message.bcc = ["bcc@example.com"]
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})

    def test_html_message(self):
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["message"]["body"], {"plaintext": text_content, "html": html_content}
        )
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn("attachments", data["message"])

    def test_html_only_message(self):
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        email = mail.EmailMessage(
            "Subject", html_content, "from@example.com", ["to@example.com"]
        )
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["body"], {"html": html_content})

    def test_amp_html_alternative(self):
        # Unisender Go *does* support text/x-amp-html alongside text/html
        self.message.attach_alternative("<p>HTML</p>", "text/html")
        self.message.attach_alternative("<p>And AMP HTML</p>", "text/x-amp-html")
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["body"]["html"], "<p>HTML</p>")
        self.assertEqual(data["message"]["body"]["amp"], "<p>And AMP HTML</p>")

    def test_extra_headers(self):
        self.message.extra_headers = {
            "X-Custom": "string",
            "X-Num": 123,
            "Reply-To": "noreply@example.com",
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["message"]["headers"],
            {
                "X-Custom": "string",
                "X-Num": 123,
            },
        )
        # Reply-To must be moved to separate param
        self.assertNotIn("Reply-To", data["message"]["headers"])
        self.assertEqual(data["message"]["reply_to"], "noreply@example.com")
        self.assertNotIn("reply_to_name", data["message"])

    def test_extra_headers_serialization_error(self):
        self.message.extra_headers = {"X-Custom": Decimal(12.5)}
        with self.assertRaisesMessage(AnymailSerializationError, "Decimal"):
            self.message.send()

    def test_reply_to(self):
        # Unisender Go supports only a single reply-to
        self.message.reply_to = ['"Reply recipient" <reply@example.com']
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["reply_to"], "reply@example.com")
        self.assertEqual(data["message"]["reply_to_name"], "Reply recipient")

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

        self.assertEqual(
            attachments[0],
            {
                "name": "test.txt",
                "content": b64encode(text_content.encode("utf-8")).decode("ascii"),
                "type": "text/plain",
            },
        )
        self.assertEqual(
            attachments[1],
            {
                "name": "test.png",
                "content": b64encode(png_content).decode("ascii"),
                "type": "image/png",  # (type inferred from filename)
            },
        )
        self.assertEqual(
            attachments[2],
            {
                "name": "",  # no filename -- but param is required
                "content": b64encode(pdf_content).decode("ascii"),
                "type": "application/pdf",
            },
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

        self.assertEqual(
            data["message"]["inline_attachments"],
            [
                {
                    "name": cid,
                    "content": b64encode(image_data).decode("ascii"),
                    "type": "image/png",  # (type inferred from filename)
                }
            ],
        )

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

        image_data_b64 = b64encode(image_data).decode("ascii")
        data = self.get_api_call_json()
        self.assertEqual(
            data["message"]["attachments"][0],
            {
                "name": image_filename,  # the named one
                "content": image_data_b64,
                "type": "image/png",
            },
        )
        self.assertEqual(
            data["message"]["attachments"][1],
            {
                "name": "",  # the unnamed one
                "content": image_data_b64,
                "type": "image/png",
            },
        )

    def test_multiple_html_alternatives(self):
        # Multiple alternatives not allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>But not second html</p>", "text/html")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_non_html_alternative(self):
        # Only html alternatives allowed
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_api_failure(self):
        self.set_mock_response(status_code=400)
        with self.assertRaisesMessage(AnymailAPIError, "Unisender Go API response 400"):
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
            json_data=[
                {
                    "status": "error",
                    "message": "Helpful explanation from Unisender Go",
                    "code": 999,
                },
            ],
        )
        with self.assertRaisesMessage(
            AnymailAPIError, "Helpful explanation from Unisender Go"
        ):
            self.message.send()


@tag("unisender_go")
class UnisenderGoBackendAnymailFeatureTests(UnisenderGoBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        # Unisender Go does not have a way to change envelope sender.
        self.message.envelope_sender = "anything@bounces.example.com"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "envelope_sender"):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6, "float": 98.6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["message"]["global_metadata"],
            {
                "user_id": "12345",
                "items": 6,
                "float": 98.6,
            },
        )

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        with override_current_timezone(utc_plus_6):
            # Timezone-naive datetime assumed to be Django current_timezone
            self.message.send_at = datetime(2022, 10, 11, 12, 13, 14, 567)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["message"]["options"]["send_at"], "2022-10-11 06:13:14"
            )  # 12:13 UTC+6 == 06:13 UTC

            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["message"]["options"]["send_at"], "2016-03-04 13:06:07"
            )  # 05:06 UTC-8 == 13:06 UTC

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["message"]["options"]["send_at"], "2022-10-21 18:00:00"
            )  # 00:00 UTC+6 == 18:00-1d UTC

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["message"]["options"]["send_at"], "2022-05-06 07:08:09"
            )

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "2013-11-12 01:02:03"
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(
                data["message"]["options"]["send_at"], "2013-11-12 01:02:03"
            )

    def test_tags(self):
        self.message.tags = ["receipt", "repeat-user"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(data["message"]["tags"], ["receipt", "repeat-user"])

    def test_tracking(self):
        # Test one way...
        self.message.track_clicks = False
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["track_links"], 0)
        self.assertEqual(data["message"]["track_read"], 1)

        # ...and the opposite way
        self.message.track_clicks = True
        self.message.track_opens = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["track_links"], 1)
        self.assertEqual(data["message"]["track_read"], 0)

    def test_template_id(self):
        self.message.template_id = "5997fcf6-2b9f-484d-acd5-7e9a99f0dc1f"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["message"]["template_id"], "5997fcf6-2b9f-484d-acd5-7e9a99f0dc1f"
        )

    def test_merge_data(self):
        self.message.from_email = "from@example.com"
        self.message.to = [
            "alice@example.com",
            "Bob <bob@example.com>",
            "celia@example.com",
        ]
        self.message.merge_data = {
            "alice@example.com": {"name": "Alice", "group": "Developers"},
            "bob@example.com": {"name": "Robert"},  # and leave group undefined
            # and no data for celia@example.com
        }
        self.message.merge_global_data = {
            "group": "Users",
            "site": "ExampleCo",
        }
        self.message.send()

        data = self.get_api_call_json()
        recipients = data["message"]["recipients"]
        self.assertEqual(recipients[0]["email"], "alice@example.com")
        self.assertEqual(
            recipients[0]["substitutions"], {"name": "Alice", "group": "Developers"}
        )
        self.assertEqual(recipients[1]["email"], "bob@example.com")
        self.assertEqual(
            # Make sure email display name (as "to_name") is combined with merge_data
            recipients[1]["substitutions"],
            {"name": "Robert", "to_name": "Bob"},
        )
        self.assertEqual(recipients[2]["email"], "celia@example.com")
        self.assertNotIn("substitutions", recipients[2])
        self.assertEqual(
            data["message"]["global_substitutions"],
            {"group": "Users", "site": "ExampleCo"},
        )

    def test_merge_metadata(self):
        self.message.to = ["alice@example.com", "Bob <bob@example.com>"]
        self.message.merge_metadata = {
            "alice@example.com": {"order_id": 123},
            "bob@example.com": {"order_id": 678, "tier": "premium"},
        }
        self.message.send()
        data = self.get_api_call_json()
        recipients = data["message"]["recipients"]
        # anymail_id added to other recipient metadata
        self.assertEqual(
            recipients[0]["metadata"],
            {
                "anymail_id": "mocked-uuid-1",
                "order_id": 123,
            },
        )
        self.assertEqual(
            recipients[1]["metadata"],
            {
                "anymail_id": "mocked-uuid-2",
                "order_id": 678,
                "tier": "premium",
            },
        )

    @override_settings(ANYMAIL_UNISENDER_GO_GENERATE_MESSAGE_ID=False)
    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        message_data = self.get_api_call_json()["message"]
        self.assertNotIn("attachments", message_data)
        self.assertNotIn("from_name", message_data)
        self.assertNotIn("global_substitutions", message_data)
        self.assertNotIn("global_metadata", message_data)
        self.assertNotIn("headers", message_data)
        self.assertNotIn("inline_attachments", message_data)
        self.assertNotIn("options", message_data)
        self.assertNotIn("reply_to", message_data)
        self.assertNotIn("reply_to_name", message_data)
        self.assertNotIn("tags", message_data)
        self.assertNotIn("template_id", message_data)
        self.assertNotIn("track_links", message_data)
        self.assertNotIn("track_read", message_data)

        for recipient_data in message_data["recipients"]:
            self.assertNotIn("metadata", recipient_data)
            self.assertNotIn("substitutions", recipient_data)

    def test_esp_extra(self):
        self.message.send_at = "2022-02-22 22:22:22"
        self.message.esp_extra = {
            "global_language": "en",
            "skip_unsubscribe": 1,
            "template_engine": "velocity",
            "options": {
                "unsubscribe_url": "https://example.com/unsubscribe?id={{user_id}}",
                "smtp_pool_id": "custom-smtp-pool",
            },
        }
        self.message.send()
        data = self.get_api_call_json()
        # merged from esp_extra:
        self.assertEqual(data["message"]["global_language"], "en")
        self.assertEqual(data["message"]["skip_unsubscribe"], 1)
        self.assertEqual(data["message"]["template_engine"], "velocity")
        self.assertEqual(
            data["message"]["options"],
            {  # deep merge
                "send_at": "2022-02-22 22:22:22",
                "unsubscribe_url": "https://example.com/unsubscribe?id={{user_id}}",
                "smtp_pool_id": "custom-smtp-pool",
            },
        )

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to@example.com"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(msg.anymail_status.message_id, "mocked-uuid-1")
        self.assertEqual(
            msg.anymail_status.recipients["to@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to@example.com"].message_id, "mocked-uuid-1"
        )
        self.assertEqual(
            msg.anymail_status.esp_response.content, self.DEFAULT_RAW_RESPONSE
        )

    def test_batch_recipients_get_unique_message_ids(self):
        """In a batch send, each recipient should get a distinct message_id"""
        # Unisender Go *always* uses batch send; no need to force by setting merge_data.
        self.set_mock_response(success_emails=["to1@example.com", "to2@example.com"])
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["to1@example.com", "Someone Else <to2@example.com>"],
        )
        msg.send()
        self.assertEqual(
            msg.anymail_status.message_id, {"mocked-uuid-1", "mocked-uuid-2"}
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id, "mocked-uuid-1"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to2@example.com"].message_id, "mocked-uuid-2"
        )

    def test_rejected_recipient_status(self):
        self.message.to = [
            "duplicate@example.com",
            "Again <duplicate@example.com>",
            "Duplicate@example.com",  # addresses are case-insensitive
            "bounce@example.com",
            "mailbox-full@example.com",
            "webmaster@localhost",
            "spam-report@example.com",
        ]
        self.set_mock_response(
            # Note "duplicate" email will appear in both success and failed lists
            # (because Unisender Go sends the first one, fails remaining duplicates)
            success_emails=["duplicate@example.com"],
            failed_emails={
                "duplicate@example.com": "duplicate",
                "Duplicate@example.com": "duplicate",
                "bounce@example.com": "permanent_unavailable",
                "mailbox-full@example.com": "temporary_unavailable",
                "webmaster@localhost": "invalid",
                "spam-report@example.com": "unsubscribed",
            },
        )
        self.message.send()
        recipient_status = self.message.anymail_status.recipients
        self.assertEqual(recipient_status["duplicate@example.com"].status, "queued")
        self.assertEqual(
            # duplicate uses _first_ message_id (because first instance will be sent)
            recipient_status["duplicate@example.com"].message_id,
            "mocked-uuid-1",
        )
        self.assertEqual(recipient_status["bounce@example.com"].status, "rejected")
        self.assertIsNone(recipient_status["bounce@example.com"].message_id)
        self.assertEqual(recipient_status["mailbox-full@example.com"].status, "failed")
        self.assertIsNone(recipient_status["mailbox-full@example.com"].message_id)
        self.assertEqual(recipient_status["webmaster@localhost"].status, "invalid")
        self.assertIsNone(recipient_status["webmaster@localhost"].message_id)
        self.assertEqual(recipient_status["spam-report@example.com"].status, "rejected")
        self.assertIsNone(recipient_status["spam-report@example.com"].message_id)

    @override_settings(ANYMAIL_UNISENDER_GO_GENERATE_MESSAGE_ID=False)
    def test_disable_generate_message_id(self):
        self.message.send()
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertIsNone(
            self.message.anymail_status.recipients["to@example.com"].message_id
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

    def test_json_serialization_errors(self):
        """Try to provide more information about non-json-serializable data"""
        self.message.metadata = {"total": Decimal("19.99")}
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        # our added context:
        self.assertIn("Don't know how to send this data to Unisender Go", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("unisender_go")
class UnisenderGoBackendRecipientsRefusedTests(UnisenderGoBackendMockAPITestCase):
    """
    Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid
    """

    def test_recipients_refused(self):
        self.message.to = ["invalid@localhost", "reject@example.com"]
        self.set_mock_response(
            failed_emails={
                "invalid@localhost": "invalid",
                "reject@example.com": "permanent_unavailable",
            }
        )
        with self.assertRaises(AnymailRecipientsRefused):
            self.message.send()

    def test_fail_silently(self):
        self.message.to = ["invalid@localhost", "reject@example.com"]
        self.set_mock_response(
            failed_emails={
                "invalid@localhost": "invalid",
                "reject@example.com": "permanent_unavailable",
            }
        )
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        self.message.to = [
            "invalid@localhost",
            "valid@example.com",
            "reject@example.com",
            "also.valid@example.com",
        ]
        self.set_mock_response(
            success_emails=["valid@example.com", "also.valid@example.com"],
            failed_emails={
                "invalid@localhost": "invalid",
                "reject@example.com": "permanent_unavailable",
            },
        )
        sent = self.message.send()
        # one message sent, successfully, to 2 of 4 recipients:
        self.assertEqual(sent, 1)
        status = self.message.anymail_status
        self.assertEqual(status.recipients["invalid@localhost"].status, "invalid")
        self.assertEqual(status.recipients["valid@example.com"].status, "queued")
        self.assertEqual(status.recipients["reject@example.com"].status, "rejected")
        self.assertEqual(status.recipients["also.valid@example.com"].status, "queued")

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)
    def test_settings_override(self):
        """No exception with ignore setting"""
        self.message.to = ["invalid@localhost", "reject@example.com"]
        self.set_mock_response(
            failed_emails={
                "invalid@localhost": "invalid",
                "reject@example.com": "permanent_unavailable",
            }
        )
        sent = self.message.send()
        self.assertEqual(sent, 1)  # refused message is included in sent count


@tag("unisender_go")
class UnisenderGoBackendSessionSharingTestCase(
    SessionSharingTestCases, UnisenderGoBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("unisender_go")
@override_settings(EMAIL_BACKEND="anymail.backends.unisender_go.EmailBackend")
class UnisenderGoBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_auth(self):
        with self.assertRaisesRegex(
            AnymailConfigurationError, r"\bUNISENDER_GO_API_KEY\b"
        ):
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
