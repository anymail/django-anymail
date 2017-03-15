from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus, ANYMAIL_STATUSES
from ..utils import get_anymail_setting

from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Mailjet API Email Backend
    """

    esp_name = "Mailjet"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting('api_key', esp_name=esp_name, kwargs=kwargs, allow_bare=True)
        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs,
                                      default="https://api.mailjet.com/v3")
        if not api_url.endswith("/"):
            api_url += "/"
        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailjetPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        recipient_status = {}
        try:
            for key in parsed_response:
                status = key.lower()
                if status not in ANYMAIL_STATUSES:
                    status = 'unknown'

                for item in parsed_response[key]:
                    message_id = item.get('MessageID_id', None)
                    email = item['Email']
                    recipient_status[email] = AnymailRecipientStatus(message_id=message_id, status=status)
        except (KeyError, TypeError):
            raise AnymailRequestsAPIError("Invalid Mailjet API response format",
                                          email_message=message, payload=payload, response=response,
                                          backend=self)
        return recipient_status


class MailjetPayload(RequestsPayload):

    def __init__(self, *args, **kwargs):
        self.esp_extra = {}  # late-bound in serialize_data
        self.headers = {
            'Content-Type': 'application/json',
        }
        super(MailjetPayload, self).__init__(*args, **kwargs)

    def get_api_endpoint(self):
        return "messages/send"

    def serialize_data(self):
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {
        }

    def set_from_email(self, email):
        self.data["FromEmail"] = email.email
        if email.name:
            self.data["FromName"] = email.name

    def add_recipient(self, recipient_type, email):
        assert recipient_type in ["to", "cc", "bcc"]
        self.data.setdefault(recipient_type.capitalize(), []).append(str(email))

    def set_subject(self, subject):
        self.data["Subject"] = subject

    def set_reply_to(self, emails):
        self.data["Reply-To"] = ", ".join([str(email) for email in emails])

    def set_extra_headers(self, headers):
        self.data.setdefault("Headers", {}).update(headers)

    def set_text_body(self, body):
        self.data["Text-part"] = body

    def set_html_body(self, body):
        if "Html-part" in self.data:
            # second html body could show up through multiple alternatives, or html body + alternative
            self.unsupported_feature("multiple html parts")

        self.data["Html-part"] = body

    def add_attachment(self, attachment):
        if attachment.inline:
            field = "Inline_attachments"
            name = attachment.cid
        else:
            field = "Attachments"
            name = attachment.name or ""
        self.data.setdefault(field, []).append({
            "Content-type": attachment.mimetype,
            "Filename": name,
            "content": attachment.b64content
        })

    def set_tags(self, tags):
        self.data["Mj-EventPayLoad"] = ','.join(tags)

    def set_track_clicks(self, track_clicks):
        # 1 disables tracking, 2 enables tracking
        self.data["Mj-trackclick"] = 2 if track_clicks else 1

    def set_track_opens(self, track_opens):
        # 1 disables tracking, 2 enables tracking
        self.data["Mj-trackopen"] = 2 if track_opens else 1

    def set_template_id(self, template_id):
        self.data["Mj-TemplateID"] = template_id
        self.data["Mj-TemplateLanguage"] = True
