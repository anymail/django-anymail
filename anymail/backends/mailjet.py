from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus, ANYMAIL_STATUSES
from ..utils import get_anymail_setting, ParsedEmail, parse_address_list

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
        self.secret_key = get_anymail_setting('secret_key', esp_name=esp_name, kwargs=kwargs, allow_bare=True)
        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs,
                                      default="https://api.mailjet.com/v3")
        if not api_url.endswith("/"):
            api_url += "/"
        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailjetPayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        # Improve Mailjet's (lack of) error message for bad API key
        if response.status_code == 401 and not response.content:
            raise AnymailRequestsAPIError(
                "Invalid Mailjet API key or secret",
                email_message=message, payload=payload, response=response, backend=self)
        super(EmailBackend, self).raise_for_status(response, payload, message)

    def parse_recipient_status(self, response, payload, message):
        # Mailjet's (v3.0) transactional send API is not covered in their reference docs.
        # The response appears to be either:
        #   {"Sent": [{"Email": ..., "MessageID": ...}, ...]}
        #   where only successful recipients are included
        # or if the entire call has failed:
        #   {"ErrorCode": nnn, "Message": ...}
        parsed_response = self.deserialize_json_response(response, payload, message)
        if "ErrorCode" in parsed_response:
            raise AnymailRequestsAPIError(email_message=message, payload=payload, response=response,
                                          backend=self)

        recipient_status = {}
        try:
            for key in parsed_response:
                status = key.lower()
                if status not in ANYMAIL_STATUSES:
                    status = 'unknown'

                for item in parsed_response[key]:
                    message_id = str(item['MessageID'])
                    email = item['Email']
                    recipient_status[email] = AnymailRecipientStatus(message_id=message_id, status=status)
        except (KeyError, TypeError):
            raise AnymailRequestsAPIError("Invalid Mailjet API response format",
                                          email_message=message, payload=payload, response=response,
                                          backend=self)
        # Make sure we ended up with a status for every original recipient
        # (Mailjet only communicates "Sent")
        for recipients in payload.recipients.values():
            for email in recipients:
                if email.email not in recipient_status:
                    recipient_status[email.email] = AnymailRecipientStatus(message_id=None, status='unknown')

        return recipient_status


