from django.core import checks
from django.test import SimpleTestCase
from django.test.utils import override_settings

from anymail.checks import check_deprecated_settings, check_insecure_settings

from .utils import AnymailTestMixin


class DeprecatedSettingsTests(AnymailTestMixin, SimpleTestCase):
    @override_settings(ANYMAIL={"WEBHOOK_AUTHORIZATION": "abcde:12345"})
    def test_webhook_authorization(self):
        errors = check_deprecated_settings(None)
        self.assertEqual(
            errors,
            [
                checks.Error(
                    "The ANYMAIL setting 'WEBHOOK_AUTHORIZATION' has been renamed"
                    " 'WEBHOOK_SECRET' to improve security.",
                    hint="You must update your settings.py.",
                    id="anymail.E001",
                )
            ],
        )

    @override_settings(ANYMAIL_WEBHOOK_AUTHORIZATION="abcde:12345", ANYMAIL={})
    def test_anymail_webhook_authorization(self):
        errors = check_deprecated_settings(None)
        self.assertEqual(
            errors,
            [
                checks.Error(
                    "The ANYMAIL_WEBHOOK_AUTHORIZATION setting has been renamed"
                    " ANYMAIL_WEBHOOK_SECRET to improve security.",
                    hint="You must update your settings.py.",
                    id="anymail.E001",
                )
            ],
        )


class InsecureSettingsTests(AnymailTestMixin, SimpleTestCase):
    @override_settings(ANYMAIL={"DEBUG_API_REQUESTS": True})
    def test_debug_api_requests_deployed(self):
        errors = check_insecure_settings(None)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "anymail.W002")

    @override_settings(ANYMAIL={"DEBUG_API_REQUESTS": True}, DEBUG=True)
    def test_debug_api_requests_debug(self):
        errors = check_insecure_settings(None)
        self.assertEqual(len(errors), 0)  # no warning in DEBUG (non-production) config
