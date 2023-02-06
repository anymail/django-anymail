import json
from io import BytesIO
from unittest.mock import patch

import requests
from django.core import mail
from django.test import SimpleTestCase

from anymail.exceptions import AnymailAPIError

from .utils import AnymailTestMixin

UNSET = object()


class RequestsBackendMockAPITestCase(AnymailTestMixin, SimpleTestCase):
    """TestCase that mocks API calls through requests"""

    DEFAULT_RAW_RESPONSE = b"""{"subclass": "should override"}"""
    DEFAULT_STATUS_CODE = 200  # most APIs use '200 OK' for success

    class MockResponse(requests.Response):
        """requests.request return value mock sufficient for testing"""

        def __init__(
            self,
            status_code=200,
            raw=b"RESPONSE",
            encoding="utf-8",
            reason=None,
            test_case=None,
        ):
            super().__init__()
            self.status_code = status_code
            self.encoding = encoding
            self.reason = reason or ("OK" if 200 <= status_code < 300 else "ERROR")
            self.raw = BytesIO(raw)
            self.test_case = test_case

        @property
        def url(self):
            return self.test_case.get_api_call_arg("url", required=False)

        @url.setter
        def url(self, url):
            if url is not None:
                raise ValueError("MockResponse can't handle url assignment")

    def setUp(self):
        super().setUp()
        self.patch_request = patch("requests.Session.request", autospec=True)
        self.mock_request = self.patch_request.start()
        self.addCleanup(self.patch_request.stop)
        self.set_mock_response()

    def set_mock_response(
        self, status_code=DEFAULT_STATUS_CODE, raw=UNSET, encoding="utf-8", reason=None
    ):
        if raw is UNSET:
            raw = self.DEFAULT_RAW_RESPONSE
        mock_response = self.MockResponse(
            status_code, raw=raw, encoding=encoding, reason=reason, test_case=self
        )
        self.mock_request.return_value = mock_response
        return mock_response

    def assert_esp_called(self, url, method="POST"):
        """Verifies the (mock) ESP API was called on endpoint.

        url can be partial, and is just checked against the end of the url requested
        """
        # This assumes the last (or only) call to requests.Session.request
        # is the API call of interest.
        if self.mock_request.call_args is None:
            raise AssertionError("No ESP API was called")
        if method is not None:
            actual_method = self.get_api_call_arg("method")
            if actual_method != method:
                self.fail(
                    "API was not called using %s. (%s was used instead.)"
                    % (method, actual_method)
                )
        if url is not None:
            actual_url = self.get_api_call_arg("url")
            if not actual_url.endswith(url):
                self.fail(
                    "API was not called at %s\n(It was called at %s)"
                    % (url, actual_url)
                )

    def get_api_call_arg(self, kwarg, required=True):
        """Returns an argument passed to the mock ESP API.

        Fails test if API wasn't called.
        """
        if self.mock_request.call_args is None:
            raise AssertionError("API was not called")
        (args, kwargs) = self.mock_request.call_args
        try:
            return kwargs[kwarg]
        except KeyError:
            pass

        try:
            # positional arg? This is the order of requests.Session.request params:
            pos = (
                "method",
                "url",
                "params",
                "data",
                "headers",
                "cookies",
                "files",
                "auth",
                "timeout",
                "allow_redirects",
                "proxies",
                "hooks",
                "stream",
                "verify",
                "cert",
                "json",
            ).index(kwarg)
            return args[pos]
        except (ValueError, IndexError):
            pass

        if required:
            self.fail("API was called without required arg '%s'" % kwarg)
        return None

    def get_api_call_params(self, required=True):
        """Returns the query params sent to the mock ESP API."""
        return self.get_api_call_arg("params", required)

    def get_api_call_data(self, required=True):
        """Returns the raw data sent to the mock ESP API."""
        return self.get_api_call_arg("data", required)

    def get_api_call_json(self, required=True):
        """Returns the data sent to the mock ESP API, json-parsed"""
        # could be either the data param (as json str)
        # or the json param (needing formatting)
        value = self.get_api_call_arg("data", required=False)
        if value is not None:
            return json.loads(value)
        else:
            return self.get_api_call_arg("json", required)

    def get_api_call_headers(self, required=True):
        """Returns the headers sent to the mock ESP API"""
        return self.get_api_call_arg("headers", required)

    def get_api_call_files(self, required=True):
        """Returns the files sent to the mock ESP API"""
        return self.get_api_call_arg("files", required)

    def get_api_call_auth(self, required=True):
        """Returns the auth sent to the mock ESP API"""
        return self.get_api_call_arg("auth", required)

    def get_api_prepared_request(self):
        """Returns the PreparedRequest that would have been sent"""
        (args, kwargs) = self.mock_request.call_args
        kwargs.pop("timeout", None)  # Session-only param
        request = requests.Request(**kwargs)
        return request.prepare()

    def assert_esp_not_called(self, msg=None):
        if self.mock_request.called:
            raise AssertionError(msg or "ESP API was called and shouldn't have been")


