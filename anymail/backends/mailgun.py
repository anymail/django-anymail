from datetime import datetime
from email.utils import encode_rfc2231
from urllib.parse import quote

from requests import Request

from .base_requests import AnymailRequestsBackend, RequestsPayload
from ..exceptions import AnymailError, AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting, rfc2822date


# Feature-detect whether requests (urllib3) correctly uses RFC 7578 encoding for non-
# ASCII filenames in Content-Disposition headers. (This was fixed in urllib3 v1.25.)
# See MailgunPayload.get_request_params for info (and a workaround on older versions).
# (Note: when this workaround is removed, please also remove the "old_urllib3" tox envs.)
def is_requests_rfc_5758_compliant():
    request = Request(method='POST', url='https://www.example.com',
                      files=[('attachment', ('\N{NOT SIGN}.txt', 'test', 'text/plain'))])
    prepared = request.prepare()
    form_data = prepared.body  # bytes
    return b'filename*=' not in form_data


REQUESTS_IS_RFC_7578_COMPLIANT = is_requests_rfc_5758_compliant()


class EmailBackend(AnymailRequestsBackend):
    """
    Mailgun API Email Backend
    """

    esp_name = "Mailgun"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting('api_key', esp_name=esp_name, kwargs=kwargs, allow_bare=True)
        self.sender_domain = get_anymail_setting('sender_domain', esp_name=esp_name, kwargs=kwargs,
                                                 allow_bare=True, default=None)
        api_url = get_anymail_setting('api_url', esp_name=esp_name, kwargs=kwargs,
                                      default="https://api.mailgun.net/v3")
        if not api_url.endswith("/"):
            api_url += "/"
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailgunPayload(message, defaults, self)

    def raise_for_status(self, response, payload, message):
        # Mailgun issues a terse 404 for unrecognized sender domains.
        # Add some context:
        if response.status_code == 404 and "Domain not found" in response.text:
            raise AnymailRequestsAPIError(
                "Unknown sender domain {sender_domain!r}.\n"
                "Check the domain is verified with Mailgun, and that the ANYMAIL"
                " MAILGUN_API_URL setting {api_url!r} is the correct region.".format(
                    sender_domain=payload.sender_domain, api_url=self.api_url),
                email_message=message, payload=payload,
                response=response, backend=self)

        super().raise_for_status(response, payload, message)

        # Mailgun issues a cryptic "Mailgun Magnificent API" success response
        # for invalid API endpoints. Convert that to a useful error:
        if response.status_code == 200 and "Mailgun Magnificent API" in response.text:
            raise AnymailRequestsAPIError(
                "Invalid Mailgun API endpoint %r.\n"
                "Check your ANYMAIL MAILGUN_SENDER_DOMAIN"
                " and MAILGUN_API_URL settings." % response.url,
                email_message=message, payload=payload,
                response=response, backend=self)

    def parse_recipient_status(self, response, payload, message):
        # The *only* 200 response from Mailgun seems to be:
        #     {
        #       "id": "<20160306015544.116301.25145@example.org>",
        #       "message": "Queued. Thank you."
        #     }
        #
        # That single message id applies to all recipients.
        # The only way to detect rejected, etc. is via webhooks.
        # (*Any* invalid recipient addresses will generate a 400 API error)
        parsed_response = self.deserialize_json_response(response, payload, message)
        try:
            message_id = parsed_response["id"]
            mailgun_message = parsed_response["message"]
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError("Invalid Mailgun API response format",
                                          email_message=message, payload=payload, response=response,
                                          backend=self) from err
        if not mailgun_message.startswith("Queued"):
            raise AnymailRequestsAPIError("Unrecognized Mailgun API message '%s'" % mailgun_message,
                                          email_message=message, payload=payload, response=response,
                                          backend=self)
        # Simulate a per-recipient status of "queued":
        status = AnymailRecipientStatus(message_id=message_id, status="queued")
        return {recipient.addr_spec: status for recipient in payload.all_recipients}


