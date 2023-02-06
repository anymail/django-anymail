from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting, update_deep
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    Mailjet API Email Backend
    """

    esp_name = "Mailjet"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        self.secret_key = get_anymail_setting(
            "secret_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.mailjet.com/v3.1/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailjetPayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        if 400 <= response.status_code <= 499:
            # Mailjet uses 4xx status codes for partial failure in batch send;
            # we'll determine how to handle below in parse_recipient_status.
            return
        super().raise_for_status(response, payload, message)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)

        # Global error? (no messages sent)
        if "ErrorCode" in parsed_response:
            raise AnymailRequestsAPIError(
                email_message=message, payload=payload, response=response, backend=self
            )

        recipient_status = {}
        try:
            for result in parsed_response["Messages"]:
                # result["Status"] is "success" or "error"
                status = "sent" if result["Status"] == "success" else "failed"
                recipients = (
                    result.get("To", []) + result.get("Cc", []) + result.get("Bcc", [])
                )
                for recipient in recipients:
                    email = recipient["Email"]
                    # other Mailjet APIs expect MessageID (not MessageUUID)
                    message_id = str(recipient["MessageID"])
                    recipient_status[email] = AnymailRecipientStatus(
                        message_id=message_id, status=status
                    )
                # For errors, Mailjet doesn't identify the problem recipients. (This
                # can occur with a batch send.) Patch up the missing recipients below.
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                "Invalid Mailjet API response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        # Any recipient who wasn't reported as a 'success' must have been an error:
        for email in payload.recipients:
            if email.addr_spec not in recipient_status:
                recipient_status[email.addr_spec] = AnymailRecipientStatus(
                    message_id=None, status="failed"
                )

        return recipient_status


class MailjetPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        auth = (backend.api_key, backend.secret_key)
        http_headers = {
            "Content-Type": "application/json",
        }
        self.recipients = []  # for backend parse_recipient_status
        self.metadata = None
        super().__init__(
            message, defaults, backend, auth=auth, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self):
        return "send"

    def serialize_data(self):
        return self.serialize_json(self.data)

    #
    # Payload construction
    #

    def init_payload(self):
        # The v3.1 Send payload. We use Globals for most parameters,
        # which simplifies batch sending if it's used (and if not,
        # still works as expected for ordinary send).
        # https://dev.mailjet.com/email/reference/send-emails#v3_1_post_send
        self.data = {
            "Globals": {},
            "Messages": [],
        }

    def _burst_for_batch_send(self):
        """Expand the payload Messages into a separate object for each To address"""
        # This can be called multiple times -- if the payload has already been burst,
        # it will have no effect.
        # For simplicity, this assumes that "To" is the only Messages param we use
        # (because everything else goes in Globals).
        if len(self.data["Messages"]) == 1:
            to_recipients = self.data["Messages"][0].get("To", [])
            self.data["Messages"] = [{"To": [to]} for to in to_recipients]

    @staticmethod
    def _mailjet_email(email):
        """Expand an Anymail EmailAddress into Mailjet's {"Email", "Name"} dict"""
        result = {"Email": email.addr_spec}
        if email.display_name:
            result["Name"] = email.display_name
        return result

    def set_from_email(self, email):
        self.data["Globals"]["From"] = self._mailjet_email(email)

    def set_to(self, emails):
        # "To" is the one non-batch param we transmit in Messages rather than Globals.
        # (See also _burst_for_batch_send, set_merge_data, and set_merge_metadata.)
        if len(self.data["Messages"]) > 0:
            # This case shouldn't happen. Please file a bug report if it does.
            raise AssertionError("set_to called with non-empty Messages list")
        if emails:
            self.data["Messages"].append(
                {"To": [self._mailjet_email(email) for email in emails]}
            )
            self.recipients += emails
        else:
            # Mailjet requires a To list; cc-only messages aren't possible
            self.unsupported_feature("messages without any `to` recipients")

    def set_cc(self, emails):
        if emails:
            self.data["Globals"]["Cc"] = [
                self._mailjet_email(email) for email in emails
            ]
            self.recipients += emails

    def set_bcc(self, emails):
        if emails:
            self.data["Globals"]["Bcc"] = [
                self._mailjet_email(email) for email in emails
            ]
            self.recipients += emails

    def set_subject(self, subject):
        self.data["Globals"]["Subject"] = subject

    def set_reply_to(self, emails):
        if len(emails) > 0:
            self.data["Globals"]["ReplyTo"] = self._mailjet_email(emails[0])
            if len(emails) > 1:
                self.unsupported_feature("Multiple reply_to addresses")

    def set_extra_headers(self, headers):
        self.data["Globals"]["Headers"] = headers

    def set_text_body(self, body):
        if body:  # Django's default empty text body confuses Mailjet (esp. templates)
            self.data["Globals"]["TextPart"] = body

    def set_html_body(self, body):
        if body is not None:
            if "HTMLPart" in self.data["Globals"]:
                # second html body could show up through multiple alternatives,
                # or html body + alternative
                self.unsupported_feature("multiple html parts")

            self.data["Globals"]["HTMLPart"] = body

    def add_attachment(self, attachment):
        att = {
            "ContentType": attachment.mimetype,
            "Filename": attachment.name or "",
            "Base64Content": attachment.b64content,
        }
        if attachment.inline:
            field = "InlinedAttachments"
            att["ContentID"] = attachment.cid
        else:
            field = "Attachments"
        self.data["Globals"].setdefault(field, []).append(att)

    def set_envelope_sender(self, email):
        self.data["Globals"]["Sender"] = self._mailjet_email(email)

    def set_metadata(self, metadata):
        # Mailjet expects a single string payload
        self.data["Globals"]["EventPayload"] = self.serialize_json(metadata)
        self.metadata = metadata  # save for set_merge_metadata

    def set_merge_metadata(self, merge_metadata):
        self._burst_for_batch_send()
        for message in self.data["Messages"]:
            email = message["To"][0]["Email"]
            if email in merge_metadata:
                if self.metadata:
                    recipient_metadata = self.metadata.copy()
                    recipient_metadata.update(merge_metadata[email])
                else:
                    recipient_metadata = merge_metadata[email]
                message["EventPayload"] = self.serialize_json(recipient_metadata)

    def set_tags(self, tags):
        # The choices here are CustomID or Campaign, and Campaign seems closer
        # to how "tags" are handled by other ESPs -- e.g., you can view dashboard
        # statistics across all messages with the same Campaign.
        if len(tags) > 0:
            self.data["Globals"]["CustomCampaign"] = tags[0]
            if len(tags) > 1:
                self.unsupported_feature("multiple tags (%r)" % tags)

    def set_track_clicks(self, track_clicks):
        self.data["Globals"]["TrackClicks"] = "enabled" if track_clicks else "disabled"

    def set_track_opens(self, track_opens):
        self.data["Globals"]["TrackOpens"] = "enabled" if track_opens else "disabled"

    def set_template_id(self, template_id):
        # Mailjet requires integer (not string) TemplateID:
        self.data["Globals"]["TemplateID"] = int(template_id)
        self.data["Globals"]["TemplateLanguage"] = True

    def set_merge_data(self, merge_data):
        self._burst_for_batch_send()
        for message in self.data["Messages"]:
            email = message["To"][0]["Email"]
            if email in merge_data:
                message["Variables"] = merge_data[email]

    def set_merge_global_data(self, merge_global_data):
        self.data["Globals"]["Variables"] = merge_global_data

    def set_esp_extra(self, extra):
        update_deep(self.data, extra)
