from decimal import Decimal

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import (
    AnymailAPIError,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from anymail.message import attach_inline_image

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import (
    AnymailTestMixin,
    create_text_attachment,
    decode_att,
    sample_image_content,
)


@tag("postal")
@override_settings(
    EMAIL_BACKEND="anymail.backends.postal.EmailBackend",
    ANYMAIL={
        "POSTAL_API_KEY": "test_server_token",
        "POSTAL_API_URL": "https://postal.example.com",
    },
)
class PostalBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "status": "success",
        "time": 2.82,
        "flags": {},
        "data": {
            "message_id": "ad5084a6-cf01-448b-92da-2574ee64c0ba@rp.postal.example.com",
            "messages": {
                "to@example.com": { "id": 1503, "token": "ke47R2hZkSlA" }
            }
        }
    }"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives(
            "Subject", "Text Body", "from@example.com", ["to@example.com"]
        )


@tag("postal")
class PostalBackendStandardEmailTests(PostalBackendMockAPITestCase):
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
        self.assert_esp_called("/message")
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-Server-API-Key"], "test_server_token")
        data = self.get_api_call_json()
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["plain_body"], "Here is the message.")
        self.assertEqual(data["from"], "from@sender.example.com")
        self.assertEqual(data["to"], ["to@example.com"])

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
        self.assertEqual(
            data["to"], ["Recipient #1 <to1@example.com>", "to2@example.com"]
        )
        self.assertEqual(
            data["cc"], ["Carbon Copy <cc1@example.com>", "cc2@example.com"]
        )
        self.assertEqual(
            data["bcc"], ["Blind Copy <bcc1@example.com>", "bcc2@example.com"]
        )

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
        self.assertEqual(data["subject"], "Subject")
        self.assertEqual(data["plain_body"], "Body goes here")
        self.assertEqual(data["from"], "from@example.com")
        self.assertEqual(data["to"], ["to1@example.com", "Also To <to2@example.com>"])
        self.assertEqual(
            data["bcc"], ["bcc1@example.com", "Also BCC <bcc2@example.com>"]
        )
        self.assertEqual(data["cc"], ["cc1@example.com", "Also CC <cc2@example.com>"])
        self.assertEqual(data["reply_to"], "another@example.com")
        self.assertCountEqual(
            data["headers"],
            {"Message-ID": "mycustommsgid@sales.example.com", "X-MyHeader": "my value"},
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
        self.assertEqual(data["plain_body"], text_content)
        self.assertEqual(data["html_body"], html_content)
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
        self.assertNotIn("plain_body", data)
        self.assertEqual(data["html_body"], html_content)

    def test_extra_headers(self):
        self.message.extra_headers = {"X-Custom": "string", "X-Num": 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(data["headers"], {"X-Custom": "string", "X-Num": 123})

    def test_extra_headers_serialization_error(self):
        self.message.extra_headers = {"X-Custom": Decimal(12.5)}
        with self.assertRaisesMessage(AnymailSerializationError, "Decimal"):
            self.message.send()

    @override_settings(ANYMAIL_IGNORE_UNSUPPORTED_FEATURES=True)
    def test_reply_to(self):
        # Postal only allows single reply-to. Test handling for multiple reply
        # addresses when ignoring errors:
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["reply@example.com", "Other <reply2@example.com>"],
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data["reply_to"], "reply@example.com")  # keeps first email

    def test_multiple_reply_to(self):
        email = mail.EmailMessage(
            "Subject",
            "Body goes here",
            "from@example.com",
            ["to1@example.com"],
            reply_to=["reply@example.com", "Other <reply2@example.com>"],
        )
        with self.assertRaises(AnymailUnsupportedFeature):
            email.send()

    def test_non_ascii_headers(self):
        # Postal is believed to handle RFC 2047 encoding in headers,
        # but Anymail applies IDNA encoding for non-ASCII domain names.
        email = mail.EmailMessage(
            from_email='"Odesílatel, z adresy" <from@příklad.example.cz>',
            to=['"Příjemce, na adresu" <to@příklad.example.cz>'],
            subject="Předmět e-mailu",
            reply_to=['"Odpověď, adresa" <reply@příklad.example.cz>'],
            headers={"X-Extra": "Další"},
            body="Prostý text",
        )
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(
            data["from"], '"Odesílatel, z adresy" <from@xn--pklad-zsa96e.example.cz>'
        )
        self.assertEqual(
            data["to"], ['"Příjemce, na adresu" <to@xn--pklad-zsa96e.example.cz>']
        )
        self.assertEqual(data["subject"], "Předmět e-mailu")
        self.assertEqual(
            data["reply_to"], '"Odpověď, adresa" <reply@xn--pklad-zsa96e.example.cz>'
        )
        self.assertEqual(data["headers"], {"X-Extra": "Další"})

    def test_attachments(self):
        # Postal's API is believed to support charset in the content_type param
        # and non-ASCII filenames, but has not specifically been tested.
        # Postal does not support inline images.
        text_content = "pièce jointe\n"
        self.message.attach(
            create_text_attachment("pièce jointe\n", charset="iso-8859-1")
        )
        self.message.attach("émoticône.img", b";-)", "image/x-emoticon")

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(
            attachments[0]["content_type"], 'text/plain; charset="iso-8859-1"'
        )
        self.assertEqual(attachments[0]["name"], "")  # no filename
        self.assertEqual(
            decode_att(attachments[0]["data"]).decode("iso-8859-1"), text_content
        )
        self.assertEqual(attachments[1]["content_type"], "image/x-emoticon")
        self.assertEqual(attachments[1]["name"], "émoticône.img")
        self.assertEqual(decode_att(attachments[1]["data"]), b";-)")

    def test_embedded_images(self):
        attach_inline_image(self.message, sample_image_content(), "test.png")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline attachments"):
            self.message.send()

    def test_multiple_html_alternatives(self):
        # Multiple alternatives not allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>But not second html</p>", "text/html")
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple html parts"):
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

    def test_api_failure(self):
        failure_response = b"""{
            "status": "error",
            "time": 0.0,
            "flags": {},
            "data": {
                "code": "ValidationError"
            }
        }"""
        self.set_mock_response(status_code=200, raw=failure_response)
        with self.assertRaisesMessage(AnymailAPIError, "Postal API response 200"):
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])

        # Make sure fail_silently is respected
        self.set_mock_response(status_code=200, raw=failure_response)
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
            "status": "error",
            "time": 0.0,
            "flags": {},
            "data": {
                "code": "ValidationError"
            }
        }"""
        self.set_mock_response(status_code=200, raw=error_response)
        with self.assertRaisesMessage(AnymailAPIError, "ValidationError"):
            self.message.send()

        # Non-JSON error response:
        self.set_mock_response(status_code=500, raw=b"Ack! Bad proxy!")
        with self.assertRaisesMessage(AnymailAPIError, "Ack! Bad proxy!"):
            self.message.send()

        # No content in the error response:
        self.set_mock_response(status_code=502, raw=None)
        with self.assertRaises(AnymailAPIError):
            self.message.send()


@tag("postal")
class PostalBackendAnymailFeatureTests(PostalBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "anything@bounces.example.com"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["sender"], "anything@bounces.example.com")

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "metadata"):
            self.message.send()

    def test_send_at(self):
        self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["tag"], "receipt")

        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "multiple tags"):
            self.message.send()

    def test_track_opens(self):
        self.message.track_opens = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_opens"):
            self.message.send()

    def test_track_clicks(self):
        self.message.track_clicks = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_clicks"):
            self.message.send()

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("tag", data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            "future_postal_option": "some-value",
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["future_postal_option"], "some-value")

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        response_content = b"""{
          "status": "success",
          "time": 1.08,
          "flags": {},
          "data": {
            "message_id": "9dfcc4df-09a6-4f1d-b535-0eb0a9f104a4@postal.example.com",
            "messages": {
              "to1@example.com": { "id": 1531, "token": "xLcafDRCVUFe" }
            }
          }
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
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(msg.anymail_status.message_id, 1531)
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to1@example.com"].message_id, 1531
        )
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    # noinspection PyUnresolvedReferences
    def test_send_without_to_attaches_anymail_status(self):
        """The anymail_status should be attached even if there are no `to` recipients"""
        response_content = b"""{
          "status": "success",
          "time": 1.08,
          "flags": {},
          "data": {
            "message_id": "9dfcc4df-09a6-4f1d-b535-0eb0a9f104a4@postal.example.com",
            "messages": {
              "cc@example.com": { "id": 1531, "token": "xLcafDRCVUFe" }
            }
          }
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
        self.assertEqual(msg.anymail_status.status, {"queued"})
        self.assertEqual(msg.anymail_status.message_id, 1531)
        self.assertEqual(
            msg.anymail_status.recipients["cc@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["cc@example.com"].message_id, 1531
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
        self.assertIn("Don't know how to send this data to Postal", str(err))
        # original message:
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")


@tag("postal")
class PostalBackendRecipientsRefusedTests(PostalBackendMockAPITestCase):
    # Postal doesn't check email bounce or complaint lists at time of send --
    # it always just queues the message. You'll need to listen for the "rejected"
    # and "failed" events to detect refused recipients.
    pass


@tag("postal")
class PostalBackendSessionSharingTestCase(
    SessionSharingTestCases, PostalBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("postal")
@override_settings(EMAIL_BACKEND="anymail.backends.postal.EmailBackend")
class PostalBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r"\bPOSTAL_API_KEY\b")
        self.assertRegex(errmsg, r"\bANYMAIL_POSTAL_API_KEY\b")
