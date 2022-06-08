from urllib.parse import urljoin

import requests

from anymail.utils import get_anymail_setting
from .base import AnymailBaseBackend, BasePayload
from .._version import __version__
from ..exceptions import AnymailRequestsAPIError


class AnymailRequestsBackend(AnymailBaseBackend):
    """
    Base Anymail email backend for ESPs that use an HTTP API via requests
    """

    def __init__(self, api_url, **kwargs):
        """Init options from Django settings"""
        self.api_url = api_url
        self.timeout = get_anymail_setting('requests_timeout', kwargs=kwargs, default=30)
        super().__init__(**kwargs)
        self.session = None

    def open(self):
        if self.session:
            return False  # already exists

        try:
            self.session = self.create_session()
        except Exception:
            if not self.fail_silently:
                raise

        return True

    def close(self):
        if self.session is None:
            return
        try:
            self.session.close()
        except requests.RequestException:
            if not self.fail_silently:
                raise
        finally:
            self.session = None

    def _send(self, message):
        if self.session is None:
            class_name = self.__class__.__name__
            raise RuntimeError(
                "Session has not been opened in {class_name}._send. "
                "(This is either an implementation error in {class_name}, "
                "or you are incorrectly calling _send directly.)".format(class_name=class_name))
        return super()._send(message)

    def create_session(self):
        """Create the requests.Session object used by this instance of the backend.
        If subclassed, you can modify the Session returned from super() to give
        it your own configuration.

        This must return an instance of requests.Session."""
        session = requests.Session()

        session.headers["User-Agent"] = "django-anymail/{version}-{esp} {orig}".format(
            esp=self.esp_name.lower(), version=__version__,
            orig=session.headers.get("User-Agent", ""))

        if self.debug_api_requests:
            session.hooks['response'].append(self._dump_api_request)

        return session

    def post_to_esp(self, payload, message):
        """Post payload to ESP send API endpoint, and return the raw response.

        payload is the result of build_message_payload
        message is the original EmailMessage
        return should be a requests.Response

        Can raise AnymailRequestsAPIError for HTTP errors in the post
        """
        params = payload.get_request_params(self.api_url)
        params.setdefault('timeout', self.timeout)
        try:
            response = self.session.request(**params)
        except requests.RequestException as err:
            # raise an exception that is both AnymailRequestsAPIError
            # and the original requests exception type
            exc_class = type('AnymailRequestsAPIError', (AnymailRequestsAPIError, type(err)), {})
            raise exc_class(
                "Error posting to %s:" % params.get('url', '<missing url>'),
                email_message=message, payload=payload) from err
        self.raise_for_status(response, payload, message)
        return response

    def raise_for_status(self, response, payload, message):
        """Raise AnymailRequestsAPIError if response is an HTTP error

        Subclasses can override for custom error checking
        (though should defer parsing/deserialization of the body to
        parse_recipient_status)
        """
        if response.status_code < 200 or response.status_code >= 300:
            raise AnymailRequestsAPIError(
                email_message=message, payload=payload,
                response=response, backend=self)

    def deserialize_json_response(self, response, payload, message):
        """Deserialize an ESP API response that's in json.

        Useful for implementing deserialize_response
        """
        try:
            return response.json()
        except ValueError as err:
            raise AnymailRequestsAPIError("Invalid JSON in %s API response" % self.esp_name,
                                          email_message=message, payload=payload, response=response,
                                          backend=self) from err

    @staticmethod
    def _dump_api_request(response, **kwargs):
        """Print the request and response for debugging"""
        # (This is not byte-for-byte, but a readable text representation that assumes
        # UTF-8 encoding if encoded, and that omits the CR in CRLF line endings.
        # If you need the raw bytes, configure HTTPConnection logging as shown
        # in http://docs.python-requests.org/en/v3.0.0/api/#api-changes)
        request = response.request  # a PreparedRequest
        print("\n===== Anymail API request")
        print("{method} {url}\n{headers}".format(
            method=request.method, url=request.url,
            headers="".join("{header}: {value}\n".format(header=header, value=value)
                            for (header, value) in request.headers.items()),
        ))
        if request.body is not None:
            body_text = (request.body if isinstance(request.body, str)
                         else request.body.decode("utf-8", errors="replace")
                         ).replace("\r\n", "\n")
            print(body_text)
        print("\n----- Response")
        print("HTTP {status} {reason}\n{headers}\n{body}".format(
            status=response.status_code, reason=response.reason,
            headers="".join("{header}: {value}\n".format(header=header, value=value)
                            for (header, value) in response.headers.items()),
            body=response.text,  # Let Requests decode body content for us
        ))


class RequestsPayload(BasePayload):
    """Abstract Payload for AnymailRequestsBackend"""

    def __init__(self, message, defaults, backend,
                 method="POST", params=None, data=None,
                 headers=None, files=None, auth=None):
        self.method = method
        self.params = params
        self.data = data
        self.headers = headers
        self.files = files
        self.auth = auth
        super().__init__(message, defaults, backend)

    def get_request_params(self, api_url):
        """Returns a dict of requests.request params that will send payload to the ESP.

        :param api_url: the base api_url for the backend
        :return: dict
        """
        api_endpoint = self.get_api_endpoint()
        if api_endpoint is not None:
            url = urljoin(api_url, api_endpoint)
        else:
            url = api_url

        return dict(
            method=self.method,
            url=url,
            params=self.params,
            data=self.serialize_data(),
            headers=self.headers,
            files=self.files,
            auth=self.auth,
            # json= is not here, because we prefer to do our own serialization
            #       to provide extra context in error messages
        )

    def get_api_endpoint(self):
        """Returns a str that should be joined to the backend's api_url for sending this payload."""
        return None

    def serialize_data(self):
        """Performs any necessary serialization on self.data, and returns the result."""
        return self.data
