import requests

from ..exceptions import AnymailError
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

        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs, default='/rest/api/v1.3/campaigns/')

        login_url = get_anymail_setting('login_url', esp_name=esp_name, kwargs=kwargs,
                                        default='http://login2.responsys.net/rest/api/v1.3/auth/token')

        # Fetch authentication token from Responsys
        payload = dict(
            user_name=username,
            password=password,
            auth_type='password'
        )

        response = requests.post(login_url, data=payload)

        parsed_response = self.deserialize_json_response(response, payload, dict())

        api_url = parsed_response['endPoint'] + api_url

        self.auth_token = parsed_response['authToken']

        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return ResponsysPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        recipients_dict = dict()
        parsed_response = self.deserialize_json_response(response, payload, message)

        for r in parsed_response:
            status = 'sent' if r['success'] else 'failed'
            recipients_dict[r['recipientId']] = AnymailRecipientStatus(status=status,  message_id=None)

        return recipients_dict


class ResponsysPayload(RequestsPayload):

    def __init__(self, message, defaults, backend, *args, **kwargs):
        http_headers = kwargs.pop('headers', dict())
        http_headers['Authorization'] = '%s' % backend.auth_token
        http_headers['Content-Type'] = 'application/json'
        http_headers['Accept'] = 'application/json'
        super(ResponsysPayload, self).__init__(message, defaults, backend,
                                               headers=http_headers,
                                               *args, **kwargs)

    def init_payload(self):
        self.data = dict(
            mergeTriggerRecordData=dict(
                mergeTriggerRecords=list(),
                fieldNames=list()
            ),
            mergeRule=self.get_default_merge_rule()
        )

    def get_api_endpoint(self):
        if self.esp_extra.get('campaign_name', None) is None:
            raise AnymailError("Cannot call Responsys unknown campaign name. "
                               "Set `message.esp_extra={'campaign_name': '<campaign_name>'}`",
                               backend=self.backend, email_message=self.message, payload=self)
        return "%s/email" % self.esp_extra.get('campaign_name')

    def set_text_body(self, body):
        pass
        # self.unsupported_feature("text_body")

    def set_from_email(self, email):
        pass
        # self.unsupported_feature("from_email")

    def set_extra_headers(self, headers):
        pass
        # self.unsupported_feature("extra_headers")

    def set_html_body(self, body):
        pass
        # self.unsupported_feature("html_body")

    def set_reply_to(self, emails):
        pass
        # self.unsupported_feature("reply_to")

    def set_to(self, emails):
        self.to = emails

    def set_subject(self, subject):
        self.subject = dict(name='SUBJECT', value=subject or '')

    def set_esp_extra(self, extra):
        self.esp_extra = extra

    def set_merge_data(self, merge_data):
        self.data['mergeTriggerRecordData']['mergeTriggerRecords'] = merge_data.get('recipients', [])

    def set_merge_global_data(self, merge_global_data):
        self.data['mergeRule'].update(merge_global_data.get('mergeRule', dict()))
        self.data['mergeTriggerRecordData']['fieldNames'] = merge_global_data.get('fieldNames', [])

        self.custom_data = merge_global_data.get('customData', None)

        for recipient in self.data['mergeTriggerRecordData']['mergeTriggerRecords']:
            if self.custom_data is not None:
                recipient['optionalData'] = recipient['optionalData'] + self.custom_data

            recipient['optionalData'].append(self.subject)

    def get_default_merge_rule(self):
        return dict(
            htmlValue='H',
            matchColumnName1='EMAIL_ADDRESS_',
            matchColumnName2=None,
            optoutValue='O',
            insertOnNoMatch=True,
            defaultPermissionStatus='OPTIN',
            rejectRecordIfChannelEmpty='E',
            optinValue='I',
            updateOnMatch='REPLACE_ALL',
            textValue='T',
            matchOperator='NONE'
        )

    def serialize_data(self):
        return self.serialize_json(self.data)
