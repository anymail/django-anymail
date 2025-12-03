import datetime

from django.core import mail
from django.test import SimpleTestCase, override_settings, tag

from anymail.exceptions import (
    AnymailAPIError,
    AnymailConfigurationError,
    AnymailUnsupportedFeature,
)
from anymail.message import attach_inline_image_file

from .mock_requests_backend import (
    RequestsBackendMockAPITestCase,
    SessionSharingTestCases,
)
from .utils import (
    SAMPLE_IMAGE_FILENAME,
    decode_att,
    sample_image_content,
    sample_image_path,
)

# Minimal required ANYMAIL settings for Scaleway, used in multiple tests
SCALEWAY_BASE_SETTINGS = {
    "SCALEWAY_SECRET_KEY": "test_secret_key",
    "SCALEWAY_PROJECT_ID": "test_project_id",
}


@tag("scaleway")
@override_settings(
    EMAIL_BACKEND="anymail.backends.scaleway.EmailBackend",
    ANYMAIL=SCALEWAY_BASE_SETTINGS,
)
class ScalewayBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "emails": [
            {
                "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "message_id": "00000000-1111-2222-3333-444444444444",
                "project_id": "test-project-id",
                "mail_from": "from@example.com",
                "mail_rcpt": "to@example.com",
                "rcpt_type": "to",
                "status": "sending",
                "status_details": "ready to send",
                "created_at": "2025-08-05T01:12:20.016801Z",
                "updated_at": "2025-08-05T01:12:20.016801Z"
            }
        ]
    }"""
    DEFAULT_CONTENT_TYPE = "application/json"

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
        self.assert_esp_called(
            "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par/emails"
        )
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-Auth-Token"], "test_secret_key")
        data = self.get_api_call_json()
        self.assertEqual(data["project_id"], "test_project_id")
        self.assertEqual(data["subject"], "Subject here")
        self.assertEqual(data["text"], "Here is the message.")
        self.assertEqual(data["from"], {"email": "from@example.com"})
        self.assertEqual(data["to"], [{"email": "to@example.com"}])

    def test_name_addr(self):
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
        self.assertEqual(
            data["from"], {"name": "From Name", "email": "from@example.com"}
        )
        self.assertEqual(
            data["to"],
            [
                {"email": "to1@example.com", "name": "Recipient, #1"},
                {"email": "to2@example.com"},
            ],
        )
        self.assertEqual(
            data["cc"],
            [
                {"email": "cc1@example.com", "name": "Carbon Copy"},
                {"email": "cc2@example.com"},
            ],
        )
        self.assertEqual(
            data["bcc"],
            [
                {"email": "bcc1@example.com", "name": "Blind Copy"},
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

    def test_non_ascii_headers(self):
        # Scaleway correctly encodes non-ASCII display-names and most headers.
        # Anymail must handle RFC 2047 encoding for the constructed Reply-To header
        # and perform IDNA encoding for non-ASCII domain names.
        # Scaleway doesn't support EAI (see next test).
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
            data["from"],
            {
                "name": "Odesílatel, z adresy",
                "email": "from@xn--pklad-zsa96e.example.cz",
            },
        )
        self.assertEqual(
            data["to"],
            [
                {
                    "name": "Příjemce, na adresu",
                    "email": "to@xn--pklad-zsa96e.example.cz",
                }
            ],
        )
        self.assertEqual(data["subject"], "Předmět e-mailu")
        self.assertCountEqual(
            data["additional_headers"],
            [
                {"key": "X-Extra", "value": "Další"},
                {
                    "key": "Reply-To",
                    "value": "=?utf-8?b?T2Rwb3bEm8SPLCBhZHJlc2E=?="
                    " <reply@xn--pklad-zsa96e.example.cz>",
                },
            ],
        )

    def test_eai_unsupported(self):
        """
        Scaleway generates an undeliverable message (that seems to bounce or
        get dropped within Scaleway's own infrastructure) if any address header
        uses EAI. To prevent delivery problems, Anymail treats EAI as unsupported.
        """
        with self.subTest(field="from_email"):
            self.message.from_email = "тест@example.com"
            with self.assertRaisesMessage(
                AnymailUnsupportedFeature, "EAI in from_email"
            ):
                self.message.send()

        for field in ["to", "cc", "bcc", "reply_to"]:
            message = mail.EmailMultiAlternatives(
                "Subject", "Text Body", "from@example.com", ["to@example.com"]
            )
            with self.subTest(field=field):
                setattr(message, field, ["тест@example.com"])
                with self.assertRaisesMessage(
                    AnymailUnsupportedFeature, f"EAI in {field}"
                ):
                    message.send()

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(
            filename="test.txt", content=text_content, mimetype="text/plain"
        )
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["name"], "test.txt")
        self.assertEqual(data["attachments"][0]["type"], "text/plain")
        self.assertEqual(
            decode_att(data["attachments"][0]["content"]).decode(), text_content
        )

    def test_inline_images(self):
        # Scaleway's API doesn't have a way to specify content-id
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)

        cid = attach_inline_image_file(self.message, image_path)  # Read from a png file
        html_content = f'<p>This has an <img src="cid:{cid}" alt="inline" /> image.</p>'
        self.message.attach_alternative(html_content, "text/html")

        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline attachments"):
            self.message.send()

    @override_settings(ANYMAIL_IGNORE_UNSUPPORTED_FEATURES=True)
    def test_inline_images_ignore_unsupported(self):
        # Sends as ordinary attachment when ignoring unsupported features
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_content = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)  # Read from a png file
        html_content = f'<p>This has an <img src="cid:{cid}" alt="inline" /> image.</p>'
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["attachments"]), 1)
        self.assertEqual(data["attachments"][0]["name"], image_filename)
        self.assertEqual(data["attachments"][0]["type"], "image/png")
        self.assertEqual(
            decode_att(data["attachments"][0]["content"]),
            image_content,
        )

    def test_api_failure(self):
        self.set_mock_response(
            status_code=400, json_data={"message": "Helpful diagnostics from Scaleway"}
        )
        with self.assertRaisesMessage(
            AnymailAPIError, "Helpful diagnostics from Scaleway"
        ):
            self.message.send()


@tag("scaleway")
class ScalewayBackendAnymailFeatureTests(ScalewayBackendMockAPITestCase):
    def test_envelope_sender(self):
        self.message.envelope_sender = "anything@bounces.example.com"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "envelope_sender"):
            self.message.send()

    def test_metadata(self):
        self.message.metadata = {"user_id": "12345", "items": 6}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["additional_headers"]), 1)
        self.assertEqual(data["additional_headers"][0]["key"], "X-Metadata")
        self.assertJSONEqual(
            data["additional_headers"][0]["value"],
            {"user_id": "12345", "items": 6},
        )

    def test_send_at(self):
        self.message.send_at = datetime.datetime(
            2022, 5, 6, 7, 8, 9, tzinfo=datetime.timezone.utc
        )
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "send_at"):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt", "reorder test 12"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(len(data["additional_headers"]), 1)
        self.assertEqual(data["additional_headers"][0]["key"], "X-Tags")
        self.assertJSONEqual(
            data["additional_headers"][0]["value"],
            ["receipt", "reorder test 12"],
        )

    def test_headers_interaction(self):
        # Test four features that use custom headers don't clobber each other
        self.message.reply_to = ["reply@example.com"]
        self.message.extra_headers = {"X-Custom": "custom value"}
        self.message.metadata = {"user_id": "12345"}
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["additional_headers"],
            [
                {"key": "Reply-To", "value": "reply@example.com"},
                {"key": "X-Custom", "value": "custom value"},
                {"key": "X-Tags", "value": '["receipt"]'},
                {"key": "X-Metadata", "value": '{"user_id": "12345"}'},
            ],
        )

    def test_merge_data(self):
        self.message.merge_data = {"to@example.com": {"customer_id": "3"}}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "merge_data"):
            self.message.send()

    def test_merge_global_data(self):
        self.message.merge_global_data = {"customer_id": "3"}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "merge_global_data"):
            self.message.send()

    def test_merge_metadata(self):
        self.message.merge_metadata = {"to@example.com": {"tier": "premium"}}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "merge_metadata"):
            self.message.send()

    def test_template_id(self):
        self.message.template_id = "template-12345"
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "template_id"):
            self.message.send()

    def test_track_opens(self):
        self.message.track_opens = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_opens"):
            self.message.send()

    def test_track_clicks(self):
        self.message.track_clicks = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "track_clicks"):
            self.message.send()

    def test_esp_extra(self):
        self.message.esp_extra = {"send_before": "2022-05-06T07:08:09Z"}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["send_before"], "2022-05-06T07:08:09Z")

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent"""
        msg = mail.EmailMessage(
            "Subject",
            "Message",
            "from@example.com",
            ["Recipient <to1@example.com>"],
        )
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {"queued"})
        # Anymail's message_id is Scaleway's technical "id", which is unique per
        # recipient. (Not Scaleway's "message_id", which is shared across recipients.)
        self.assertEqual(
            msg.anymail_status.message_id,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(
            msg.anymail_status.recipients["to@example.com"].status, "queued"
        )
        self.assertEqual(
            msg.anymail_status.recipients["to@example.com"].message_id,
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        )
        self.assertEqual(
            msg.anymail_status.esp_response.content, self.DEFAULT_RAW_RESPONSE
        )

    def test_default_omits_unused_fields(self):
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("additional_headers", data)
        self.assertNotIn("attachments", data)
        self.assertNotIn("cc", data)
        self.assertNotIn("bcc", data)
        self.assertNotIn("html", data)


@tag("scaleway")
class ScalewayBackendRecipientsRefusedTests(ScalewayBackendMockAPITestCase):
    # Scaleway doesn't appear to check email bounce or complaint lists at time
    # of send -- it always just queues the message. You'll need to listen for
    # tracking webhook events to detect failed sends.
    pass


@tag("resend")
class ScalewayBackendSessionSharingTestCase(
    SessionSharingTestCases, ScalewayBackendMockAPITestCase
):
    """Requests session sharing tests"""

    pass  # tests are defined in SessionSharingTestCases


@tag("scaleway")
@override_settings(EMAIL_BACKEND="anymail.backends.scaleway.EmailBackend")
class ScalewayBackendConfigurationTests(SimpleTestCase):
    @override_settings(ANYMAIL={"SCALEWAY_PROJECT_ID": "test_project_id"})
    def test_missing_secret_key(self):
        with self.assertRaisesRegex(
            AnymailConfigurationError, r"You must set.*SCALEWAY_SECRET_KEY"
        ):
            mail.get_connection()

    @override_settings(ANYMAIL={"SCALEWAY_SECRET_KEY": "test_secret_key"})
    def test_missing_project_id(self):
        with self.assertRaisesRegex(
            AnymailConfigurationError, r"You must set.*SCALEWAY_PROJECT_ID"
        ):
            mail.get_connection()

    @override_settings(
        ANYMAIL={"SCALEWAY_PROJECT_ID": "test_project_id"},
        SCALEWAY_SECRET_KEY="test_secret_key",
    )
    def test_bare_secret_key(self):
        # SCALEWAY_SECRET_KEY is allowed in settings file root
        connection = mail.get_connection()
        self.assertEqual(connection.secret_key, "test_secret_key")

    @override_settings(ANYMAIL=dict(SCALEWAY_BASE_SETTINGS, SCALEWAY_REGION="pl-waw"))
    def test_region_setting(self):
        backend = mail.get_connection()
        self.assertEqual(
            backend.api_url,
            "https://api.scaleway.com/transactional-email/v1alpha1/regions/pl-waw/",
        )

    @override_settings(
        ANYMAIL=dict(SCALEWAY_BASE_SETTINGS, SCALEWAY_REGION="nl-ams # from /.env")
    )
    def test_bad_region_setting(self):
        # Make sure api_url is properly quoted
        # (e.g., misread from an env file that doesn't allow comments)
        backend = mail.get_connection()
        self.assertEqual(
            backend.api_url,
            "https://api.scaleway.com/transactional-email/v1alpha1"
            "/regions/nl-ams%20%23%20from%20%2F.env/",
        )

    @override_settings(
        ANYMAIL=dict(
            SCALEWAY_BASE_SETTINGS,
            SCALEWAY_API_URL="https://scaleway.example.com/{region}/email",
        )
    )
    def test_api_url_setting(self):
        # The {region} placeholder is replaced with the region setting
        backend = mail.get_connection()
        self.assertEqual(backend.api_url, "https://scaleway.example.com/fr-par/email/")

    @override_settings(
        ANYMAIL=dict(
            SCALEWAY_BASE_SETTINGS,
            SCALEWAY_API_URL="https://scaleway.example.com/email",
        )
    )
    def test_api_url_setting_without_region(self):
        # The region placeholder is not required
        backend = mail.get_connection()
        self.assertEqual(backend.api_url, "https://scaleway.example.com/email/")