class MailjetPayload(RequestsPayload):

    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.esp_extra = {}  # late-bound in serialize_data
        auth = (backend.api_key, backend.secret_key)
        http_headers = {
            'Content-Type': 'application/json',
        }
        # Late binding of recipients and their variables
        self.recipients = {}
        self.merge_data = None
        super(MailjetPayload, self).__init__(message, defaults, backend,
                                             auth=auth, headers=http_headers, *args, **kwargs)

    def get_api_endpoint(self):
        return "send"

    def serialize_data(self):
        self._finish_recipients()
        self._populate_sender_from_template()
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def _finish_recipients(self):
        # NOTE do not set both To and Recipients, it behaves specially: each
        # recipient receives a separate mail but the To address receives one
        # listing all recipients.
        if "cc" in self.recipients or "bcc" in self.recipients:
            self._finish_recipients_single()
        else:
            self._finish_recipients_with_vars()

    def _populate_sender_from_template(self):
        # If no From address was given, use the address from the template.
        # Unfortunately, API 3.0 requires the From address to be given, so let's
        # query it when needed. This will supposedly be fixed in 3.1 with a
        # public beta in May 2017.
        template_id = self.data.get("Mj-TemplateID")
        if template_id and not self.data.get("FromEmail"):
            response = self.backend.session.get(
                "%sREST/template/%s/detailcontent" % (self.backend.api_url, template_id),
                auth=self.auth
            )
            self.backend.raise_for_status(response, None, self.message)
            json_response = self.backend.deserialize_json_response(response, None, self.message)
            # Populate email address header from template.
            try:
                headers = json_response["Data"][0]["Headers"]
                if "From" in headers:
                    # Workaround Mailjet returning malformed From header
                    # if there's a comma in the template's From display-name:
                    from_email = headers["From"].replace(",", "||COMMA||")
                    parsed = parse_address_list([from_email])[0]
                    if parsed.name:
                        parsed.name = parsed.name.replace("||COMMA||", ",")
                else:
                    name_addr = (headers["SenderName"], headers["SenderEmail"])
                    parsed = ParsedEmail(name_addr)
            except KeyError:
                raise AnymailRequestsAPIError("Invalid Mailjet template API response",
                                              email_message=self.message, response=response, backend=self.backend)
            self.set_from_email(parsed)

    def _finish_recipients_with_vars(self):
        """Send bulk mail with different variables for each mail."""
        assert "Cc" not in self.data and "Bcc" not in self.data
        recipients = []
        merge_data = self.merge_data or {}
        for email in self.recipients["to"]:
            recipient = {
                "Email": email.email,
                "Name": email.name,
                "Vars": merge_data.get(email.email)
            }
            # Strip out empty Name and Vars
            recipient = {k: v for k, v in recipient.items() if v}
            recipients.append(recipient)
        self.data["Recipients"] = recipients

    def _finish_recipients_single(self):
        """Send a single mail with some To, Cc and Bcc headers."""
        assert "Recipients" not in self.data
        if self.merge_data:
            # When Cc and Bcc headers are given, then merge data cannot be set.
            raise NotImplementedError("Cannot set merge data with bcc/cc")
        for recipient_type, emails in self.recipients.items():
            # Workaround Mailjet 3.0 bug parsing display-name with commas
            # (see test_comma_in_display_name in test_mailjet_backend for details)
            formatted_emails = [
                email.address if "," not in email.name
                # else name has a comma, so force it into MIME encoded-word utf-8 syntax:
                else ParsedEmail((email.name.encode('utf-8'), email.email)).formataddr('utf-8')
                for email in emails
            ]
            self.data[recipient_type.capitalize()] = ", ".join(formatted_emails)

    def init_payload(self):
        self.data = {
        }

    def set_from_email(self, email):
        self.data["FromEmail"] = email.email
        if email.name:
            self.data["FromName"] = email.name

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        # Will be handled later in serialize_data
        if emails:
            self.recipients[recipient_type] = emails

    def set_subject(self, subject):
        self.data["Subject"] = subject

    def set_reply_to(self, emails):
        headers = self.data.setdefault("Headers", {})
        if emails:
            headers["Reply-To"] = ", ".join([str(email) for email in emails])
        elif "Reply-To" in headers:
            del headers["Reply-To"]

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

    def set_metadata(self, metadata):
        # Mailjet expects a single string payload
        self.data["Mj-EventPayLoad"] = self.serialize_json(metadata)

    def set_tags(self, tags):
        # The choices here are CustomID or Campaign, and Campaign seems closer
        # to how "tags" are handled by other ESPs -- e.g., you can view dashboard
        # statistics across all messages with the same Campaign.
        if len(tags) > 0:
            self.data["Tag"] = tags[0]
            self.data["Mj-campaign"] = tags[0]
            if len(tags) > 1:
                self.unsupported_feature('multiple tags (%r)' % tags)

    def set_track_clicks(self, track_clicks):
        # 1 disables tracking, 2 enables tracking
        self.data["Mj-trackclick"] = 2 if track_clicks else 1

    def set_track_opens(self, track_opens):
        # 1 disables tracking, 2 enables tracking
        self.data["Mj-trackopen"] = 2 if track_opens else 1

    def set_template_id(self, template_id):
        self.data["Mj-TemplateID"] = template_id
        self.data["Mj-TemplateLanguage"] = True

    def set_merge_data(self, merge_data):
        # Will be handled later in serialize_data
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        self.data["Vars"] = merge_global_data

    def set_esp_extra(self, extra):
        self.data.update(extra)
