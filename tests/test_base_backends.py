from django.test import SimpleTestCase, override_settings, tag

from anymail.backends.base_requests import AnymailRequestsBackend, RequestsPayload
from anymail.message import AnymailMessage, AnymailRecipientStatus
from tests.utils import AnymailTestMixin

from .mock_requests_backend import RequestsBackendMockAPITestCase


class MinimalRequestsBackend(AnymailRequestsBackend):
    """(useful only for these tests)"""

    esp_name = "Example"
    api_url = "https://httpbin.org/post"  # helpful echoback endpoint for live testing

    def __init__(self, **kwargs):
        super().__init__(self.api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        _payload_init = getattr(message, "_payload_init", {})
        return MinimalRequestsPayload(message, defaults, self, **_payload_init)

    def parse_recipient_status(self, response, payload, message):
        return {"to@example.com": AnymailRecipientStatus("message-id", "sent")}


class MinimalRequestsPayload(RequestsPayload):
    def init_payload(self):
        pass

    def _noop(self, *args, **kwargs):
        pass

    set_from_email = _noop
    set_recipients = _noop
    set_subject = _noop
    set_reply_to = _noop
    set_extra_headers = _noop
    set_text_body = _noop
    set_html_body = _noop
    add_attachment = _noop


@override_settings(EMAIL_BACKEND="tests.test_base_backends.MinimalRequestsBackend")
class RequestsBackendBaseTestCase(RequestsBackendMockAPITestCase):
    """Test common functionality in AnymailRequestsBackend"""

    def setUp(self):
        super().setUp()
        self.message = AnymailMessage(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )

    def test_minimal_requests_backend(self):
        """Make sure the testing backend defined above actually works"""
        self.message.send()
        self.assert_esp_called("https://httpbin.org/post")

    def test_timeout_default(self):
        """All requests have a 30 second default timeout"""
        self.message.send()
        timeout = self.get_api_call_arg("timeout")
        self.assertEqual(timeout, 30)

    @override_settings(ANYMAIL_REQUESTS_TIMEOUT=5)
    def test_timeout_setting(self):
        """You can use the Anymail setting REQUESTS_TIMEOUT to override the default"""
        self.message.send()
        timeout = self.get_api_call_arg("timeout")
        self.assertEqual(timeout, 5)


@tag("live")
@override_settings(EMAIL_BACKEND="tests.test_base_backends.MinimalRequestsBackend")
class RequestsBackendLiveTestCase(AnymailTestMixin, SimpleTestCase):
    @override_settings(ANYMAIL_DEBUG_API_REQUESTS=True)
    def test_debug_logging(self):
        message = AnymailMessage(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )
        message._payload_init = dict(
            data="Request body",
            headers={
                "Content-Type": "text/plain",
                "Accept": "application/json",
            },
        )
        with self.assertPrints("===== Anymail API request") as outbuf:
            message.send()

        # Header order and response data vary too much to do a full comparison,
        # but make sure that the output contains some expected pieces of the request
        # and the response
        output = outbuf.getvalue()
        self.assertIn("\nPOST https://httpbin.org/post\n", output)
        self.assertIn("\nUser-Agent: django-anymail/", output)
        self.assertIn("\nAccept: application/json\n", output)
        self.assertIn("\nContent-Type: text/plain\n", output)  # request
        self.assertIn("\n\nRequest body\n", output)
        self.assertIn("\n----- Response\n", output)
        self.assertIn("\nHTTP 200 OK\n", output)
        self.assertIn("\nContent-Type: application/json\n", output)  # response

    def test_no_debug_logging(self):
        # Make sure it doesn't output anything when DEBUG_API_REQUESTS is not set
        message = AnymailMessage(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )
        message._payload_init = dict(
            data="Request body",
            headers={
                "Content-Type": "text/plain",
                "Accept": "application/json",
            },
        )
        with self.assertPrints("", match="equal"):
            message.send()
