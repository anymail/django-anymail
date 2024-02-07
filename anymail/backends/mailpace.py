from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import CaseInsensitiveCasePreservingDict, get_anymail_setting
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    MailPace API Email Backend
    """

    esp_name = "MailPace"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.server_token = get_anymail_setting(
            "server_token", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://app.mailpace.com/api/v1/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailPacePayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        # We need to handle 400 responses in parse_recipient_status
        if response.status_code != 400:
            super().raise_for_status(response, payload, message)

    def parse_recipient_status(self, response, payload, message):
        # Prepare the dict by setting everything to queued without a message id
        unknown_status = AnymailRecipientStatus(message_id=None, status="unknown")
        recipient_status = CaseInsensitiveCasePreservingDict(
            {recip.addr_spec: unknown_status for recip in payload.to_cc_and_bcc_emails}
        )

        parsed_response = self.deserialize_json_response(response, payload, message)

        status_code = str(response.status_code)
        json_response = response.json()

        # Set the status_msg and id based on the status_code
        if status_code == "200":
            try:
                status_msg = parsed_response["status"]
                id = parsed_response["id"]
            except (KeyError, TypeError) as err:
                raise AnymailRequestsAPIError(
                    "Invalid MailPace API response format",
                    email_message=None,
                    payload=payload,
                    response=response,
                    backend=self,
                ) from err
        elif status_code.startswith("4"):
            status_msg = "error"
            id = None

        if status_msg == "queued":
            # Add the message_id to all of the recipients
            for recip in payload.to_cc_and_bcc_emails:
                recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                    message_id=id, status="queued"
                )
        elif status_msg == "error":
            if "errors" in json_response:
                for field in ["to", "cc", "bcc"]:
                    if field in json_response["errors"]:
                        error_messages = json_response["errors"][field]
                        for email in payload.to_cc_and_bcc_emails:
                            for error_message in error_messages:
                                if (
                                    "undefined field" in error_message
                                    or "is invalid" in error_message
                                ):
                                    recipient_status[
                                        email.addr_spec
                                    ] = AnymailRecipientStatus(
                                        message_id=None, status="invalid"
                                    )
                                elif "contains a blocked address" in error_message:
                                    recipient_status[
                                        email.addr_spec
                                    ] = AnymailRecipientStatus(
                                        message_id=None, status="rejected"
                                    )
                                elif (
                                    "number of email addresses exceeds maximum volume"
                                    in error_message
                                ):
                                    recipient_status[
                                        email.addr_spec
                                    ] = AnymailRecipientStatus(
                                        message_id=None, status="invalid"
                                    )
                        else:
                            continue  # No errors found in this field; continue to next field
            else:
                raise AnymailRequestsAPIError(
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                )

        return dict(recipient_status)


class MailPacePayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.server_token = backend.server_token  # esp_extra can override
        self.to_cc_and_bcc_emails = []
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        return "send"

    def get_request_params(self, api_url):
        params = super().get_request_params(api_url)
        params["headers"]["MailPace-Server-Token"] = self.server_token
        return params

    def serialize_data(self):
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email(self, email):
        self.data["from"] = email.address

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            # Creates to, cc, and bcc in the payload
            self.data[recipient_type] = ", ".join([email.address for email in emails])
            self.to_cc_and_bcc_emails += emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            reply_to = ", ".join([email.address for email in emails])
            self.data["replyto"] = reply_to

    def set_extra_headers(self, headers):
        if "list-unsubscribe" in headers:
            self.data["list_unsubscribe"] = headers.pop("list-unsubscribe")
        if headers:
            self.unsupported_features("extra_headers (other than List-Unsubscribe)")

    def set_text_body(self, body):
        self.data["textbody"] = body

    def set_html_body(self, body):
        self.data["htmlbody"] = body

    def make_attachment(self, attachment):
        """Returns MailPace attachment dict for attachment"""
        att = {
            "name": attachment.name or "",
            "content": attachment.b64content,
            "content_type": attachment.mimetype,
        }
        if attachment.inline:
            att["cid"] = "cid:%s" % attachment.cid
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_tags(self, tags):
        if tags:
            if len(tags) == 1:
                self.data["tags"] = tags[0]
            else:
                self.data["tags"] = tags

    def set_esp_extra(self, extra):
        self.data.update(extra)
        # Special handling for 'server_token':
        self.server_token = self.data.pop("server_token", self.server_token)
