from datetime import datetime
from email.utils import encode_rfc2231
from six.moves.urllib.parse import quote

from requests import Request

from ..exceptions import AnymailRequestsAPIError, AnymailError
from ..message import AnymailRecipientStatus
from ..utils import get_anymail_setting, rfc2822date

from .base_requests import AnymailRequestsBackend, RequestsPayload


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
        super(EmailBackend, self).__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailgunPayload(message, defaults, self)

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
        except (KeyError, TypeError):
            raise AnymailRequestsAPIError("Invalid Mailgun API response format",
                                          email_message=message, payload=payload, response=response,
                                          backend=self)
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

        super(MailgunPayload, self).__init__(message, defaults, backend, auth=auth, *args, **kwargs)

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
        params = super(MailgunPayload, self).get_request_params(api_url)
        non_ascii_filenames = [filename
                               for (field, (filename, content, mimetype)) in params["files"]
                               if filename is not None and not isascii(filename)]
        if non_ascii_filenames:
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
                rfc2231_filename = encode_rfc2231(  # wants a str (text in PY3, bytes in PY2)
                    filename if isinstance(filename, str) else filename.encode("utf-8"),
                    charset="utf-8")
                form_data = form_data.replace(
                    b'filename*=' + rfc2231_filename.encode("utf-8"),
                    b'filename="' + filename.encode("utf-8") + b'"')
            params["data"] = form_data
            params["headers"]["Content-Type"] = prepared.headers["Content-Type"]  # multipart/form-data; boundary=...
            params["files"] = None  # these are now in the form_data body
        return params

    def serialize_data(self):
        if self.is_batch() or self.merge_global_data:
            self.populate_recipient_variables()
        return self.data

    def populate_recipient_variables(self):
        """Populate Mailgun recipient-variables from merge data and metadata"""
        merge_metadata_keys = set()  # all keys used in any recipient's merge_metadata
        for recipient_metadata in self.merge_metadata.values():
            merge_metadata_keys.update(recipient_metadata.keys())
        metadata_vars = {key: "v:%s" % key for key in merge_metadata_keys}  # custom-var for key

        # Set up custom-var substitutions for merge metadata
        # data['v:SomeMergeMetadataKey'] = '%recipient.v:SomeMergeMetadataKey%'
        for var in metadata_vars.values():
            self.data[var] = "%recipient.{var}%".format(var=var)

        # Any (toplevel) metadata that is also in (any) merge_metadata must be be moved
        # into recipient-variables; and all merge_metadata vars must have defaults
        # (else they'll get the '%recipient.v:SomeMergeMetadataKey%' literal string).
        base_metadata = {metadata_vars[key]: self.metadata.get(key, '')
                         for key in merge_metadata_keys}

        recipient_vars = {}
        for addr in self.to_emails:
            # For each recipient, Mailgun recipient-variables[addr] is merger of:
            # 1. metadata, for any keys that appear in merge_metadata
            recipient_data = base_metadata.copy()

            # 2. merge_metadata[addr], with keys prefixed with 'v:'
            if addr in self.merge_metadata:
                recipient_data.update({
                    metadata_vars[key]: value for key, value in self.merge_metadata[addr].items()
                })

            # 3. merge_global_data (because Mailgun doesn't support global variables)
            recipient_data.update(self.merge_global_data)

            # 4. merge_data[addr]
            if addr in self.merge_data:
                recipient_data.update(self.merge_data[addr])

            if recipient_data:
                recipient_vars[addr] = recipient_data

        self.data['recipient-variables'] = self.serialize_json(recipient_vars)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}   # {field: [multiple, values]}
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
