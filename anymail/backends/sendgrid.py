import uuid
import warnings
from email.utils import quote as rfc822_quote

from requests.structures import CaseInsensitiveDict

from .base_requests import AnymailRequestsBackend, RequestsPayload
from ..exceptions import AnymailConfigurationError, AnymailRequestsAPIError, AnymailWarning
from ..message import AnymailRecipientStatus
from ..utils import BASIC_NUMERIC_TYPES, Mapping, get_anymail_setting, timestamp, update_deep


class EmailBackend(AnymailRequestsBackend):
    """
    SendGrid v3 API Email Backend
    """

    esp_name = "SendGrid"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name

        # Warn if v2-only username or password settings found
        username = get_anymail_setting('username', esp_name=esp_name, kwargs=kwargs, default=None, allow_bare=True)
        password = get_anymail_setting('password', esp_name=esp_name, kwargs=kwargs, default=None, allow_bare=True)
        if username or password:
            raise AnymailConfigurationError(
                "SendGrid v3 API doesn't support username/password auth; Please change to API key.")

        self.api_key = get_anymail_setting('api_key', esp_name=esp_name, kwargs=kwargs, allow_bare=True)

        self.generate_message_id = get_anymail_setting('generate_message_id', esp_name=esp_name,
                                                       kwargs=kwargs, default=True)
        self.merge_field_format = get_anymail_setting('merge_field_format', esp_name=esp_name,
                                                      kwargs=kwargs, default=None)

        # Undocumented setting to disable workaround for SendGrid display-name quoting bug (see below).
        # If/when SendGrid fixes their API, recipient names will end up with extra double quotes
        # until Anymail is updated to remove the workaround. In the meantime, you can disable it
        # by adding `"SENDGRID_WORKAROUND_NAME_QUOTE_BUG": False` to your `ANYMAIL` settings.
        self.workaround_name_quote_bug = get_anymail_setting('workaround_name_quote_bug', esp_name=esp_name,
                                                             kwargs=kwargs, default=True)

        # This is SendGrid's newer Web API v3
        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs,
                                      default="https://api.sendgrid.com/v3/")
        if not api_url.endswith("/"):
            api_url += "/"
        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return SendGridPayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        if response.status_code < 200 or response.status_code >= 300:
            raise AnymailRequestsAPIError(email_message=message, payload=payload, response=response,
                                          backend=self)

    def parse_recipient_status(self, response, payload, message):
        # If we get here, the send call was successful.
        # (SendGrid uses a non-2xx response for any failures, caught in raise_for_status.)
        # SendGrid v3 doesn't provide any information in the response for a successful send,
        # so simulate a per-recipient status of "queued":
        status = AnymailRecipientStatus(message_id=payload.message_id, status="queued")
        return {recipient.addr_spec: status for recipient in payload.all_recipients}


