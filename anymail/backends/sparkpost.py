from .base_requests import AnymailRequestsBackend, RequestsPayload
from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting, update_deep


class EmailBackend(AnymailRequestsBackend):
    """
    SparkPost Email Backend
    """

    esp_name = "SparkPost"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        self.api_key = get_anymail_setting('api_key', esp_name=self.esp_name,
                                           kwargs=kwargs, allow_bare=True)
        self.subaccount = get_anymail_setting('subaccount', esp_name=self.esp_name,
                                              kwargs=kwargs, default=None)
        api_url = get_anymail_setting('api_url', esp_name=self.esp_name, kwargs=kwargs,
                                      default="https://api.sparkpost.com/api/v1/")
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return SparkPostPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)
        try:
            results = parsed_response["results"]
            accepted = results["total_accepted_recipients"]
            rejected = results["total_rejected_recipients"]
            transmission_id = results["id"]
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError("Invalid SparkPost API response format",
                                          email_message=message, payload=payload,
                                          response=response, backend=self) from err

        # SparkPost doesn't (yet*) tell us *which* recipients were accepted or rejected.
        # (* looks like undocumented 'rcpt_to_errors' might provide this info.)
        # If all are one or the other, we can report a specific status;
        # else just report 'unknown' for all recipients.
        recipient_count = len(payload.recipients)
        if accepted == recipient_count and rejected == 0:
            status = 'queued'
        elif rejected == recipient_count and accepted == 0:
            status = 'rejected'
        else:  # mixed results, or wrong total
            status = 'unknown'
        recipient_status = AnymailRecipientStatus(message_id=transmission_id, status=status)
        return {recipient.addr_spec: recipient_status for recipient in payload.recipients}


class SparkPostPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        http_headers = {
            'Authorization': backend.api_key,
            'Content-Type': 'application/json',
        }
        if backend.subaccount is not None:
            http_headers['X-MSYS-SUBACCOUNT'] = backend.subaccount
        self.recipients = []  # all recipients, for backend parse_recipient_status
        self.cc_and_bcc = []  # for _finalize_recipients
        super().__init__(message, defaults, backend, headers=http_headers, *args, **kwargs)

    def get_api_endpoint(self):
        return "transmissions/"

    def serialize_data(self):
        self._finalize_recipients()
        return self.serialize_json(self.data)

    def _finalize_recipients(self):
        # https://www.sparkpost.com/docs/faq/cc-bcc-with-rest-api/
        # self.data["recipients"] is currently a list of all to-recipients. We need to add
        # all cc and bcc recipients. Exactly how depends on whether this is a batch send.
        if self.is_batch():
            # For batch sends, must duplicate the cc/bcc for *every* to-recipient
            # (using each to-recipient's metadata and substitutions).
            extra_recipients = []
            for to_recipient in self.data["recipients"]:
                for email in self.cc_and_bcc:
                    extra = to_recipient.copy()  # capture "metadata" and "substitutions", if any
                    extra["address"] = {
                        "email": email.addr_spec,
                        "header_to": to_recipient["address"]["header_to"],
                    }
                    extra_recipients.append(extra)
            self.data["recipients"].extend(extra_recipients)
        else:
            # For non-batch sends, we need to patch up *everyone's* displayed
            # "To" header to show all the "To" recipients...
            full_to_header = ", ".join(
                to_recipient["address"]["header_to"]
                for to_recipient in self.data["recipients"])
            for recipient in self.data["recipients"]:
                recipient["address"]["header_to"] = full_to_header
            # ... and then simply add the cc/bcc to the end of the list.
            # (There is no per-recipient data, or it would be a batch send.)
            self.data["recipients"].extend(
                {"address": {
                    "email": email.addr_spec,
                    "header_to": full_to_header,
                }}
                for email in self.cc_and_bcc)

    #
    # Payload construction
    #

    def init_payload(self):
        # The JSON payload:
        self.data = {
            "content": {},
            "recipients": [],
        }

    def set_from_email(self, email):
        self.data["content"]["from"] = email.address

    def set_to(self, emails):
        if emails:
            # In the recipient address, "email" is the addr spec to deliver to,
            # and "header_to" is a fully-composed "To" header to display.
            # (We use "header_to" rather than "name" to simplify some logic
            # in _finalize_recipients; the results end up the same.)
            self.data["recipients"].extend(
                {"address": {
                    "email": email.addr_spec,
                    "header_to": email.address,
                }}
                for email in emails)
            self.recipients += emails

    def set_cc(self, emails):
        # https://www.sparkpost.com/docs/faq/cc-bcc-with-rest-api/
        if emails:
            # Add the Cc header, visible to all recipients:
            cc_header = ", ".join(email.address for email in emails)
            self.data["content"].setdefault("headers", {})["Cc"] = cc_header
            # Actual recipients are added later, in _finalize_recipients
            self.cc_and_bcc += emails
            self.recipients += emails

    def set_bcc(self, emails):
        if emails:
            # Actual recipients are added later, in _finalize_recipients
            self.cc_and_bcc += emails
            self.recipients += emails

    def set_subject(self, subject):
        self.data["content"]["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            self.data["content"]["reply_to"] = ", ".join(email.address for email in emails)

    def set_extra_headers(self, headers):
        if headers:
            self.data["content"].setdefault("headers", {}).update(headers)

    def set_text_body(self, body):
        self.data["content"]["text"] = body

    def set_html_body(self, body):
        if "html" in self.data["content"]:
            # second html body could show up through multiple alternatives, or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["content"]["html"] = body

    def add_alternative(self, content, mimetype):
        if mimetype.lower() == "text/x-amp-html":
            if "amp_html" in self.data["content"]:
                self.unsupported_feature("multiple html parts")
            self.data["content"]["amp_html"] = content
        else:
            super().add_alternative(content, mimetype)

    def set_attachments(self, atts):
        attachments = [{
            "name": att.name or "",
            "type": att.content_type,
            "data": att.b64content,
        } for att in atts if not att.inline]
        if attachments:
            self.data["content"]["attachments"] = attachments

        inline_images = [{
            "name": att.cid,
            "type": att.mimetype,
            "data": att.b64content,
        } for att in atts if att.inline]
        if inline_images:
            self.data["content"]["inline_images"] = inline_images

    # Anymail-specific payload construction
    def set_envelope_sender(self, email):
        self.data["return_path"] = email.addr_spec

    def set_metadata(self, metadata):
        self.data["metadata"] = metadata

    def set_merge_metadata(self, merge_metadata):
        for recipient in self.data["recipients"]:
            to_email = recipient["address"]["email"]
            if to_email in merge_metadata:
                recipient["metadata"] = merge_metadata[to_email]

    def set_send_at(self, send_at):
        try:
            start_time = send_at.replace(microsecond=0).isoformat()
        except (AttributeError, TypeError):
            start_time = send_at  # assume user already formatted
        self.data.setdefault("options", {})["start_time"] = start_time

    def set_tags(self, tags):
        if len(tags) > 0:
            self.data["campaign_id"] = tags[0]
            if len(tags) > 1:
                self.unsupported_feature("multiple tags (%r)" % tags)

    def set_track_clicks(self, track_clicks):
        self.data.setdefault("options", {})["click_tracking"] = track_clicks

    def set_track_opens(self, track_opens):
        self.data.setdefault("options", {})["open_tracking"] = track_opens

    def set_template_id(self, template_id):
        self.data["content"]["template_id"] = template_id
        # Must remove empty string "content" params when using stored template
        for content_param in ["subject", "text", "html"]:
            try:
                if not self.data["content"][content_param]:
                    del self.data["content"][content_param]
            except KeyError:
                pass

    def set_merge_data(self, merge_data):
        for recipient in self.data["recipients"]:
            to_email = recipient["address"]["email"]
            if to_email in merge_data:
                recipient["substitution_data"] = merge_data[to_email]

    def set_merge_global_data(self, merge_global_data):
        self.data["substitution_data"] = merge_global_data

    # ESP-specific payload construction
    def set_esp_extra(self, extra):
        update_deep(self.data, extra)
