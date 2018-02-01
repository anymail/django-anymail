import requests

from ..utils import get_anymail_setting
from ..message import AnymailRecipientStatus
from .base_requests import AnymailRequestsBackend, RequestsPayload

class EmailBackend(AnymailRequestsBackend):
    """
    Responsys API Email Backend
    """

    esp_name = "Responsys"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name

        username = get_anymail_setting('username', esp_name=esp_name, kwargs=kwargs, default=None, allow_bare=True)
        password = get_anymail_setting('password', esp_name=esp_name, kwargs=kwargs, default=None, allow_bare=True)

        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs,
                                        default='/rest/api/v1.3/campaigns/test_email_alerts/email')

        login_url = get_anymail_setting('login_url', esp_name=esp_name, kwargs=kwargs,
                                        default='http://login2.responsys.net/rest/api/v1.3/auth/token')

        # Fetch authentication token from Responsys
        payload = dict(
            user_name=username,
            password=password,
            auth_type='password'
        )

        response = requests.post(login_url, data=payload)

        parsed_response = self.deserialize_json_response(response, payload, {})

        api_url = parsed_response['endPoint'] + api_url

        self.auth_token = parsed_response['authToken']

        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return ResponsysPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        recipientsDict = {}
        parsed_response = self.deserialize_json_response(response, payload, message)

        for r in parsed_response:
            status = 'sent' if r['success'] else 'failed'
            recipientsDict[r['recipientId']] = AnymailRecipientStatus(status=status,  message_id=None)

        return recipientsDict

class ResponsysPayload(RequestsPayload):

    def __init__(self, message, defaults, backend, *args, **kwargs):
        http_headers = kwargs.pop('headers', {})
        http_headers['Authorization'] = '%s' % backend.auth_token
        http_headers['Content-Type'] = 'application/json'
        http_headers['Accept'] = 'application/json'
        super(ResponsysPayload, self).__init__(message, defaults, backend,
                                              headers=http_headers,
                                              *args, **kwargs)

    def init_payload(self):
        self.data = {}

    def set_text_body(self, body):
        self.data = body

    def set_extra_headers(self, headers):
        pass

    def set_html_body(self, body):
        pass

    def set_reply_to(self, emails):
        pass

    def set_from_email(self, email):
        pass

    def set_recipients(self, recipient_type, emails):
        pass

    def set_subject(self, subject):
        pass
