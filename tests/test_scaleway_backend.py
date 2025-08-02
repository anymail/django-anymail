from django.core import mail
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import AnymailAPIError, AnymailConfigurationError

from .mock_requests_backend import RequestsBackendMockAPITestCase


@tag("scaleway")
@override_settings(
    EMAIL_BACKEND="anymail.backends.scaleway.EmailBackend",
    ANYMAIL={
        "SCALEWAY_SECRET_KEY": "test_secret_key",
        "SCALEWAY_PROJECT_ID": "test_project_id",
    },
)
class ScalewayBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "emails": [
            {
                "id": "b7c6a8c1-19a4-49d8-9293-41835462ce81",
                "message_id": "<b7c6a8c1-19a4-49d8-9293-41835462ce81@example.com>",
                "project_id": "a4f7b3e2-1b3a-4b3c-9c1a-1a2b3c4d5e6f",
                "mail_from": "from@example.com",
                "mail_rcpt": "to@example.com",
                "rcpt_type": "to",
                "status": "new",
                "status_details": "Email is new",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": "2023-01-01T00:00:00Z"
            }
        ]
    }"""

    def setUp(self):
        super().setUp()
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("scaleway")
class ScalewayBackendStandardEmailTests(ScalewayBackendMockAPITestCase):
    def test_send_mail(self):
        mail.send_mail(
            "Subject here",
            "Here is the message.",
            "from@example.com",
            ["to@example.com"],
            fail_silently=False,
        )
        self.assert_esp_called("/emails")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-Auth-Token"], "test_secret_key")
        data = self.get_api_call_json()
        self.assertEqual(data["project_id"], "test_project_id")
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["text"], "Here is the message.")
        self.assertEqual(data["from"]["email"], "from@example.com")
        self.assertEqual(data["to"][0]["email"], "to@example.com")

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

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(
            filename="test.txt", content=text_content, mimetype="text/plain"
        )
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["name"], "test.txt")

    def test_api_failure(self):
        self.set_mock_response(status_code=400)
        with self.assertRaisesMessage(AnymailAPIError, "Scaleway API response 400"):
            self.message.send()


@tag("scaleway")
class ScalewayBackendAnymailFeatureTests(ScalewayBackendMockAPITestCase):
    def test_extra_headers(self):
        self.message.extra_headers = {"X-Custom": "string", "X-Num": 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["additional_headers"],
            [{"key": "X-Custom", "value": "string"}, {"key": "X-Num", "value": "123"}],
        )

    def test_reply_to(self):
        self.message.reply_to = ["reply@example.com"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["additional_headers"],
            [{"key": "Reply-To", "value": "reply@example.com"}],
        )

    def test_reply_to_and_extra_headers(self):
        self.message.reply_to = ["reply@example.com"]
        self.message.extra_headers = {"X-Custom": "string"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["additional_headers"],
            [
                {"key": "X-Custom", "value": "string"},
                {"key": "Reply-To", "value": "reply@example.com"},
            ],
        )


@tag("scaleway")
@override_settings(
    EMAIL_BACKEND="anymail.backends.scaleway.EmailBackend",
    ANYMAIL={"SCALEWAY_SECRET_KEY": "test_secret_key"},
)
class ScalewayBackendImproperlyConfiguredTests(SimpleTestCase):
    def test_missing_project_id(self):
        with self.assertRaises(AnymailConfigurationError):
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])


@tag("scaleway")
@override_settings(EMAIL_BACKEND="anymail.backends.scaleway.EmailBackend")
class ScalewayBackendMissingApiKeyTests(SimpleTestCase):
    def test_missing_api_key(self):
        with self.assertRaises(AnymailConfigurationError):
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
