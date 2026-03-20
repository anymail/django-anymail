from __future__ import annotations

from unittest.mock import ANY

from django.core.mail import EmailMessage, send_mail
from django.test import ignore_warnings, override_settings, tag

from anymail.exceptions import AnymailConfigurationError, AnymailDeprecationWarning
from anymail.webhooks.sendinblue import (
    SendinBlueInboundWebhookView,
    SendinBlueTrackingWebhookView,
)

from .mock_requests_backend import RequestsBackendMockAPITestCase
from .webhook_cases import WebhookTestCase


@tag("brevo", "sendinblue")
@override_settings(
    EMAIL_BACKEND="anymail.backends.sendinblue.EmailBackend",
    ANYMAIL={"SENDINBLUE_API_KEY": "test_api_key"},
)
@ignore_warnings(category=AnymailDeprecationWarning)
class SendinBlueBackendDeprecationTests(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = (
        b'{"messageId":"<201801020304.1234567890@smtp-relay.mailin.fr>"}'
    )
    DEFAULT_STATUS_CODE = 201  # Brevo v3 uses '201 Created' for success (in most cases)

    def test_deprecation_warning(self):
        message = EmailMessage(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )
        with self.assertWarnsMessage(
            AnymailDeprecationWarning,
            "`anymail.backends.sendinblue.EmailBackend` has been renamed"
            " `anymail.backends.brevo.EmailBackend`.",
        ):
            message.send()
        self.assert_esp_called("https://api.brevo.com/v3/smtp/email")

    @override_settings(ANYMAIL={"BREVO_API_KEY": "test_api_key"})
    def test_missing_api_key_error_uses_correct_setting_name(self):
        # The sendinblue.EmailBackend requires SENDINBLUE_ settings names
        with self.assertRaisesMessage(AnymailConfigurationError, "SENDINBLUE_API_KEY"):
            send_mail("Subject", "Body", "from@example.com", ["to@example.com"])


@tag("brevo", "sendinblue")
@ignore_warnings(category=AnymailDeprecationWarning)
class SendinBlueTrackingWebhookDeprecationTests(WebhookTestCase):
    def test_deprecation_warning(self):
        with self.assertWarnsMessage(
            AnymailDeprecationWarning,
            "Anymail's SendinBlue webhook URLs are deprecated.",
        ):
            response = self.client.post(
                "/anymail/sendinblue/tracking/",
                content_type="application/json",
                data="{}",
            )
        self.assertEqual(response.status_code, 200)
        # Old url uses old names to preserve compatibility:
        self.assert_handler_called_once_with(
            self.tracking_handler,
            sender=SendinBlueTrackingWebhookView,  # *not* BrevoTrackingWebhookView
            event=ANY,
            esp_name="SendinBlue",  # *not* "Brevo"
        )

    def test_misconfigured_inbound(self):
        # Uses old esp_name when called on old URL
        errmsg = (
            "You seem to have set Brevo's *inbound* webhook URL"
            " to Anymail's SendinBlue *tracking* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client.post(
                "/anymail/sendinblue/tracking/",
                content_type="application/json",
                data={"items": []},
            )


@tag("brevo", "sendinblue")
@override_settings(ANYMAIL_SENDINBLUE_API_KEY="test-api-key")
@ignore_warnings(category=AnymailDeprecationWarning)
class SendinBlueInboundWebhookDeprecationTests(WebhookTestCase):
    def test_deprecation_warning(self):
        with self.assertWarnsMessage(
            AnymailDeprecationWarning,
            "Anymail's SendinBlue webhook URLs are deprecated.",
        ):
            response = self.client.post(
                "/anymail/sendinblue/inbound/",
                content_type="application/json",
                data='{"items":[{}]}',
            )
        self.assertEqual(response.status_code, 200)
        # Old url uses old names to preserve compatibility:
        self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=SendinBlueInboundWebhookView,  # *not* BrevoInboundWebhookView
            event=ANY,
            esp_name="SendinBlue",  # *not* "Brevo"
        )

    def test_misconfigured_tracking(self):
        # Uses old esp_name when called on old URL
        errmsg = (
            "You seem to have set Brevo's *tracking* webhook URL"
            " to Anymail's SendinBlue *inbound* webhook URL."
        )
        with self.assertRaisesMessage(AnymailConfigurationError, errmsg):
            self.client.post(
                "/anymail/sendinblue/inbound/",
                content_type="application/json",
                data={"event": "delivered"},
            )
