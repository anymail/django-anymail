from datetime import datetime, timezone
from decimal import Decimal

from django.core import mail
from django.test import SimpleTestCase, tag

from anymail.backends.smtp2go import EmailBackend
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
    AnymailTestMixin,
    decode_att,
    ignore_fail_silently_warning,
    override_settings,
    sample_image_content,
)


@tag("smtp2go")
@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "anymail.backends.smtp2go.EmailBackend",
            "OPTIONS": {"api_key": "test_api_key"},
        }
    }
)
class SMTP2GOBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "request_id": "aa253464-0bd0-467a-b24b-6159dcd7be60",
        "data": {"succeeded": 1, "failed": 0, "failures": [],
                 "email_id": "1u0SwL-B9zBpi9ffUq-JAB2"}
    }"""

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )


class SMTP2GOBackendStandardEmailTests(SMTP2GOBackendMockAPITestCase):
    def test_send_mail(self):
        self.assertEqual(
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"]),
            1,
        )
        self.assert_esp_called("https://api.smtp2go.com/v3/email/send")
        self.assertEqual(
            self.get_api_call_headers()["X-Smtp2go-Api-Key"], "test_api_key"
        )
        self.assertEqual(
            self.get_api_call_json(),
            {
                "sender": "from@example.com",
                "to": ["to@example.com"],
                "subject": "Subject",
                "text_body": "Body",
                "fastaccept": True,
            },
        )

    def test_address_headers(self):
        self.message.from_email = '"From, Name" <from@example.com>'
        self.message.to = ["To Name <to@example.com>", "other@example.com"]
        self.message.cc = ["Copy <cc@example.com>"]
        self.message.bcc = ["bcc@example.com"]
        self.message.reply_to = ["Reply <reply@example.com>", "other-reply@example.com"]
        self.message.extra_headers = {"X-Custom": "value", "X-Number": 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["sender"], '"From, Name" <from@example.com>')
        self.assertEqual(data["to"], ["To Name <to@example.com>", "other@example.com"])
        self.assertEqual(data["cc"], ["Copy <cc@example.com>"])
        self.assertEqual(data["bcc"], ["bcc@example.com"])
        self.assertEqual(
            data["custom_headers"],
            [
                {
                    "header": "Reply-To",
                    "value": "Reply <reply@example.com>, other-reply@example.com",
                },
                {"header": "X-Custom", "value": "value"},
                {"header": "X-Number", "value": "123"},
            ],
        )
        self.assertEqual(
            set(self.message.anymail_status.recipients),
            {
                "to@example.com",
                "other@example.com",
                "cc@example.com",
                "bcc@example.com",
            },
        )

    def test_unicode(self):
        self.message.from_email = "Thé Sender <from@例え.テスト>"
        self.message.to = ["Réçipient <to@例え.テスト>"]
        self.message.subject = "Résumé"
        self.message.body = "Unicode body ✓"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["sender"], "Thé Sender <from@xn--r8jz45g.xn--zckzah>")
        self.assertEqual(data["to"], ["Réçipient <to@xn--r8jz45g.xn--zckzah>"])
        self.assertEqual(data["subject"], "Résumé")
        self.assertEqual(data["text_body"], "Unicode body ✓")

    def test_html(self):
        self.message.attach_alternative("<p>Body</p>", "text/html")
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["text_body"], "Body")
        self.assertEqual(data["html_body"], "<p>Body</p>")
        self.assertNotIn("attachments", data)

    def test_html_only(self):
        self.message.body = "<p>Body</p>"
        self.message.content_subtype = "html"
        self.message.send()
        self.assertNotIn("text_body", self.get_api_call_json())
        self.assertEqual(self.get_api_call_json()["html_body"], "<p>Body</p>")

    def test_attachments(self):
        self.message.attach("résumé.txt", "Résumé", "text/plain")
        self.message.attach("image.png", sample_image_content(), "image/png")
        cid = attach_inline_image(
            self.message, sample_image_content(), filename="logo.png"
        )
        self.message.attach_alternative(f'<img src="cid:{cid}">', "text/html")
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["attachments"][0]["filename"], "résumé.txt")
        self.assertEqual(
            decode_att(data["attachments"][0]["fileblob"]).decode(), "Résumé"
        )
        self.assertEqual(
            decode_att(data["attachments"][1]["fileblob"]), sample_image_content()
        )
        self.assertEqual(data["inlines"][0]["filename"], cid)
        self.assertEqual(data["inlines"][0]["mimetype"], "image/png")
        self.assertEqual(
            decode_att(data["inlines"][0]["fileblob"]), sample_image_content()
        )

    def test_no_recipients(self):
        self.message.to = []
        self.assertEqual(self.message.send(), 0)
        self.assert_esp_not_called()

    def test_bcc_only(self):
        self.message.to = []
        self.message.bcc = ["hidden@example.com"]
        self.message.send()
        self.assertEqual(self.get_api_call_json()["to"], [])
        self.assertEqual(self.get_api_call_json()["bcc"], ["hidden@example.com"])
        self.assertEqual(
            set(self.message.anymail_status.recipients), {"hidden@example.com"}
        )

    def test_multiple_html_parts(self):
        self.message.attach_alternative("<p>one</p>", "text/html")
        self.message.attach_alternative("<p>two</p>", "text/html")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()
        self.assert_esp_not_called()

    def test_alternative(self):
        self.message.attach_alternative("calendar", "text/calendar")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()


class SMTP2GOBackendAnymailFeatureTests(SMTP2GOBackendMockAPITestCase):
    def test_send_status(self):
        self.message.send()
        self.assertEqual(self.message.anymail_status.status, {"queued"})
        self.assertEqual(
            self.message.anymail_status.message_id, "1u0SwL-B9zBpi9ffUq-JAB2"
        )
        self.assertEqual(self.message.anymail_status.esp_response.status_code, 200)

    def test_schedule(self):
        self.message.send_at = datetime(2026, 10, 7, 12, 34, 56, tzinfo=timezone.utc)
        self.set_mock_response(json_data={"data": {"schedule_id": "schedule-123"}})
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["schedule"], "2026-10-07 12:34:56 +0000"
        )
        self.assertEqual(self.message.anymail_status.message_id, "schedule-123")

    def test_template(self):
        self.message.template_id = "welcome"
        self.message.merge_global_data = {"name": "Customer", "number": 42}
        self.message.send()
        self.assertEqual(self.get_api_call_json()["template_id"], "welcome")
        self.assertEqual(
            self.get_api_call_json()["template_data"],
            {"name": "Customer", "number": 42},
        )

    def test_batch(self):
        self.message.to = ["One <one@example.com>", "two@example.com"]
        self.message.cc = ["cc@example.com"]
        self.message.bcc = ["bcc@example.com"]
        self.message.template_id = "welcome"
        self.message.merge_global_data = {"name": "Customer", "number": 42}
        self.message.merge_data = {"one@example.com": {"name": "One"}}
        self.message.extra_headers = {"X-Common": "common", "X-Custom": "default"}
        self.message.merge_headers = {"one@example.com": {"X-Custom": "one"}}
        self.set_mock_response(
            json_data={"data": [{"email_id": "id-1"}, {"email_id": "id-2"}]}
        )
        self.message.send()
        self.assert_esp_called("https://api.smtp2go.com/v3/email/batch")
        first, second = self.get_api_call_json()["emails"]
        self.assertEqual(first["to"], ["One <one@example.com>"])
        self.assertEqual(second["to"], ["two@example.com"])
        self.assertEqual(first["template_data"], {"name": "One", "number": 42})
        self.assertEqual(second["template_data"], {"name": "Customer", "number": 42})
        for item in [first, second]:
            self.assertEqual(item["cc"], ["cc@example.com"])
            self.assertEqual(item["bcc"], ["bcc@example.com"])
        self.assertIn({"header": "X-Custom", "value": "one"}, first["custom_headers"])
        self.assertIn(
            {"header": "X-Custom", "value": "default"}, second["custom_headers"]
        )
        self.assertEqual(
            self.message.anymail_status.recipients["one@example.com"].message_id, "id-1"
        )
        self.assertEqual(
            self.message.anymail_status.recipients["two@example.com"].message_id, "id-2"
        )

    def test_empty_merge_data_still_batches(self):
        self.message.merge_data = {}
        self.set_mock_response(json_data={"data": [{"email_id": "id-1"}]})
        self.message.send()
        self.assert_esp_called("email/batch")
        self.assertEqual(len(self.get_api_call_json()["emails"]), 1)

    @override_settings(
        ANYMAIL={
            "SMTP2GO_API_KEY": "test_api_key",
            "SEND_DEFAULTS": {
                "template_id": "welcome",
                "merge_global_data": {"name": "Default", "shared": 1},
            },
            "SMTP2GO_SEND_DEFAULTS": {
                "merge_global_data": {"name": "SMTP2GO default", "esp": 2}
            },
        }
    )
    def test_send_defaults(self):
        self.message.merge_global_data = {"name": "Message"}
        self.message.send()
        self.assertEqual(
            self.get_api_call_json()["template_data"], {"name": "Message", "esp": 2}
        )

        self.assertEqual(self.get_api_call_json()["template_id"], "welcome")

    def test_batch_schedule_ids(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.merge_data = {}
        self.message.send_at = datetime(2026, 10, 7, tzinfo=timezone.utc)
        self.set_mock_response(
            json_data={
                "data": [
                    {"schedule_id": "schedule-1"},
                    {"schedule_id": "schedule-2"},
                ]
            }
        )
        self.message.send()
        self.assertEqual(
            self.message.anymail_status.message_id, {"schedule-1", "schedule-2"}
        )
        for item in self.get_api_call_json()["emails"]:
            self.assertEqual(item["schedule"], "2026-10-07 00:00:00 +0000")

    def test_esp_extra(self):
        self.message.esp_extra = {
            "fastaccept": False,
            "custom_headers": [{"header": "X-Extra", "value": "yes"}],
        }
        self.message.send()
        self.assertFalse(self.get_api_call_json()["fastaccept"])
        self.assertEqual(
            self.get_api_call_json()["custom_headers"],
            [{"header": "X-Extra", "value": "yes"}],
        )

    def test_unsupported_features(self):
        for attr, value in {
            "tags": ["tag"],
            "metadata": {"key": "value"},
            "merge_metadata": {"to@example.com": {"key": "value"}},
            "track_clicks": True,
            "track_opens": False,
            "envelope_sender": "bounce@example.com",
        }.items():
            with self.subTest(attr=attr):
                message = AnymailMessage(
                    "Subject", "Body", "from@example.com", ["to@example.com"]
                )
                setattr(message, attr, value)
                with self.assertRaises(AnymailUnsupportedFeature):
                    message.send()
        self.assert_esp_not_called()

    @override_settings(
        ANYMAIL={"SMTP2GO_API_KEY": "test_api_key", "IGNORE_UNSUPPORTED_FEATURES": True}
    )
    def test_ignore_unsupported(self):
        self.message.tags = ["tag"]
        self.message.send()
        self.assertNotIn("tags", self.get_api_call_json())

    def test_serialization_error(self):
        self.message.merge_global_data = {"decimal": Decimal("1.2")}
        with self.assertRaises(AnymailSerializationError):
            self.message.send()
        self.assert_esp_not_called()


class SMTP2GOBackendAPIFailureTests(SMTP2GOBackendMockAPITestCase):
    def test_http_error(self):
        self.set_mock_response(
            status_code=400, json_data={"data": {"error": "Bad API key"}}
        )
        with self.assertRaisesMessage(AnymailAPIError, "Bad API key"):
            self.message.send()

    def test_processing_errors(self):
        for data in [
            {"error": "Not authorized"},
            {"error_code": "DENIED"},
            {"email_id": "id", "failed": 1, "failures": ["Rejected"]},
            {"email_id": "id", "failures": ["Rejected"]},
        ]:
            with self.subTest(data=data):
                self.set_mock_response(json_data={"data": data})
                with self.assertRaises(AnymailAPIError) as cm:
                    self.message.send()
                self.assertEqual(cm.exception.status_code, 200)
                self.assertIs(cm.exception.email_message, self.message)

    def test_invalid_responses(self):
        for data in [
            {},
            {"data": {}},
            {"data": []},
            {"data": None},
            [],
            {"data": {"email_id": 123}},
        ]:
            with self.subTest(data=data):
                self.set_mock_response(json_data=data)
                with self.assertRaisesMessage(
                    AnymailAPIError, "Invalid SMTP2GO API response"
                ):
                    self.message.send()

    def test_invalid_json(self):
        self.set_mock_response(raw=b"Not JSON")
        with self.assertRaisesMessage(AnymailAPIError, "Invalid JSON"):
            self.message.send()

    def test_fastaccept_response(self):
        self.set_mock_response(json_data={"data": {"email_id": "accepted-id"}})
        self.message.send()
        self.assertEqual(self.message.anymail_status.message_id, "accepted-id")

    def test_batch_response_count(self):
        self.message.merge_data = {}
        self.set_mock_response(json_data={"data": []})
        with self.assertRaises(AnymailAPIError):
            self.message.send()

    def test_batch_item_error(self):
        self.message.to = ["one@example.com", "two@example.com"]
        self.message.merge_data = {}
        self.set_mock_response(
            json_data={"data": [{"email_id": "id-1"}, {"error": "Rejected"}]}
        )
        with self.assertRaisesMessage(AnymailAPIError, "Rejected"):
            self.message.send()

    @ignore_fail_silently_warning()
    def test_fail_silently(self):
        self.set_mock_response(status_code=500)
        self.assertEqual(self.message.send(fail_silently=True), 0)


@tag("smtp2go")
class SMTP2GOBackendSettingsTests(AnymailTestMixin, SimpleTestCase):
    @override_settings(ANYMAIL={"SMTP2GO_API_KEY": "settings-key"})
    def test_settings(self):
        backend = EmailBackend()
        self.assertEqual(backend.api_key, "settings-key")
        self.assertEqual(backend.api_url, "https://api.smtp2go.com/v3/")

    @override_settings(SMTP2GO_API_KEY="bare-key")
    def test_bare_setting(self):
        self.assertEqual(EmailBackend().api_key, "bare-key")

    @override_settings(ANYMAIL={"SMTP2GO_API_KEY": "settings-key"})
    def test_options_override_settings(self):
        backend = EmailBackend(
            api_key="option-key", api_url="https://eu-api.smtp2go.com/v3"
        )
        self.assertEqual(backend.api_key, "option-key")
        self.assertEqual(backend.api_url, "https://eu-api.smtp2go.com/v3/")

    def test_missing_api_key(self):
        with self.assertRaises(AnymailConfigurationError):
            EmailBackend()


class SMTP2GOBackendSessionSharingTests(
    SessionSharingTestCases, SMTP2GOBackendMockAPITestCase
):
    pass