class MailgunPayload(RequestsPayload):

    def __init__(self, message, defaults, backend, *args, **kwargs):
        auth = ("api", backend.api_key)
        self.sender_domain = backend.sender_domain
        self.all_recipients = []  # used for backend.parse_recipient_status

        # late-binding of recipient-variables:
        self.merge_data = {}
        self.merge_global_data = {}
        self.metadata = {}
        self.merge_metadata = {}
        self.to_emails = []

        super().__init__(message, defaults, backend, auth=auth, *args, **kwargs)

    def get_api_endpoint(self):
        if self.sender_domain is None:
            raise AnymailError("Cannot call Mailgun unknown sender domain. "
                               "Either provide valid `from_email`, "
                               "or set `message.esp_extra={'sender_domain': 'example.com'}`",
                               backend=self.backend, email_message=self.message, payload=self)
        if '/' in self.sender_domain or '%2f' in self.sender_domain.lower():
            # Mailgun returns a cryptic 200-OK "Mailgun Magnificent API" response
            # if '/' (or even %-encoded '/') confuses it about the API endpoint.
            raise AnymailError("Invalid '/' in sender domain '%s'" % self.sender_domain,
                               backend=self.backend, email_message=self.message, payload=self)
        return "%s/messages" % quote(self.sender_domain, safe='')

    def get_request_params(self, api_url):
        params = super().get_request_params(api_url)
        non_ascii_filenames = [filename
                               for (field, (filename, content, mimetype)) in params["files"]
                               if filename is not None and not isascii(filename)]
        if non_ascii_filenames and not REQUESTS_IS_RFC_7578_COMPLIANT:
            # Workaround https://github.com/requests/requests/issues/4652:
            # Mailgun expects RFC 7578 compliant multipart/form-data, and is confused
            # by Requests/urllib3's improper use of RFC 2231 encoded filename parameters
            # ("filename*=utf-8''...") in Content-Disposition headers.
            # The workaround is to pre-generate the (non-compliant) form-data body, and
            # replace 'filename*={RFC 2231 encoded}' with 'filename="{UTF-8 bytes}"'.
            # Replace _only_ the filenames that will be problems (not all "filename*=...")
            # to minimize potential side effects--e.g., in attached messages that might
            # have their own attachments with (correctly) RFC 2231 encoded filenames.
            prepared = Request(**params).prepare()
            form_data = prepared.body  # bytes
            for filename in non_ascii_filenames:  # text
                rfc2231_filename = encode_rfc2231(filename, charset="utf-8")
                form_data = form_data.replace(
                    b'filename*=' + rfc2231_filename.encode("utf-8"),
                    b'filename="' + filename.encode("utf-8") + b'"')
            params["data"] = form_data
            params["headers"]["Content-Type"] = prepared.headers["Content-Type"]  # multipart/form-data; boundary=...
            params["files"] = None  # these are now in the form_data body
        return params

    def serialize_data(self):
        self.populate_recipient_variables()
        return self.data

    # A not-so-brief digression about Mailgun's batch sending, template personalization,
    # and metadata tracking capabilities...
    #
    # Mailgun has two kinds of templates:
    #   * ESP-stored templates (handlebars syntax), referenced by template name in the
    #     send API, with substitution data supplied as "custom data" variables.
    #     Anymail's `template_id` maps to this feature.
    #   * On-the-fly templating (`%recipient.KEY%` syntax), with template variables
    #     appearing directly in the message headers and/or body, and data supplied
    #     as "recipient variables" per-recipient personalizations. Mailgun docs also
    #     sometimes refer to this data as "template variables," but it's distinct from
    #     the substitution data used for stored handelbars templates.
    #
    # Mailgun has two mechanisms for supplying additional data with a message:
    #   * "Custom data" is supplied via `v:KEY` and/or `h:X-Mailgun-Variables` fields.
    #     Custom data is passed to tracking webhooks (as 'user-variables') and is
    #     available for `{{substitutions}}` in ESP-stored handlebars templates.
    #     Normally, the same custom data is applied to every recipient of a message.
    #   * "Recipient variables" are supplied via the `recipient-variables` field, and
    #     provide per-recipient data for batch sending. The recipient specific values
    #     are available as `%recipient.KEY%` virtually anywhere in the message
    #     (including header fields and other parameters).
    #
    # Anymail needs both mechanisms to map its normalized metadata and template merge_data
    # features to Mailgun:
    # (1) Anymail's `metadata` maps directly to Mailgun's custom data, where it can be
    #     accessed from webhooks.
    # (2) Anymail's `merge_metadata` (per-recipient metadata for batch sends) maps
    #     *indirectly* through recipient-variables to Mailgun's custom data. To avoid
    #     conflicts, the recipient-variables mapping prepends 'v:' to merge_metadata keys.
    #     (E.g., Mailgun's custom-data "user" is set to "%recipient.v:user", which picks
    #     up its per-recipient value from Mailgun's `recipient-variables[to_email]["v:user"]`.)
    # (3) Anymail's `merge_data` (per-recipient template substitutions) maps directly to
    #     Mailgun's `recipient-variables`, where it can be referenced in on-the-fly templates.
    # (4) Anymail's `merge_global_data` (global template substitutions) is copied to
    #     Mailgun's `recipient-variables` for every recipient, as the default for missing
    #     `merge_data` keys.
    # (5) Only if a stored template is used, `merge_data` and `merge_global_data` are
    #     *also* mapped *indirectly* through recipient-variables to Mailgun's custom data,
    #     where they can be referenced in handlebars {{substitutions}}.
    #     (E.g., Mailgun's custom-data "name" is set to "%recipient.name%", which picks
    #     up its per-recipient value from Mailgun's `recipient-variables[to_email]["name"]`.)
    #
    # If Anymail's `merge_data`, `template_id` (stored templates) and `metadata` (or
    # `merge_metadata`) are used together, there's a possibility of conflicting keys in
    # Mailgun's custom data. Anymail treats that conflict as an unsupported feature error.

    def populate_recipient_variables(self):
        """Populate Mailgun recipient-variables and custom data from merge data and metadata"""
        # (numbers refer to detailed explanation above)
        # Mailgun parameters to construct:
        recipient_variables = {}
        custom_data = {}

        # (1) metadata --> Mailgun custom_data
        custom_data.update(self.metadata)

        # (2) merge_metadata --> Mailgun custom_data via recipient_variables
        if self.merge_metadata:
            def vkey(key):  # 'v:key'
                return 'v:{}'.format(key)

            merge_metadata_keys = flatset(  # all keys used in any recipient's merge_metadata
                recipient_data.keys() for recipient_data in self.merge_metadata.values())
            custom_data.update({  # custom_data['key'] = '%recipient.v:key%' indirection
                key: '%recipient.{}%'.format(vkey(key))
                for key in merge_metadata_keys})
            base_recipient_data = {  # defaults for each recipient must cover all keys
                vkey(key): self.metadata.get(key, '')
                for key in merge_metadata_keys}
            for email in self.to_emails:
                this_recipient_data = base_recipient_data.copy()
                this_recipient_data.update({
                    vkey(key): value
                    for key, value in self.merge_metadata.get(email, {}).items()})
                recipient_variables.setdefault(email, {}).update(this_recipient_data)

        # (3) and (4) merge_data, merge_global_data --> Mailgun recipient_variables
        if self.merge_data or self.merge_global_data:
            merge_data_keys = flatset(  # all keys used in any recipient's merge_data
                recipient_data.keys() for recipient_data in self.merge_data.values())
            merge_data_keys = merge_data_keys.union(self.merge_global_data.keys())
            base_recipient_data = {  # defaults for each recipient must cover all keys
                key: self.merge_global_data.get(key, '')
                for key in merge_data_keys}
            for email in self.to_emails:
                this_recipient_data = base_recipient_data.copy()
                this_recipient_data.update(self.merge_data.get(email, {}))
                recipient_variables.setdefault(email, {}).update(this_recipient_data)

            # (5) if template, also map Mailgun custom_data to per-recipient_variables
            if self.data.get('template') is not None:
                conflicts = merge_data_keys.intersection(custom_data.keys())
                if conflicts:
                    self.unsupported_feature(
                        "conflicting merge_data and metadata keys (%s) when using template_id"
                        % ', '.join("'%s'" % key for key in conflicts))
                custom_data.update({  # custom_data['key'] = '%recipient.key%' indirection
                    key: '%recipient.{}%'.format(key)
                    for key in merge_data_keys})

        # populate Mailgun params
        self.data.update({'v:%s' % key: value
                          for key, value in custom_data.items()})
        if recipient_variables or self.is_batch():
            self.data['recipient-variables'] = self.serialize_json(recipient_variables)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # {field: [multiple, values]}
        self.files = []  # [(field, multiple), (field, values)]
        self.headers = {}

    def set_from_email_list(self, emails):
        # Mailgun supports multiple From email addresses
        self.data["from"] = [email.address for email in emails]
        if self.sender_domain is None and len(emails) > 0:
            # try to intuit sender_domain from first from_email
            self.sender_domain = emails[0].domain or None

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            self.data[recipient_type] = [email.address for email in emails]
            self.all_recipients += emails  # used for backend.parse_recipient_status
        if recipient_type == 'to':
            self.to_emails = [email.addr_spec for email in emails]  # used for populate_recipient_variables

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if emails:
            reply_to = ", ".join([str(email) for email in emails])
            self.data["h:Reply-To"] = reply_to

    def set_extra_headers(self, headers):
        for key, value in headers.items():
            self.data["h:%s" % key] = value

    def set_text_body(self, body):
        self.data["text"] = body

    def set_html_body(self, body):
        if "html" in self.data:
            # second html body could show up through multiple alternatives, or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["html"] = body

    def add_alternative(self, content, mimetype):
        if mimetype.lower() == "text/x-amp-html":
            if "amp-html" in self.data:
                self.unsupported_feature("multiple html parts")
            self.data["amp-html"] = content
        else:
            super().add_alternative(content, mimetype)

    def add_attachment(self, attachment):
        # http://docs.python-requests.org/en/v2.4.3/user/advanced/#post-multiple-multipart-encoded-files
        if attachment.inline:
            field = "inline"
            name = attachment.cid
            if not name:
                self.unsupported_feature("inline attachments without Content-ID")
        else:
            field = "attachment"
            name = attachment.name
            if not name:
                self.unsupported_feature("attachments without filenames")
        self.files.append(
            (field, (name, attachment.content, attachment.mimetype))
        )

    def set_envelope_sender(self, email):
        # Only the domain is used
        self.sender_domain = email.domain

    def set_metadata(self, metadata):
        self.metadata = metadata  # save for handling merge_metadata later
        for key, value in metadata.items():
            self.data["v:%s" % key] = value

    def set_send_at(self, send_at):
        # Mailgun expects RFC-2822 format dates
        # (BasePayload has converted most date-like values to datetime by now;
        # if the caller passes a string, they'll need to format it themselves.)
        if isinstance(send_at, datetime):
            send_at = rfc2822date(send_at)
        self.data["o:deliverytime"] = send_at

    def set_tags(self, tags):
        self.data["o:tag"] = tags

    def set_track_clicks(self, track_clicks):
        # Mailgun also supports an "htmlonly" option, which Anymail doesn't offer
        self.data["o:tracking-clicks"] = "yes" if track_clicks else "no"

    def set_track_opens(self, track_opens):
        self.data["o:tracking-opens"] = "yes" if track_opens else "no"

    def set_template_id(self, template_id):
        self.data["template"] = template_id

    def set_merge_data(self, merge_data):
        # Processed at serialization time (to allow merging global data)
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        # Processed at serialization time (to allow merging global data)
        self.merge_global_data = merge_global_data

    def set_merge_metadata(self, merge_metadata):
        # Processed at serialization time (to allow combining with merge_data)
        self.merge_metadata = merge_metadata

    def set_esp_extra(self, extra):
        self.data.update(extra)
        # Allow override of sender_domain via esp_extra
        # (but pop it out of params to send to Mailgun)
        self.sender_domain = self.data.pop("sender_domain", self.sender_domain)


def isascii(s):
    """Returns True if str s is entirely ASCII characters.

    (Compare to Python 3.7 `str.isascii()`.)
    """
    try:
        s.encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def flatset(iterables):
    """Return a set of the items in a single-level flattening of iterables

    >>> flatset([1, 2], [2, 3])
    set(1, 2, 3)
    """
    return set(item for iterable in iterables for item in iterable)
