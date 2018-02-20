from requests.structures import CaseInsensitiveDict

from .base_requests import AnymailRequestsBackend, RequestsPayload
from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting, parse_address_list


class EmailBackend(AnymailRequestsBackend):
    """
    SendinBlue v3 API Email Backend
    """

    esp_name = "SendinBlue"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting(
            'api_key',
            esp_name=esp_name,
            kwargs=kwargs,
            allow_bare=True,
        )
        api_url = get_anymail_setting(
            'api_url',
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.sendinblue.com/v3",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return SendinBluePayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        if response.status_code < 200 or response.status_code >= 300:
            raise AnymailRequestsAPIError(
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )

    def parse_recipient_status(self, response, payload, message):
        # SendinBlue doesn't give any detail on a success
        # https://developers.sendinblue.com/docs/responses
        message_id = None

        if response.content != b'':
            parsed_response = self.deserialize_json_response(response, payload, message)
            try:
                message_id = parsed_response['messageId']
            except (KeyError, TypeError):
                raise AnymailRequestsAPIError("Invalid SendinBlue API response format",
                                              email_message=message, payload=payload, response=response,
                                              backend=self)

        status = AnymailRecipientStatus(message_id=message_id, status="queued")
        return {recipient.addr_spec: status for recipient in payload.all_recipients}


class SendinBluePayload(RequestsPayload):

    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.all_recipients = []  # used for backend.parse_recipient_status
        self.template_id = None

        http_headers = kwargs.pop('headers', {})
        http_headers['api-key'] = backend.api_key
        http_headers['Content-Type'] = 'application/json'

        super(SendinBluePayload, self).__init__(message, defaults, backend, headers=http_headers, *args, **kwargs)

    def get_api_endpoint(self):
        if self.template_id:
            return "smtp/templates/%s/send" % (self.template_id)
        else:
            return "smtp/email"

    def init_payload(self):
        self.data = {  # becomes json
            'headers': CaseInsensitiveDict()
        }

    def serialize_data(self):
        """Performs any necessary serialization on self.data, and returns the result."""

        headers = self.data["headers"]
        if "Reply-To" in headers:
            # Reply-To must be in its own param
            reply_to = headers.pop('Reply-To')
            self.set_reply_to(parse_address_list([reply_to]))
        if len(headers) > 0:
            self.data["headers"] = dict(headers)  # flatten to normal dict for json serialization
        else:
            del self.data["headers"]  # don't send empty headers

        # SendinBlue use different argument's name if we use template functionality
        if self.template_id:
            data = self._transform_data_for_templated_email(self.data)
        else:
            data = self.data

        return self.serialize_json(data)

    def _transform_data_for_templated_email(self, data):
        """
        Transform the default Payload's data (used for basic transactional email) to
        the data used by SendinBlue in case of a templated transactional email.
        :param data: The data we want to transform
        :return: The transformed data
        """
        if 'subject' in data:
            self.unsupported_feature("overriding template subject")
        if 'subject' in data:
            self.unsupported_feature("overriding template from_email")
        if 'textContent' in data or 'htmlContent' in data:
            self.unsupported_feature("overriding template body content")

        transformation = {
            'to': 'emailTo',
            'cc': 'emailCc',
            'bcc': 'emailBcc',
        }
        for key in data:
            if key in transformation:
                new_key = transformation[key]
                list_email = list()
                for email in data.pop(key):
                    if 'name' in email:
                        self.unsupported_feature("display names in (%r) when sending with a template" % key)

                    list_email.append(email.get('email'))

                data[new_key] = list_email

        if 'replyTo' in data:
            if 'name' in data['replyTo']:
                self.unsupported_feature("display names in (replyTo) when sending with a template")

            data['replyTo'] = data['replyTo']['email']

        return data

    #
    # Payload construction
    #

    @staticmethod
    def email_object(email):
        """Converts EmailAddress to SendinBlue API array"""
        email_object = dict()
        email_object['email'] = email.addr_spec
        if email.display_name:
            email_object['name'] = email.display_name
        return email_object

    def set_from_email(self, email):
        self.data["sender"] = self.email_object(email)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            self.data[recipient_type] = [self.email_object(email) for email in emails]
            self.all_recipients += emails  # used for backend.parse_recipient_status

    def set_subject(self, subject):
        if subject != "":  # see note in set_text_body about template rendering
            self.data["subject"] = subject

    def set_reply_to(self, emails):
        # SendinBlue only supports a single address in the reply_to API param.
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if len(emails) > 0:
            self.data['replyTo'] = self.email_object(emails[0])

    def set_extra_headers(self, headers):
        for key in headers.keys():
            self.data['headers'][key] = headers[key]

    def set_tags(self, tags):
        if len(tags) > 0:
            self.data['headers']["X-Mailin-tag"] = tags[0]
            if len(tags) > 1:
                self.unsupported_feature('multiple tags (%r)' % tags)

    def set_template_id(self, template_id):
        self.template_id = template_id

    def set_text_body(self, body):
        if body:
            self.data['textContent'] = body

    def set_html_body(self, body):
        if body:
            if "htmlContent" in self.data:
                self.unsupported_feature("multiple html parts")

            self.data['htmlContent'] = body

    def add_attachment(self, attachment):
        """Converts attachments to SendinBlue API {name, base64} array"""
        att = {
            'name': attachment.name or '',
            'content': attachment.b64content,
        }

        if attachment.inline:
            self.unsupported_feature("inline attachments")

        self.data.setdefault("attachment", []).append(att)

    def set_esp_extra(self, extra):
        self.data.update(extra)

    def set_merge_data(self, merge_data):
        """SendinBlue doesn't support special attributes for each recipient"""
        self.unsupported_feature("merge_data")

    def set_merge_global_data(self, merge_global_data):
        self.data['attributes'] = merge_global_data
