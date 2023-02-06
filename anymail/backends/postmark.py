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
    Postmark API Email Backend
    """

    esp_name = "Postmark"

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
            default="https://api.postmarkapp.com/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return PostmarkPayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        # We need to handle 422 responses in parse_recipient_status
        if response.status_code != 422:
            super().raise_for_status(response, payload, message)

    def parse_recipient_status(self, response, payload, message):
        # Default to "unknown" status for each recipient, unless/until we find
        # otherwise. (This also forces recipient_status email capitalization to match
        # that as sent, while correctly handling Postmark's lowercase-only inactive
        # recipient reporting.)
        unknown_status = AnymailRecipientStatus(message_id=None, status="unknown")
        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: unknown_status
                for recip in payload.to_emails + payload.cc_and_bcc_emails
            }
        )

        parsed_response = self.deserialize_json_response(response, payload, message)
        if not isinstance(parsed_response, list):
            # non-batch calls return a single response object
            parsed_response = [parsed_response]

        for one_response in parsed_response:
            try:
                # these fields should always be present
                error_code = one_response["ErrorCode"]
                msg = one_response["Message"]
            except (KeyError, TypeError) as err:
                raise AnymailRequestsAPIError(
                    "Invalid Postmark API response format",
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                ) from err

            if error_code == 0:
                # At least partial success, and (some) email was sent.
                try:
                    message_id = one_response["MessageID"]
                except KeyError as err:
                    raise AnymailRequestsAPIError(
                        "Invalid Postmark API success response format",
                        email_message=message,
                        payload=payload,
                        response=response,
                        backend=self,
                    ) from err

                # Assume all To recipients are "sent" unless proven otherwise below.
                # (Must use "To" from API response to get correct individual MessageIDs
                # in batch send.)
                try:
                    to_header = one_response["To"]  # (missing if cc- or bcc-only send)
                except KeyError:
                    pass  # cc- or bcc-only send; per-recipient status not available
                else:
                    for to in parse_address_list(to_header):
                        recipient_status[to.addr_spec] = AnymailRecipientStatus(
                            message_id=message_id, status="sent"
                        )

                # Assume all Cc and Bcc recipients are "sent" unless proven otherwise
                # below. (Postmark doesn't report "Cc" or "Bcc" in API response; use
                # original payload values.)
                for recip in payload.cc_and_bcc_emails:
                    recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                        message_id=message_id, status="sent"
                    )

                # Change "sent" to "rejected" if Postmark reported an address as
                # "Inactive". Sadly, have to parse human-readable message to figure out
                # if everyone got it:
                #   "Message OK, but will not deliver to these inactive addresses:
                #    {addr_spec, ...}. Inactive recipients are ones that have generated
                #    a hard bounce or a spam complaint."
                # Note that error message emails are addr_spec only (no display names)
                # and forced lowercase.
                reject_addr_specs = self._addr_specs_from_error_msg(
                    msg, r"inactive addresses:\s*(.*)\.\s*Inactive recipients"
                )
                for reject_addr_spec in reject_addr_specs:
                    recipient_status[reject_addr_spec] = AnymailRecipientStatus(
                        message_id=None, status="rejected"
                    )

            elif error_code == 300:  # Invalid email request
                # Various parse-time validation errors, which may include invalid
                # recipients. Email not sent. response["To"] is not populated for this
                # error; must examine response["Message"]:
                if re.match(
                    r"^(Invalid|Error\s+parsing)\s+'(To|Cc|Bcc)'", msg, re.IGNORECASE
                ):
                    # Recipient-related errors: use AnymailRecipientsRefused logic
                    # - "Invalid 'To' address: '{addr_spec}'."
                    # - "Error parsing 'Cc': Illegal email domain '{domain}'
                    #     in address '{addr_spec}'."
                    # - "Error parsing 'Bcc': Illegal email address '{addr_spec}'.
                    #     It must contain the '@' symbol."
                    invalid_addr_specs = self._addr_specs_from_error_msg(
                        msg, r"address:?\s*'(.*)'"
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

            elif error_code == 406:  # Inactive recipient
                # All recipients were rejected as hard-bounce or spam-complaint. Email
                # not sent. response["To"] is not populated for this error; must examine
                # response["Message"]:
                #   "You tried to send to a recipient that has been marked as
                #    inactive.\n Found inactive addresses: {addr_spec, ...}.\n
                #    Inactive recipients are ones that have generated a hard bounce
                #    or a spam complaint. "
                reject_addr_specs = self._addr_specs_from_error_msg(
                    msg, r"inactive addresses:\s*(.*)\.\s*Inactive recipients"
                )
                for reject_addr_spec in reject_addr_specs:
                    recipient_status[reject_addr_spec] = AnymailRecipientStatus(
                        message_id=None, status="rejected"
                    )

            else:  # Other error
                raise AnymailRequestsAPIError(
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                )

        return dict(recipient_status)

    @staticmethod
    def _addr_specs_from_error_msg(error_msg, pattern):
        """Extract a list of email addr_specs from Postmark error_msg.

        pattern must be a re whose first group matches a comma-separated
        list of addr_specs in the message
        """
        match = re.search(pattern, error_msg, re.MULTILINE)
        if match:
            emails = match.group(1)  # "one@xample.com, two@example.com"
            return [email.strip().lower() for email in emails.split(",")]
        else:
            return []


class PostmarkPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # "X-Postmark-Server-Token": see get_request_params (and set_esp_extra)
        }
        self.server_token = backend.server_token  # esp_extra can override
        self.to_emails = []
        self.cc_and_bcc_emails = []  # needed for parse_recipient_status
        self.merge_data = None
        self.merge_metadata = None
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        batch_send = self.is_batch()
        if (
            "TemplateAlias" in self.data
            or "TemplateId" in self.data
            or "TemplateModel" in self.data
        ):
            if batch_send:
                return "email/batchWithTemplates"
            else:
                # This is the one Postmark API documented to have a trailing slash.
                # (Typo?)
                return "email/withTemplate/"
        else:
            if batch_send:
                return "email/batch"
            else:
                return "email"

    def get_request_params(self, api_url):
        params = super().get_request_params(api_url)
        params["headers"]["X-Postmark-Server-Token"] = self.server_token
        return params

    def serialize_data(self):
        api_endpoint = self.get_api_endpoint()
        if api_endpoint == "email":
            data = self.data
        elif api_endpoint == "email/batchWithTemplates":
            data = {"Messages": [self.data_for_recipient(to) for to in self.to_emails]}
        elif api_endpoint == "email/batch":
            data = [self.data_for_recipient(to) for to in self.to_emails]
        elif api_endpoint == "email/withTemplate/":
            assert (
                self.merge_data is None and self.merge_metadata is None
            )  # else it's a batch send
            data = self.data
        else:
            raise AssertionError(
                "PostmarkPayload.serialize_data missing"
                " case for api_endpoint %r" % api_endpoint
            )
        return self.serialize_json(data)

    def data_for_recipient(self, to):
        data = self.data.copy()
        data["To"] = to.address
        if self.merge_data and to.addr_spec in self.merge_data:
            recipient_data = self.merge_data[to.addr_spec]
            if "TemplateModel" in data:
                # merge recipient_data into merge_global_data
                data["TemplateModel"] = data["TemplateModel"].copy()
                data["TemplateModel"].update(recipient_data)
            else:
                data["TemplateModel"] = recipient_data
        if self.merge_metadata and to.addr_spec in self.merge_metadata:
            recipient_metadata = self.merge_metadata[to.addr_spec]
            if "Metadata" in data:
                # merge recipient_metadata into toplevel metadata
                data["Metadata"] = data["Metadata"].copy()
                data["Metadata"].update(recipient_metadata)
            else:
                data["Metadata"] = recipient_metadata
        return data

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email_list(self, emails):
        # Postmark accepts multiple From email addresses
        # (though truncates to just the first, on their end, as of 4/2017)
        self.data["From"] = ", ".join([email.address for email in emails])

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            field = recipient_type.capitalize()
            self.data[field] = ", ".join([email.address for email in emails])
            if recipient_type == "to":
                self.to_emails = emails
            else:
                self.cc_and_bcc_emails += emails

    def set_subject(self, subject):
        self.data["Subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            reply_to = ", ".join([email.address for email in emails])
            self.data["ReplyTo"] = reply_to

    def set_extra_headers(self, headers):
        self.data["Headers"] = [
            {"Name": key, "Value": value} for key, value in headers.items()
        ]

    def set_text_body(self, body):
        self.data["TextBody"] = body

    def set_html_body(self, body):
        if "HtmlBody" in self.data:
            # second html body could show up through multiple alternatives,
            # or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["HtmlBody"] = body

    def make_attachment(self, attachment):
        """Returns Postmark attachment dict for attachment"""
        att = {
            "Name": attachment.name or "",
            "Content": attachment.b64content,
            "ContentType": attachment.mimetype,
        }
        if attachment.inline:
            att["ContentID"] = "cid:%s" % attachment.cid
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["Attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_metadata(self, metadata):
        self.data["Metadata"] = metadata

    # Postmark doesn't support delayed sending
    # def set_send_at(self, send_at):

    def set_tags(self, tags):
        if len(tags) > 0:
            self.data["Tag"] = tags[0]
            if len(tags) > 1:
                self.unsupported_feature("multiple tags (%r)" % tags)

    def set_track_clicks(self, track_clicks):
        self.data["TrackLinks"] = "HtmlAndText" if track_clicks else "None"

    def set_track_opens(self, track_opens):
        self.data["TrackOpens"] = track_opens

    def set_template_id(self, template_id):
        try:
            self.data["TemplateId"] = int(template_id)
        except ValueError:
            self.data["TemplateAlias"] = template_id

        # Postmark requires TemplateModel (empty ok) when TemplateId/TemplateAlias
        # specified. (This may get overwritten by a real TemplateModel later.)
        self.data.setdefault("TemplateModel", {})

        # Subject, TextBody, and HtmlBody aren't allowed with TemplateId;
        # delete Django default subject and body empty strings:
        for field in ("Subject", "TextBody", "HtmlBody"):
            if field in self.data and not self.data[field]:
                del self.data[field]

    def set_merge_data(self, merge_data):
        # late-bind
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        self.data["TemplateModel"] = merge_global_data

    def set_merge_metadata(self, merge_metadata):
        # late-bind
        self.merge_metadata = merge_metadata

    def set_esp_extra(self, extra):
        self.data.update(extra)
        # Special handling for 'server_token':
        self.server_token = self.data.pop("server_token", self.server_token)
