import base64
from datetime import datetime, timezone
from email.message import MIMEPart
from email.mime.image import MIMEImage

import django
import requests
from django.core import mail
from django.test import tag

from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import AnymailMessage, attach_inline_image

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import (
    get_default_mailer,
    ignore_fail_silently_warning,
    override_settings,
    sample_image_content,
)


@tag("mailchannels")
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.mailchannels.EmailBackend",
            "OPTIONS": {"api_key": "test_api_key"},
        }
    }
)
class MailChannelsBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_STATUS_CODE = 202
    DEFAULT_RAW_RESPONSE = (
        b'{"request_id":"queue-123", "queued_at":"2026-10-09T15:00:00Z"}'
    )

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("mailchannels")
class MailChannelsStandardEmailTests(MailChannelsBackendMockAPITestCase):
    def test_send_mail(self):
        self.assertEqual(
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"]),
            1,
        )
        self.assert_esp_called("https://api.mailchannels.net/tx/v1/send-async")
        self.assertEqual(self.get_api_call_headers()["X-Api-Key"], "test_api_key")
        self.assertEqual(
            self.get_api_call_headers()["Content-Type"], "application/json"
        )
        self.assertEqual(self.get_api_call_arg("timeout"), 30)
        self.assertEqual(
            self.get_api_call_json(),
            {
                "from": {"email": "from@example.com"},
                "subject": "Subject",
                "content": [{"type": "text/plain", "value": "Body"}],
                "personalizations": [{"to": [{"email": "to@example.com"}]}],
            },
        )

    def test_names_cc_bcc_reply_and_unicode(self):
        message = mail.EmailMessage(
            "Hello «世界»",
            "Body",
            '"Sender, 张三" <from@example.com>',
            ['"Recipient, One" <one@example.com>', "Deux <two@example.com>"],
            cc=["Copy <cc@example.com>"],
            bcc=["Hidden <bcc@example.com>"],
            reply_to=["Reply <reply@example.com>"],
            headers={"X-Custom": "é", "X-Count": 3},
        )
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["from"], {"email": "from@example.com", "name": "Sender, 张三"}
        )
        self.assertEqual(
            data["personalizations"],
            [
                {
                    "to": [
                        {"email": "one@example.com", "name": "Recipient, One"},
                        {"email": "two@example.com", "name": "Deux"},
                    ],
                    "cc": [{"email": "cc@example.com", "name": "Copy"}],
                    "bcc": [{"email": "bcc@example.com", "name": "Hidden"}],
                }
            ],
        )
        self.assertEqual(
            data["reply_to"], {"email": "reply@example.com", "name": "Reply"}
        )
        self.assertEqual(data["headers"], {"X-Custom": "é", "X-Count": "3"})
        self.assertEqual(data["subject"], "Hello «世界»")

    def test_idna(self):
        self.message.to = ["IDN <to@例え.テスト>"]
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["personalizations"][0]["to"],
            [{"email": "to@xn--r8jz45g.xn--zckzah", "name": "IDN"}],
        )

    def test_multipart(self):
        self.message.attach_alternative("<p>HTML</p>", "text/html")
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["content"],
            [
                {"type": "text/plain", "value": "Text Body"},
                {"type": "text/html", "value": "<p>HTML</p>"},
            ],
        )
        self.assertNotIn("attachments", self.get_api_call_json())

    def test_html_only(self):
        self.message.body = "<p>Only HTML</p>"
        self.message.content_subtype = "html"
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["content"],
            [{"type": "text/html", "value": "<p>Only HTML</p>"}],
        )

    def test_empty_body(self):
        self.message.body = ""
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["content"], [{"type": "text/plain", "value": ""}]
        )

    def test_attachments(self):
        self.message.attach("hello.txt", "héllo", "text/plain")
        self.message.attach("data.bin", b"\x00\xff", "application/octet-stream")
        self.message.send()
        attachments = self.get_api_call_json()["attachments"]
        self.assertEqual(base64.b64decode(attachments[0]["content"]), "héllo".encode())
        self.assertEqual(attachments[0]["filename"], "hello.txt")
        self.assertEqual(
            attachments[1],
            {
                "filename": "data.bin",
                "type": "application/octet-stream",
                "content": "AP8=",
            },
        )

    def test_inline_image(self):
        cid = attach_inline_image(
            self.message, sample_image_content(), filename="logo.png"
        )
        self.message.attach_alternative(f'<img src="cid:{cid}">', "text/html")
        self.message.send()
        attachment = self.get_api_call_json()["attachments"][0]
        self.assertEqual(attachment["content_id"], cid)
        self.assertEqual(
            base64.b64decode(attachment["content"]), sample_image_content()
        )
        self.assertEqual(attachment["type"], "image/png")

    @staticmethod
    def make_image_attachment():
        if django.VERSION < (6, 0):
            return MIMEImage(sample_image_content())
        image = MIMEPart()
        image.set_content(sample_image_content(), maintype="image", subtype="png")
        return image

    def test_noninline_content_id_does_not_make_inline(self):
        image = self.make_image_attachment()
        image.add_header("Content-Disposition", "attachment", filename="logo.png")
        image.add_header("Content-ID", "<not-inline>")
        self.message.attach(image)
        self.message.send()
        self.assertNotIn("content_id", self.get_api_call_json()["attachments"][0])

    def test_inline_without_id_unsupported(self):
        image = self.make_image_attachment()
        image.add_header("Content-Disposition", "inline", filename="logo.png")
        self.message.attach(image)
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "without Content-ID"):
            self.message.send()
        self.assert_esp_not_called()

    def test_no_recipients(self):
        self.message.to = []
        self.assertEqual(self.message.send(), 0)
        self.assert_esp_not_called()

    def test_cc_or_bcc_only_unsupported(self):
        for recipient_type in ("cc", "bcc"):
            with self.subTest(recipient_type=recipient_type):
                message = AnymailMessage("Subject", "Body", "from@example.com", [])
                setattr(message, recipient_type, ["copy@example.com"])
                with self.assertRaisesMessage(AnymailUnsupportedFeature, "without To"):
                    message.send()
        self.assert_esp_not_called()

    def test_reply_to_header_overrides_attribute(self):
        self.message.reply_to = ["attribute@example.com"]
        self.message.extra_headers = {"Reply-To": "Header <header@example.com>"}
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["reply_to"],
            {"email": "header@example.com", "name": "Header"},
        )

    def test_from_header_preserves_envelope(self):
        self.message.extra_headers = {"From": "Visible <visible@example.com>"}
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["from"],
            {"email": "visible@example.com", "name": "Visible"},
        )
        self.assertEqual(
            self.get_api_call_json()["envelope_from"], {"email": "from@example.com"}
        )

    def test_reserved_headers(self):
        for header in (
            "mEsSaGe-Id",
            "Cc",
            "BCC",
            "Subject",
            "Content-Type",
            "Content-Transfer-Encoding",
            "DKIM-Signature",
            "Received",
            "Authentication-Results",
            "To",
        ):
            with self.subTest(header=header):
                self.message.extra_headers = {header: "value"}
                with self.assertRaises(AnymailUnsupportedFeature):
                    self.message.send()
        self.assert_esp_not_called()

    def test_multiple_reply_to_unsupported(self):
        self.message.reply_to = ["one@example.com", "two@example.com"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple reply_to"):
            self.message.send()
        self.assert_esp_not_called()

    def test_multiple_html_unsupported(self):
        self.message.attach_alternative("one", "text/html")
        self.message.attach_alternative("two", "text/html")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple html"):
            self.message.send()
        self.assert_esp_not_called()

    def test_other_alternative_unsupported(self):
        self.message.attach_alternative("calendar", "text/calendar")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()
        self.assert_esp_not_called()


@tag("mailchannels")
class MailChannelsAnymailTests(MailChannelsBackendMockAPITestCase):
    def test_status(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.cc = ["cc@example.com"]
        self.message.bcc = ["bcc@example.com"]
        self.assertEqual(self.message.send(), 1)
        status = self.message.anymail_status
        self.assertEqual(status.status, {"queued"})
        self.assertEqual(status.message_id, "queue-123")
        self.assertEqual(
            set(status.recipients),
            {"one@example.com", "two@example.com", "cc@example.com", "bcc@example.com"},
        )
        for recipient in status.recipients.values():
            self.assertEqual(recipient.status, "queued")
            self.assertEqual(recipient.message_id, "queue-123")

    def test_envelope_sender(self):
        self.message.envelope_sender = "Bounce <bounce@example.com>"
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["envelope_from"], {"email": "bounce@example.com"}
        )

    def test_tracking(self):
        self.message.track_clicks = True
        self.message.track_opens = False
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["tracking_settings"],
            {"click_tracking": {"enable": True}, "open_tracking": {"enable": False}},
        )

    def test_merge_batch(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.cc = ["copy@example.com"]
        self.message.bcc = ["hidden@example.com"]
        self.message.body = "Hello {{name}}, {{common}}"
        self.message.merge_global_data = {"common": "global", "name": "default"}
        self.message.merge_data = {
            "one@example.com": {"name": "One", "common": "local"}
        }
        self.message.extra_headers = {"X-Value": "global"}
        self.message.merge_headers = {"one@example.com": {"X-Value": "local"}}
        self.message.send()
        data = self.get_api_call_json()
        one, two = data["personalizations"]
        self.assertEqual(one["to"], [{"email": "one@example.com"}])
        self.assertEqual(two["to"], [{"email": "two@example.com"}])
        self.assertEqual(
            one["dynamic_template_data"], {"common": "local", "name": "One"}
        )
        self.assertEqual(
            two["dynamic_template_data"], {"common": "global", "name": "default"}
        )
        self.assertEqual(one["headers"], {"X-Value": "local"})
        self.assertNotIn("headers", two)
        for personalization in (one, two):
            self.assertEqual(personalization["cc"], [{"email": "copy@example.com"}])
            self.assertEqual(personalization["bcc"], [{"email": "hidden@example.com"}])
        self.assertEqual(data["headers"], {"X-Value": "global"})
        self.assertEqual(data["content"][0]["template_type"], "mustache")
        self.assertEqual(self.mock_request.call_count, 1)

    def test_empty_merge_data_splits_without_templating(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.merge_data = {}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["personalizations"]), 2)
        self.assertNotIn("template_type", data["content"][0])

    def test_global_merge_does_not_split_to(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.merge_global_data = {"name": "global"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["personalizations"]), 1)
        self.assertEqual(len(data["personalizations"][0]["to"]), 2)
        self.assertEqual(
            data["personalizations"][0]["dynamic_template_data"], {"name": "global"}
        )

    def test_merge_headers_alone_split(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.merge_headers = {"two@example.com": {"X-Count": 2}}
        self.message.send()
        one, two = self.get_api_call_json()["personalizations"]
        self.assertNotIn("headers", one)
        self.assertEqual(two["headers"], {"X-Count": "2"})

    def test_reserved_merge_header(self):
        self.message.merge_headers = {"to@example.com": {"Message-ID": "<custom>"}}
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()
        self.assert_esp_not_called()

    def test_unsupported_extensions(self):
        options = {
            "metadata": {"secret": "value"},
            "merge_metadata": {"to@example.com": {"key": "value"}},
            "tags": ["tag"],
            "send_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
            "template_id": "stored-template",
        }
        for name, value in options.items():
            with self.subTest(name=name):
                message = AnymailMessage(
                    "Subject", "Body", "from@example.com", ["to@example.com"]
                )
                setattr(message, name, value)
                with self.assertRaisesMessage(AnymailUnsupportedFeature, name):
                    message.send()
        self.assert_esp_not_called()

    def test_esp_extra_merges_tracking(self):
        self.message.track_clicks = True
        self.message.esp_extra = {
            "campaign_id": "campaign-1",
            "tracking_settings": {"click_tracking": {"custom_domain_name": "clicks"}},
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["campaign_id"], "campaign-1")
        self.assertEqual(
            data["tracking_settings"]["click_tracking"],
            {"enable": True, "custom_domain_name": "clicks"},
        )

    def test_payload_serialization_repeatable(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.merge_data = {"one@example.com": {"name": "One"}}
        self.message.track_clicks = True
        self.message.esp_extra = {
            "tracking_settings": {"click_tracking": {"custom_domain_name": "clicks"}}
        }
        backend = get_default_mailer()
        payload = backend.build_message_payload(self.message, {})
        first = payload.serialize_data()
        self.assertEqual(first, payload.serialize_data())
        self.assertEqual(
            payload.data["tracking_settings"], {"click_tracking": {"enable": True}}
        )
        self.assertEqual(len(payload.data["personalizations"]), 1)

    def test_non_serializable(self):
        self.message.esp_extra = {"not_json": object()}
        with self.assertRaises(AnymailSerializationError):
            self.message.send()
        self.assert_esp_not_called()

    @override_settings(
        ANYMAIL={
            "MAILCHANNELS_API_KEY": "test_api_key",
            "IGNORE_UNSUPPORTED_FEATURES": True,
        }
    )
    def test_ignore_unsupported(self):
        self.message.metadata = {"key": "value"}
        self.message.extra_headers = {"Message-ID": "<custom>", "X-OK": "yes"}
        self.assertEqual(self.message.send(), 1)
        self.assertEqual(self.get_api_call_json()["headers"], {"X-OK": "yes"})
        self.assertNotIn("metadata", self.get_api_call_json())


@tag("mailchannels")
class MailChannelsErrorTests(MailChannelsBackendMockAPITestCase):
    def test_http_errors(self):
        for status in (200, 204, 400, 401, 403, 413, 429, 500, 503):
            with self.subTest(status=status):
                self.set_mock_response(
                    status_code=status, json_data={"errors": ["error"]}
                )
                with self.assertRaises(AnymailAPIError) as raised:
                    self.message.send()
                self.assertEqual(raised.exception.status_code, status)
        self.assertEqual(self.mock_request.call_count, 9)  # no retry

    def test_invalid_response(self):
        for raw in (
            b"not json",
            b"null",
            b"[]",
            b"{}",
            b'{"request_id":null}',
            b'{"request_id":"", "queued_at":"now"}',
            b'{"request_id":123,"queued_at":"now"}',
            b'{"request_id":"queue-123"}',
            b'{"request_id":"queue-123","queued_at":null}',
        ):
            with self.subTest(raw=raw):
                self.set_mock_response(raw=raw)
                with self.assertRaises(AnymailAPIError):
                    self.message.send()
        self.assertEqual(self.mock_request.call_count, 9)

    def test_timeout_no_retry(self):
        self.mock_request.side_effect = requests.Timeout("timeout")
        with self.assertRaises(AnymailAPIError):
            self.message.send()
        self.assertEqual(self.mock_request.call_count, 1)

    @ignore_fail_silently_warning()
    def test_fail_silently(self):
        self.set_mock_response(status_code=503)
        self.assertEqual(self.message.send(fail_silently=True), 0)
        self.assertEqual(self.mock_request.call_count, 1)

    def test_configuration_override(self):
        connection = mail.get_connection(
            api_key="other-key", api_url="https://proxy.example/tx/v1", timeout=12
        )
        self.message.connection = connection
        self.message.send()
        self.assert_esp_called("https://proxy.example/tx/v1/send-async")
        self.assertEqual(self.get_api_call_headers()["X-Api-Key"], "other-key")
        self.assertEqual(self.get_api_call_arg("timeout"), 12)

    @override_settings(
        MAILERS={"default": {"BACKEND": "anymail.backends.mailchannels.EmailBackend"}},
        ANYMAIL={},
    )
    def test_missing_api_key(self):
        with self.assertRaisesMessage(
            AnymailConfigurationError, "MAILCHANNELS_API_KEY"
        ):
            mail.get_connection()
        self.assert_esp_not_called()


@tag("mailchannels")
class MailChannelsSessionSharingTests(
    SessionSharingTestCases, MailChannelsBackendMockAPITestCase
):
    pass
