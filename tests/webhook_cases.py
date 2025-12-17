import base64
import unittest
from unittest.mock import ANY, create_autospec

import django
from django.test import SimpleTestCase, modify_settings, override_settings

from anymail.exceptions import AnymailInsecureWebhookWarning
from anymail.signals import inbound, tracking

from .utils import AnymailTestMixin, ClientWithCsrfChecks


def event_handler(sender, event, esp_name, **kwargs):
    """Prototypical webhook signal handler"""
    pass


@override_settings(ANYMAIL={"WEBHOOK_SECRET": "username:password"})
class WebhookTestCase(AnymailTestMixin, SimpleTestCase):
    """Base for testing webhooks

    - connects webhook signal handlers
    - sets up basic auth by default (since most ESP webhooks warn if it's not enabled)
    """

    client_class = ClientWithCsrfChecks

    def setUp(self):
        super().setUp()
        # Use correct basic auth by default (individual tests can override):
        self.set_basic_auth()

        # Install mocked signal handlers
        self.tracking_handler = create_autospec(event_handler)
        tracking.connect(self.tracking_handler)
        self.addCleanup(tracking.disconnect, self.tracking_handler)

        self.inbound_handler = create_autospec(event_handler)
        inbound.connect(self.inbound_handler)
        self.addCleanup(inbound.disconnect, self.inbound_handler)

    def set_basic_auth(self, username="username", password="password"):
        """Set basic auth for all subsequent test client requests"""
        credentials = base64.b64encode(
            "{}:{}".format(username, password).encode("utf-8")
        ).decode("utf-8")
        self.client.defaults["HTTP_AUTHORIZATION"] = "Basic {}".format(credentials)

    def clear_basic_auth(self):
        self.client.defaults.pop("HTTP_AUTHORIZATION", None)

    def assert_handler_called_once_with(
        self, mockfn, *expected_args, **expected_kwargs
    ):
        """Verifies mockfn was called with expected_args and at least expected_kwargs.

        Ignores *additional* actual kwargs
        (which might be added by Django signal dispatch).
        (This differs from mock.assert_called_once_with.)

        Returns the actual kwargs.
        """
        self.assertEqual(mockfn.call_count, 1)
        actual_args, actual_kwargs = mockfn.call_args
        self.assertEqual(actual_args, expected_args)
        for key, expected_value in expected_kwargs.items():
            if expected_value is ANY:
                self.assertIn(key, actual_kwargs)
            else:
                self.assertEqual(actual_kwargs[key], expected_value)
        return actual_kwargs

    def get_kwargs(self, mockfn):
        """Return the kwargs passed to the most recent call to mockfn"""
        self.assertIsNotNone(mockfn.call_args)  # mockfn hasn't been called yet
        actual_args, actual_kwargs = mockfn.call_args
        return actual_kwargs


class WebhookBasicAuthTestCase(WebhookTestCase):
    """Common test cases for webhook basic authentication.

    Instantiate for each ESP's webhooks by:
    - subclassing
    - defining call_webhook to invoke the ESP's webhook
    - adding or overriding any tests as appropriate
    """

    def __init__(self, methodName="runTest"):
        if self.__class__ is WebhookBasicAuthTestCase:
            # don't run these tests on the abstract base implementation
            methodName = "runNoTestsInBaseClass"
        super().__init__(methodName)

    def runNoTestsInBaseClass(self):
        pass

    #: subclass set False if other webhook verification used
    should_warn_if_no_auth = True

    def call_webhook(self):
        # Concrete test cases should call a webhook via self.client.post,
        # and return the response
        raise NotImplementedError()

    @override_settings(ANYMAIL={})  # Clear the WEBHOOK_AUTH settings from superclass
    def test_warns_if_no_auth(self):
        if self.should_warn_if_no_auth:
            with self.assertWarns(AnymailInsecureWebhookWarning):
                response = self.call_webhook()
        else:
            with self.assertDoesNotWarn(AnymailInsecureWebhookWarning):
                response = self.call_webhook()
        self.assertEqual(response.status_code, 200)

    def test_verifies_basic_auth(self):
        response = self.call_webhook()
        self.assertEqual(response.status_code, 200)

    def test_verifies_bad_auth(self):
        self.set_basic_auth("baduser", "wrongpassword")
        response = self.call_webhook()
        self.assertEqual(response.status_code, 400)

    def test_verifies_missing_auth(self):
        self.clear_basic_auth()
        response = self.call_webhook()
        self.assertEqual(response.status_code, 400)

    @override_settings(ANYMAIL={"WEBHOOK_SECRET": ["cred1:pass1", "cred2:pass2"]})
    def test_supports_credential_rotation(self):
        """You can supply a list of basic auth credentials, and any is allowed"""
        self.set_basic_auth("cred1", "pass1")
        response = self.call_webhook()
        self.assertEqual(response.status_code, 200)

        self.set_basic_auth("cred2", "pass2")
        response = self.call_webhook()
        self.assertEqual(response.status_code, 200)

        self.set_basic_auth("baduser", "wrongpassword")
        response = self.call_webhook()
        self.assertEqual(response.status_code, 400)

    @unittest.skipIf(
        django.VERSION < (5, 1),
        "LoginRequiredMiddleware not available in this Django version",
    )
    @modify_settings(
        MIDDLEWARE={"append": "django.contrib.auth.middleware.LoginRequiredMiddleware"}
    )
    def test_works_with_login_required_middleware(self):
        """Webhooks don't use Django login, so shouldn't require it"""
        response = self.call_webhook()
        self.assertEqual(response.status_code, 200)