class SendGridPayload(RequestsPayload):

    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.all_recipients = []  # used for backend.parse_recipient_status
        self.generate_message_id = backend.generate_message_id
        self.workaround_name_quote_bug = backend.workaround_name_quote_bug
        self.use_dynamic_template = False  # how to represent merge_data
        self.message_id = None  # Message-ID -- assigned in serialize_data unless provided in headers
        self.merge_field_format = backend.merge_field_format
        self.merge_data = None  # late-bound per-recipient data
        self.merge_global_data = None
        self.merge_metadata = None

        http_headers = kwargs.pop('headers', {})
        http_headers['Authorization'] = 'Bearer %s' % backend.api_key
        http_headers['Content-Type'] = 'application/json'
        http_headers['Accept'] = 'application/json'
        super(SendGridPayload, self).__init__(message, defaults, backend,
                                              headers=http_headers,
                                              *args, **kwargs)

    def get_api_endpoint(self):
        return "mail/send"

    def init_payload(self):
        self.data = {  # becomes json
            "personalizations": [{}],
            "headers": CaseInsensitiveDict(),
        }

    def serialize_data(self):
        """Performs any necessary serialization on self.data, and returns the result."""

        if self.generate_message_id:
            self.set_anymail_id()
        self.build_merge_data()
        self.build_merge_metadata()

        if not self.data["headers"]:
            del self.data["headers"]  # don't send empty headers

        return self.serialize_json(self.data)

    def set_anymail_id(self):
        """Ensure message has a known anymail_id for later event tracking"""

        self.message_id = str(uuid.uuid4())
        self.data.setdefault("custom_args", {})["anymail_id"] = self.message_id

    def build_merge_data(self):
        if self.use_dynamic_template:
            self.build_merge_data_dynamic()
        else:
            self.build_merge_data_legacy()

    def build_merge_data_dynamic(self):
        """Set personalizations[...]['dynamic_template_data']"""
        if self.merge_global_data is not None:
            assert len(self.data["personalizations"]) == 1
            self.data["personalizations"][0].setdefault(
                "dynamic_template_data", {}).update(self.merge_global_data)

        if self.merge_data is not None:
            # Burst apart each to-email in personalizations[0] into a separate
            # personalization, and add merge_data for that recipient
            assert len(self.data["personalizations"]) == 1
            base_personalizations = self.data["personalizations"].pop()
            to_list = base_personalizations.pop("to")  # {email, name?} for each message.to
            for recipient in to_list:
                personalization = base_personalizations.copy()  # captures cc, bcc, merge_global_data, esp_extra
                personalization["to"] = [recipient]
                try:
                    recipient_data = self.merge_data[recipient["email"]]
                except KeyError:
                    pass  # no merge_data for this recipient
                else:
                    if "dynamic_template_data" in personalization:
                        # merge per-recipient data into (copy of) merge_global_data
                        personalization["dynamic_template_data"] = personalization["dynamic_template_data"].copy()
                        personalization["dynamic_template_data"].update(recipient_data)
                    else:
                        personalization["dynamic_template_data"] = recipient_data
                self.data["personalizations"].append(personalization)

    def build_merge_data_legacy(self):
        """Set personalizations[...]['substitutions'] and data['sections']"""
        merge_field_format = self.merge_field_format or '{}'

        if self.merge_data is not None:
            # Burst apart each to-email in personalizations[0] into a separate
            # personalization, and add merge_data for that recipient
            assert len(self.data["personalizations"]) == 1
            base_personalizations = self.data["personalizations"].pop()
            to_list = base_personalizations.pop("to")  # {email, name?} for each message.to
            all_fields = set()
            for recipient in to_list:
                personalization = base_personalizations.copy()  # captures cc, bcc, and any esp_extra
                personalization["to"] = [recipient]
                try:
                    recipient_data = self.merge_data[recipient["email"]]
                    personalization["substitutions"] = {merge_field_format.format(field): data
                                                        for field, data in recipient_data.items()}
                    all_fields = all_fields.union(recipient_data.keys())
                except KeyError:
                    pass  # no merge_data for this recipient
                self.data["personalizations"].append(personalization)

            if self.merge_field_format is None and len(all_fields) and all(field.isalnum() for field in all_fields):
                warnings.warn(
                    "Your SendGrid merge fields don't seem to have delimiters, "
                    "which can cause unexpected results with Anymail's merge_data. "
                    "Search SENDGRID_MERGE_FIELD_FORMAT in the Anymail docs for more info.",
                    AnymailWarning)

        if self.merge_global_data is not None:
            # (merge into any existing 'sections' from esp_extra)
            self.data.setdefault("sections", {}).update({
                merge_field_format.format(field): data
                for field, data in self.merge_global_data.items()
            })

            # Confusingly, "Section tags have to be contained within a Substitution tag"
            # (https://sendgrid.com/docs/API_Reference/SMTP_API/section_tags.html),
            # so we need to insert a "-field-": "-field-" identity fallback for each
            # missing global field in the recipient substitutions...
            global_fields = [merge_field_format.format(field)
                             for field in self.merge_global_data.keys()]
            for personalization in self.data["personalizations"]:
                substitutions = personalization.setdefault("substitutions", {})
                substitutions.update({field: field for field in global_fields
                                      if field not in substitutions})

            if (self.merge_field_format is None and
                    all(field.isalnum() for field in self.merge_global_data.keys())):
                warnings.warn(
                    "Your SendGrid global merge fields don't seem to have delimiters, "
                    "which can cause unexpected results with Anymail's merge_data. "
                    "Search SENDGRID_MERGE_FIELD_FORMAT in the Anymail docs for more info.",
                    AnymailWarning)

    def build_merge_metadata(self):
        if self.merge_metadata is None:
            return

        if self.merge_data is not None:
            # Burst apart each to-email in personalizations[0] into a separate
            # personalization, and add merge_metadata for that recipient
            assert len(self.data["personalizations"]) == 1
            base_personalizations = self.data["personalizations"].pop()
            to_list = base_personalizations.pop("to")  # {email, name?} for each message.to
            for recipient in to_list:
                personalization = base_personalizations.copy()  # captures cc, bcc, and any esp_extra
                personalization["to"] = [recipient]
                self.data["personalizations"].append(personalization)

        for personalization in self.data["personalizations"]:
            recipient_email = personalization["to"][0]["email"]
            recipient_metadata = self.merge_metadata.get(recipient_email)
            if recipient_metadata:
                recipient_custom_args = self.transform_metadata(recipient_metadata)

                if self.data.get("custom_args"):
                    merged_custom_args = {}
                    merged_custom_args.update(self.data.get("custom_args"))
                    merged_custom_args.update(recipient_custom_args)
                    recipient_custom_args = merged_custom_args
                    del self.data["custom_args"]

                personalization["custom_args"] = recipient_custom_args

    #
    # Payload construction
    #

    @staticmethod
    def email_object(email, workaround_name_quote_bug=False):
        """Converts EmailAddress to SendGrid API {email, name} dict"""
        obj = {"email": email.addr_spec}
        if email.display_name:
            # Work around SendGrid API bug: v3 fails to properly quote display-names
            # containing commas or semicolons in personalizations (but not in from_email
            # or reply_to). See https://github.com/sendgrid/sendgrid-python/issues/291.
            # We can work around the problem by quoting the name for SendGrid.
            if workaround_name_quote_bug:
                obj["name"] = '"%s"' % rfc822_quote(email.display_name)
            else:
                obj["name"] = email.display_name
        return obj

    def set_from_email(self, email):
        self.data["from"] = self.email_object(email)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            workaround_name_quote_bug = self.workaround_name_quote_bug
            # Normally, exactly one "personalizations" entry for all recipients
            # (Exception: with merge_data; will be burst apart later.)
            self.data["personalizations"][0][recipient_type] = \
                [self.email_object(email, workaround_name_quote_bug) for email in emails]
            self.all_recipients += emails  # used for backend.parse_recipient_status

    def set_subject(self, subject):
        if subject != "":  # see note in set_text_body about template rendering
            self.data["subject"] = subject

    def set_reply_to(self, emails):
        # SendGrid only supports a single address in the reply_to API param.
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if len(emails) > 0:
            self.data["reply_to"] = self.email_object(emails[0])

    def set_extra_headers(self, headers):
        # SendGrid requires header values to be strings -- not integers.
        # We'll stringify ints and floats; anything else is the caller's responsibility.
        self.data["headers"].update({
            k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
            for k, v in headers.items()
        })

    def set_text_body(self, body):
        # Empty strings (the EmailMessage default) can cause unexpected SendGrid
        # template rendering behavior, such as ignoring the HTML template and
        # rendering HTML from the plaintext template instead.
        # Treat an empty string as a request to omit the body
        # (which means use the template content if present.)
        if body != "":
            self.data.setdefault("content", []).append({
                "type": "text/plain",
                "value": body,
            })

    def set_html_body(self, body):
        # SendGrid's API permits multiple html bodies
        # "If you choose to include the text/plain or text/html mime types, they must be
        # the first indices of the content array in the order text/plain, text/html."
        if body != "":  # see note in set_text_body about template rendering
            self.data.setdefault("content", []).append({
                "type": "text/html",
                "value": body,
            })

    def add_alternative(self, content, mimetype):
        # SendGrid is one of the few ESPs that supports arbitrary alternative parts in their API
        self.data.setdefault("content", []).append({
            "type": mimetype,
            "value": content,
        })

    def add_attachment(self, attachment):
        att = {
            "content": attachment.b64content,
            "type": attachment.mimetype,
            "filename": attachment.name or '',  # required -- submit empty string if unknown
        }
        if attachment.inline:
            att["disposition"] = "inline"
            att["content_id"] = attachment.cid
        self.data.setdefault("attachments", []).append(att)

    def set_metadata(self, metadata):
        self.data["custom_args"] = self.transform_metadata(metadata)

    def transform_metadata(self, metadata):
        # SendGrid requires custom_args values to be strings -- not integers.
        # (And issues the cryptic error {"field": null, "message": "Bad Request", "help": null}
        # if they're not.)
        # We'll stringify ints and floats; anything else is the caller's responsibility.
        return {
            k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
            for k, v in metadata.items()
        }

    def set_send_at(self, send_at):
        # Backend has converted pretty much everything to
        # a datetime by here; SendGrid expects unix timestamp
        self.data["send_at"] = int(timestamp(send_at))  # strip microseconds

    def set_tags(self, tags):
        self.data["categories"] = tags

    def set_track_clicks(self, track_clicks):
        self.data.setdefault("tracking_settings", {})["click_tracking"] = {
            "enable": track_clicks,
        }

    def set_track_opens(self, track_opens):
        # SendGrid's open_tracking setting also supports a "substitution_tag" parameter,
        # which Anymail doesn't offer directly. (You could add it through esp_extra.)
        self.data.setdefault("tracking_settings", {})["open_tracking"] = {
            "enable": track_opens,
        }

    def set_template_id(self, template_id):
        self.data["template_id"] = template_id
        try:
            self.use_dynamic_template = template_id.startswith("d-")
        except AttributeError:
            pass

    def set_merge_data(self, merge_data):
        # Becomes personalizations[...]['dynamic_template_data']
        # or personalizations[...]['substitutions'] in build_merge_data,
        # after we know recipients, template type, and merge_field_format.
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        # Becomes personalizations[...]['dynamic_template_data']
        # or data['section'] in build_merge_data, after we know
        # template type and merge_field_format.
        self.merge_global_data = merge_global_data

    def set_merge_metadata(self, merge_metadata):
        # Becomes personalizations[...]['custom_args'] in
        # build_merge_data, after we know recipients, template type,
        # and merge_field_format.
        self.merge_metadata = merge_metadata

    def set_esp_extra(self, extra):
        self.merge_field_format = extra.pop("merge_field_format", self.merge_field_format)
        self.use_dynamic_template = extra.pop("use_dynamic_template", self.use_dynamic_template)
        if isinstance(extra.get("personalizations", None), Mapping):
            # merge personalizations *dict* into other message personalizations
            assert len(self.data["personalizations"]) == 1
            self.data["personalizations"][0].update(extra.pop("personalizations"))
        if "x-smtpapi" in extra:
            raise AnymailConfigurationError(
                "You are attempting to use SendGrid v2 API-style x-smtpapi params "
                "with the SendGrid v3 API. Please update your `esp_extra` to the new API."
            )
        update_deep(self.data, extra)
