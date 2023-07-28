import uuid
import warnings
from email.utils import quote as rfc822_quote

from requests.structures import CaseInsensitiveDict

from ..exceptions import AnymailConfigurationError, AnymailWarning
from ..message import AnymailRecipientStatus
from ..utils import BASIC_NUMERIC_TYPES, Mapping, get_anymail_setting, update_deep
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    SendGrid v3 API Email Backend
    """

    esp_name = "SendGrid"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name

        # Warn if v2-only username or password settings found
        username = get_anymail_setting(
            "username", esp_name=esp_name, kwargs=kwargs, default=None, allow_bare=True
        )
        password = get_anymail_setting(
            "password", esp_name=esp_name, kwargs=kwargs, default=None, allow_bare=True
        )
        if username or password:
            raise AnymailConfigurationError(
                "SendGrid v3 API doesn't support username/password auth;"
                " Please change to API key."
            )

        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )

        self.generate_message_id = get_anymail_setting(
            "generate_message_id", esp_name=esp_name, kwargs=kwargs, default=True
        )
        self.merge_field_format = get_anymail_setting(
            "merge_field_format", esp_name=esp_name, kwargs=kwargs, default=None
        )

        # Undocumented setting to disable workaround for SendGrid display-name quoting
        # bug (see below). If/when SendGrid fixes their API, recipient names will end up
        # with extra double quotes until Anymail is updated to remove the workaround.
        # In the meantime, you can disable it by adding
        # `"SENDGRID_WORKAROUND_NAME_QUOTE_BUG": False` to your `ANYMAIL` settings.
        self.workaround_name_quote_bug = get_anymail_setting(
            "workaround_name_quote_bug", esp_name=esp_name, kwargs=kwargs, default=True
        )

        # This is SendGrid's newer Web API v3
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.sendgrid.com/v3/",
        )
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return SendGridPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        # If we get here, the "send" call was successful. (SendGrid uses a non-2xx
        # response for any failures, caught in raise_for_status.) SendGrid v3 doesn't
        # provide any information in the response for a successful send, so simulate a
        # per-recipient status of "queued":
        return {
            recip.addr_spec: AnymailRecipientStatus(
                message_id=payload.message_ids.get(recip.addr_spec), status="queued"
            )
            for recip in payload.all_recipients
        }


class SendGridPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.all_recipients = []  # used for backend.parse_recipient_status
        self.generate_message_id = backend.generate_message_id
        self.workaround_name_quote_bug = backend.workaround_name_quote_bug
        self.use_dynamic_template = False  # how to represent merge_data
        self.message_ids = {}  # recipient -> generated message_id mapping
        self.merge_field_format = backend.merge_field_format
        self.merge_data = {}  # late-bound per-recipient data
        self.merge_global_data = {}
        self.merge_metadata = {}

        http_headers = kwargs.pop("headers", {})
        http_headers["Authorization"] = "Bearer %s" % backend.api_key
        http_headers["Content-Type"] = "application/json"
        http_headers["Accept"] = "application/json"
        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self):
        return "mail/send"

    def init_payload(self):
        self.data = {  # becomes json
            "personalizations": [{}],
            "headers": CaseInsensitiveDict(),
        }

    def serialize_data(self):
        """Performs any necessary serialization on self.data, and returns the result."""
        if self.is_batch():
            self.expand_personalizations_for_batch()
        self.build_merge_data()
        self.build_merge_metadata()
        if self.generate_message_id:
            self.set_anymail_id()

        if not self.data["headers"]:
            del self.data["headers"]  # don't send empty headers

        return self.serialize_json(self.data)

    def set_anymail_id(self):
        """
        Ensure each personalization has a known anymail_id for later event tracking
        """
        for personalization in self.data["personalizations"]:
            message_id = str(uuid.uuid4())
            personalization.setdefault("custom_args", {})["anymail_id"] = message_id
            for recipient in (
                personalization["to"]
                + personalization.get("cc", [])
                + personalization.get("bcc", [])
            ):
                self.message_ids[recipient["email"]] = message_id

    def expand_personalizations_for_batch(self):
        """Split data["personalizations"] into individual message for each recipient"""
        assert len(self.data["personalizations"]) == 1
        base_personalization = self.data["personalizations"].pop()
        to_list = base_personalization.pop("to")  # {email, name?} for each message.to
        for recipient in to_list:
            personalization = base_personalization.copy()
            personalization["to"] = [recipient]
            self.data["personalizations"].append(personalization)

    def build_merge_data(self):
        if self.merge_data or self.merge_global_data:
            # Always build dynamic_template_data first,
            # then convert it to legacy template format if needed
            only_global_merge_data = self.merge_global_data and not self.merge_data
            for personalization in self.data["personalizations"]:
                assert len(personalization["to"]) == 1 or only_global_merge_data
                recipient_email = personalization["to"][0]["email"]
                dynamic_template_data = self.merge_global_data.copy()
                dynamic_template_data.update(self.merge_data.get(recipient_email, {}))
                if dynamic_template_data:
                    personalization["dynamic_template_data"] = dynamic_template_data

            if not self.use_dynamic_template:
                self.convert_dynamic_template_data_to_legacy_substitutions()

    def convert_dynamic_template_data_to_legacy_substitutions(self):
        """
        Change personalizations[...]['dynamic_template_data'] to ...['substitutions]
        """
        merge_field_format = self.merge_field_format or "{}"

        all_merge_fields = set()
        for personalization in self.data["personalizations"]:
            try:
                dynamic_template_data = personalization.pop("dynamic_template_data")
            except KeyError:
                pass  # no substitutions for this recipient
            else:
                # Convert dynamic_template_data keys for substitutions,
                # using merge_field_format
                personalization["substitutions"] = {
                    merge_field_format.format(field): data
                    for field, data in dynamic_template_data.items()
                }
                all_merge_fields.update(dynamic_template_data.keys())

        if self.merge_field_format is None:
            if all_merge_fields and all(field.isalnum() for field in all_merge_fields):
                warnings.warn(
                    "Your SendGrid merge fields don't seem to have delimiters, "
                    "which can cause unexpected results with Anymail's merge_data. "
                    "Search SENDGRID_MERGE_FIELD_FORMAT in the Anymail docs "
                    "for more info.",
                    AnymailWarning,
                )

            if self.merge_global_data and all(
                field.isalnum() for field in self.merge_global_data.keys()
            ):
                warnings.warn(
                    "Your SendGrid global merge fields don't seem to have delimiters, "
                    "which can cause unexpected results with Anymail's merge_data. "
                    "Search SENDGRID_MERGE_FIELD_FORMAT in the Anymail docs "
                    "for more info.",
                    AnymailWarning,
                )

    def build_merge_metadata(self):
        if self.merge_metadata:
            for personalization in self.data["personalizations"]:
                assert len(personalization["to"]) == 1
                recipient_email = personalization["to"][0]["email"]
                recipient_metadata = self.merge_metadata.get(recipient_email)
                if recipient_metadata:
                    recipient_custom_args = self.transform_metadata(recipient_metadata)
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
            self.data["personalizations"][0][recipient_type] = [
                self.email_object(email, workaround_name_quote_bug) for email in emails
            ]
            self.all_recipients += emails  # used for backend.parse_recipient_status

    def set_subject(self, subject):
        if subject != "":  # see note in set_text_body about template rendering
            self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            self.data["reply_to_list"] = [self.email_object(email) for email in emails]

    def set_extra_headers(self, headers):
        # SendGrid requires header values to be strings -- not integers.
        # We'll stringify ints and floats; anything else is the caller's responsibility.
        self.data["headers"].update(
            {
                k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
                for k, v in headers.items()
            }
        )

    def set_text_body(self, body):
        # Empty strings (the EmailMessage default) can cause unexpected SendGrid
        # template rendering behavior, such as ignoring the HTML template and
        # rendering HTML from the plaintext template instead.
        # Treat an empty string as a request to omit the body
        # (which means use the template content if present.)
        if body != "":
            self.data.setdefault("content", []).append(
                {
                    "type": "text/plain",
                    "value": body,
                }
            )

    def set_html_body(self, body):
        # SendGrid's API permits multiple html bodies
        # "If you choose to include the text/plain or text/html mime types, they must be
        # the first indices of the content array in the order text/plain, text/html."
        # Body must not be empty (see note in set_text_body about template rendering).
        if body != "":
            self.data.setdefault("content", []).append(
                {
                    "type": "text/html",
                    "value": body,
                }
            )

    def add_alternative(self, content, mimetype):
        # SendGrid is one of the few ESPs that supports arbitrary alternative parts
        self.data.setdefault("content", []).append(
            {
                "type": mimetype,
                "value": content,
            }
        )

    def add_attachment(self, attachment):
        att = {
            "content": attachment.b64content,
            "type": attachment.mimetype,
            # (filename is required -- submit empty string if unknown)
            "filename": attachment.name or "",
        }
        if attachment.inline:
            att["disposition"] = "inline"
            att["content_id"] = attachment.cid
        self.data.setdefault("attachments", []).append(att)

    def set_metadata(self, metadata):
        self.data["custom_args"] = self.transform_metadata(metadata)

    def transform_metadata(self, metadata):
        # SendGrid requires custom_args values to be strings -- not integers.
        # (And issues the cryptic error
        #    {"field": null, "message": "Bad Request", "help": null}
        # if they're not.)
        # Stringify ints and floats; anything else is the caller's responsibility.
        return {
            k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
            for k, v in metadata.items()
        }

    def set_send_at(self, send_at):
        # Backend has converted pretty much everything to
        # a datetime by here; SendGrid expects unix timestamp
        self.data["send_at"] = int(send_at.timestamp())  # strip microseconds

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
        self.merge_field_format = extra.pop(
            "merge_field_format", self.merge_field_format
        )
        self.use_dynamic_template = extra.pop(
            "use_dynamic_template", self.use_dynamic_template
        )
        if isinstance(extra.get("personalizations", None), Mapping):
            # merge personalizations *dict* into other message personalizations
            assert len(self.data["personalizations"]) == 1
            self.data["personalizations"][0].update(extra.pop("personalizations"))
        if "x-smtpapi" in extra:
            raise AnymailConfigurationError(
                "You are attempting to use SendGrid v2 API-style x-smtpapi params "
                "with the SendGrid v3 API. Please update your `esp_extra` "
                "to the new API."
            )
        update_deep(self.data, extra)
