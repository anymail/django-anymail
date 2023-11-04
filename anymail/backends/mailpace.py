import re

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
    parse_address_list,
)
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
            default="https://app.mailpace.com/api/v1/send",
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
        unknown_status = AnymailRecipientStatus(message_id=None, status="queued")
        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: unknown_status
                for recip in payload.to_cc_and_bcc_emails
            }
        )

        parsed_response = self.deserialize_json_response(response, payload, message)

        try:
            # TODO: Fix this to support errors. Status and ID will not be present if an error is returned

            status_msg = parsed_response["status"]
            id = parsed_response["id"]
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                "Invalid MailPace API response format",
                email_message=status_msg,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        if status_msg == "queued":
            try:
                message_id = parsed_response["id"]
            except KeyError as err:
                raise AnymailRequestsAPIError(
                    "Invalid MailPace API success response format",
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                ) from err

            # Add the message_id to all of the recipients
            for recip in payload.to_cc_and_bcc_emails:
                recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                    message_id=message_id, status="queued"
                )

        # TODO: 4xx ERROR HANDLING
        elif status_msg == "error":  # Invalid email request
            # Various parse-time validation errors, which may include invalid
            # recipients. Email not sent. response["To"] is not populated for this
            # error; must examine response["Message"]:
            if re.match(
                r"^(Invalid|Error\s+parsing)\s+'(To|Cc|Bcc)'", status_msg, re.IGNORECASE
            ):
                # Recipient-related errors: use AnymailRecipientsRefused logic
                # - "Invalid 'To' address: '{addr_spec}'."
                # - "Error parsing 'Cc': Illegal email domain '{domain}'
                #     in address '{addr_spec}'."
                # - "Error parsing 'Bcc': Illegal email address '{addr_spec}'.
                #     It must contain the '@' symbol."
                invalid_addr_specs = self._addr_specs_from_error_msg(
                    status_msg, r"address:?\s*'(.*)'"
                )
                for invalid_addr_spec in invalid_addr_specs:
                    recipient_status[invalid_addr_spec] = AnymailRecipientStatus(
                        message_id=None, status="invalid"
                    )
            else:
                # Non-recipient errors; handle as normal API error response
                # - "Invalid 'From' address: '{email_address}'."
                # - "Error parsing 'Reply-To': Illegal email domain '{domain}'
                #     in address '{addr_spec}'."
                # - "Invalid metadata content. ..."
                raise AnymailRequestsAPIError(
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                )

        else:  # Other error
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
        self.merge_data = None
        self.merge_metadata = None
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_request_params(self, api_url):
        params = super().get_request_params(api_url)
        params["headers"]["MailPace-Server-Token"] = self.server_token
        return params

    def serialize_data(self):
        return self.serialize_json(self.data)

    def data_for_recipient(self, to):
        data = self.data.copy()
        data["to"] = to.address
        return data

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
        if len(tags) > 0:
            self.data["tags"] = tags if len(tags) > 1 else tags[0]