class SessionSharingTestCases(RequestsBackendMockAPITestCase):
    """Common test cases for requests backend connection sharing.

    Instantiate for each ESP by:
    - subclassing
    - adding or overriding any tests as appropriate
    """

    def __init__(self, methodName="runTest"):
        if self.__class__ is SessionSharingTestCases:
            # don't run these tests on the abstract base implementation
            methodName = "runNoTestsInBaseClass"
        super().__init__(methodName)

    def runNoTestsInBaseClass(self):
        pass

    def setUp(self):
        super().setUp()
        self.patch_close = patch("requests.Session.close", autospec=True)
        self.mock_close = self.patch_close.start()
        self.addCleanup(self.patch_close.stop)

    def test_connection_sharing(self):
        """RequestsBackend reuses one requests session when sending multiple messages"""
        datatuple = (
            ("Subject 1", "Body 1", "from@example.com", ["to@example.com"]),
            ("Subject 2", "Body 2", "from@example.com", ["to@example.com"]),
        )
        mail.send_mass_mail(datatuple)
        self.assertEqual(self.mock_request.call_count, 2)
        session1 = self.mock_request.call_args_list[0][0]  # arg[0] (self) is session
        session2 = self.mock_request.call_args_list[1][0]
        self.assertEqual(session1, session2)
        self.assertEqual(self.mock_close.call_count, 1)

    def test_caller_managed_connections(self):
        """Calling code can created long-lived connection that it opens and closes"""
        connection = mail.get_connection()
        connection.open()
        mail.send_mail(
            "Subject 1",
            "body",
            "from@example.com",
            ["to@example.com"],
            connection=connection,
        )
        session1 = self.mock_request.call_args[0]
        self.assertEqual(self.mock_close.call_count, 0)  # shouldn't be closed yet

        mail.send_mail(
            "Subject 2",
            "body",
            "from@example.com",
            ["to@example.com"],
            connection=connection,
        )
        self.assertEqual(self.mock_close.call_count, 0)  # still shouldn't be closed
        session2 = self.mock_request.call_args[0]
        self.assertEqual(session1, session2)  # should have reused same session

        connection.close()
        self.assertEqual(self.mock_close.call_count, 1)

    def test_session_closed_after_exception(self):
        self.set_mock_response(status_code=500)
        with self.assertRaises(AnymailAPIError):
            mail.send_mail("Subject", "Message", "from@example.com", ["to@example.com"])
        self.assertEqual(self.mock_close.call_count, 1)

    def test_session_closed_after_fail_silently_exception(self):
        self.set_mock_response(status_code=500)
        sent = mail.send_mail(
            "Subject",
            "Message",
            "from@example.com",
            ["to@example.com"],
            fail_silently=True,
        )
        self.assertEqual(sent, 0)
        self.assertEqual(self.mock_close.call_count, 1)

    def test_caller_managed_session_closed_after_exception(self):
        connection = mail.get_connection()
        connection.open()
        self.set_mock_response(status_code=500)
        with self.assertRaises(AnymailAPIError):
            mail.send_mail(
                "Subject",
                "Message",
                "from@example.com",
                ["to@example.com"],
                connection=connection,
            )
        self.assertEqual(self.mock_close.call_count, 0)  # wait for us to close it

        connection.close()
        self.assertEqual(self.mock_close.call_count, 1)
