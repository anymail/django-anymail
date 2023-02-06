from email.charset import QP, Charset
from email.mime.text import MIMEText

from .._version import __version__
from ..exceptions import AnymailAPIError, AnymailImproperlyInstalled
from ..message import AnymailRecipientStatus
from ..utils import UNSET, get_anymail_setting
from .base import AnymailBaseBackend, BasePayload

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import BotoCoreError, ClientError, ConnectionError
except ImportError as err:
    raise AnymailImproperlyInstalled(
        missing_package="boto3", backend="amazon_ses"
    ) from err


# boto3 has several root exception classes; this is meant to cover all of them
BOTO_BASE_ERRORS = (BotoCoreError, ClientError, ConnectionError)


class EmailBackend(AnymailBaseBackend):
    """
    Amazon SES Email Backend (using boto3)
    """

    esp_name = "Amazon SES"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        super().__init__(**kwargs)
        # AMAZON_SES_CLIENT_PARAMS is optional
        # (boto3 can find credentials several other ways)
        self.session_params, self.client_params = _get_anymail_boto3_params(
            kwargs=kwargs
        )
        self.configuration_set_name = get_anymail_setting(
            "configuration_set_name",
            esp_name=self.esp_name,
            kwargs=kwargs,
            allow_bare=False,
            default=None,
        )
        self.message_tag_name = get_anymail_setting(
            "message_tag_name",
            esp_name=self.esp_name,
            kwargs=kwargs,
            allow_bare=False,
            default=None,
        )
        self.client = None

    def open(self):
        if self.client:
            return False  # already exists
        try:
            self.client = boto3.session.Session(**self.session_params).client(
                "ses", **self.client_params
            )
        except BOTO_BASE_ERRORS:
            if not self.fail_silently:
                raise
        else:
            return True  # created client

    def close(self):
        if self.client is None:
            return
        # self.client.close()  # boto3 doesn't support (or require) client shutdown
        self.client = None

    def build_message_payload(self, message, defaults):
        # The SES SendRawEmail and SendBulkTemplatedEmail calls have
        # very different signatures, so use a custom payload for each
        if getattr(message, "template_id", UNSET) is not UNSET:
            return AmazonSESSendBulkTemplatedEmailPayload(message, defaults, self)
        else:
            return AmazonSESSendRawEmailPayload(message, defaults, self)

    def post_to_esp(self, payload, message):
        try:
            response = payload.call_send_api(self.client)
        except BOTO_BASE_ERRORS as err:
            # ClientError has a response attr with parsed json error response
            # (other errors don't)
            raise AnymailAPIError(
                str(err),
                backend=self,
                email_message=message,
                payload=payload,
                response=getattr(err, "response", None),
            ) from err
        return response

    def parse_recipient_status(self, response, payload, message):
        return payload.parse_recipient_status(response)


class AmazonSESBasePayload(BasePayload):
    def init_payload(self):
        self.params = {}
        if self.backend.configuration_set_name is not None:
            self.params["ConfigurationSetName"] = self.backend.configuration_set_name

    def call_send_api(self, ses_client):
        raise NotImplementedError()

    def parse_recipient_status(self, response):
        # response is the parsed (dict) JSON returned from the API call
        raise NotImplementedError()

    def set_esp_extra(self, extra):
        # e.g., ConfigurationSetName, FromArn, SourceArn, ReturnPathArn
        self.params.update(extra)


class AmazonSESSendRawEmailPayload(AmazonSESBasePayload):
    def init_payload(self):
        super().init_payload()
        self.all_recipients = []
        self.mime_message = self.message.message()

        # Work around an Amazon SES bug where, if all of:
        #   - the message body (text or html) contains non-ASCII characters
        #   - the body is sent with `Content-Transfer-Encoding: 8bit`
        #     (which is Django email's default for most non-ASCII bodies)
        #   - you are using an SES ConfigurationSet with open or click tracking enabled
        # then SES replaces the non-ASCII characters with question marks as it rewrites
        # the message to add tracking. Forcing `CTE: quoted-printable` avoids the
        # problem. (https://forums.aws.amazon.com/thread.jspa?threadID=287048)
        for part in self.mime_message.walk():
            if (
                part.get_content_maintype() == "text"
                and part["Content-Transfer-Encoding"] == "8bit"
            ):
                content = part.get_payload()
                del part["Content-Transfer-Encoding"]
                qp_charset = Charset(part.get_content_charset("us-ascii"))
                qp_charset.body_encoding = QP
                # (can't use part.set_payload, because SafeMIMEText can undo
                # this workaround)
                MIMEText.set_payload(part, content, charset=qp_charset)

    def call_send_api(self, ses_client):
        # Set Destinations to make sure we pick up all recipients (including bcc).
        # Any non-ASCII characters in recipient domains must be encoded with Punycode.
        # (Amazon SES doesn't support non-ASCII recipient usernames.)
        self.params["Destinations"] = [email.address for email in self.all_recipients]
        self.params["RawMessage"] = {"Data": self.mime_message.as_bytes()}
        return ses_client.send_raw_email(**self.params)

    def parse_recipient_status(self, response):
        try:
            message_id = response["MessageId"]
        except (KeyError, TypeError) as err:
            raise AnymailAPIError(
                "%s parsing Amazon SES send result %r" % (str(err), response),
                backend=self.backend,
                email_message=self.message,
                payload=self,
            ) from None

        recipient_status = AnymailRecipientStatus(
            message_id=message_id, status="queued"
        )
        return {
            recipient.addr_spec: recipient_status for recipient in self.all_recipients
        }

    # Standard EmailMessage attrs...
    # These all get rolled into the RFC-5322 raw mime directly via
    # EmailMessage.message()

    def _no_send_defaults(self, attr):
        # Anymail global send defaults don't work for standard attrs, because the
        # merged/computed value isn't forced back into the EmailMessage.
        if attr in self.defaults:
            self.unsupported_feature(
                "Anymail send defaults for '%s' with Amazon SES" % attr
            )

    def set_from_email_list(self, emails):
        # Although Amazon SES will send messages with any From header, it can only parse
        # Source if the From header is a single email. Explicit Source avoids an
        # "Illegal address" error:
        if len(emails) > 1:
            self.params["Source"] = emails[0].addr_spec
        # (else SES will look at the (single) address in the From header)

    def set_recipients(self, recipient_type, emails):
        self.all_recipients += emails
        # included in mime_message
        assert recipient_type in ("to", "cc", "bcc")
        self._no_send_defaults(recipient_type)

    def set_subject(self, subject):
        # included in mime_message
        self._no_send_defaults("subject")

    def set_reply_to(self, emails):
        # included in mime_message
        self._no_send_defaults("reply_to")

    def set_extra_headers(self, headers):
        # included in mime_message
        self._no_send_defaults("extra_headers")

    def set_text_body(self, body):
        # included in mime_message
        self._no_send_defaults("body")

    def set_html_body(self, body):
        # included in mime_message
        self._no_send_defaults("body")

    def set_alternatives(self, alternatives):
        # included in mime_message
        self._no_send_defaults("alternatives")

    def set_attachments(self, attachments):
        # included in mime_message
        self._no_send_defaults("attachments")

    # Anymail-specific payload construction
    def set_envelope_sender(self, email):
        self.params["Source"] = email.addr_spec

    def set_spoofed_to_header(self, header_to):
        # django.core.mail.EmailMessage.message() has already set
        #   self.mime_message["To"] = header_to
        # and performed any necessary header sanitization.
        #
        # The actual "to" is already in self.all_recipients,
        # which is used as the SendRawEmail Destinations later.
        #
        # So, nothing to do here, except prevent the default
        # "unsupported feature" error.
        pass

    def set_metadata(self, metadata):
        # Amazon SES has two mechanisms for adding custom data to a message:
        # * Custom message headers are available to webhooks (SNS notifications),
        #   but not in CloudWatch metrics/dashboards or Kinesis Firehose streams.
        #   Custom headers can be sent only with SendRawEmail.
        # * "Message Tags" are available to CloudWatch and Firehose, and to SNS
        #   notifications for SES *events* but not SES *notifications*. (Got that?)
        #   Message Tags also allow *very* limited characters in both name and value.
        #   Message Tags can be sent with any SES send call.
        # (See "How do message tags work?" in
        # https://aws.amazon.com/blogs/ses/introducing-sending-metrics/
        # and https://forums.aws.amazon.com/thread.jspa?messageID=782922.)
        # To support reliable retrieval in webhooks, just use custom headers for
        # metadata.
        self.mime_message["X-Metadata"] = self.serialize_json(metadata)

    def set_tags(self, tags):
        # See note about Amazon SES Message Tags and custom headers in set_metadata
        # above. To support reliable retrieval in webhooks, use custom headers for tags.
        # (There are no restrictions on number or content for custom header tags.)
        for tag in tags:
            # creates multiple X-Tag headers, one per tag:
            self.mime_message.add_header("X-Tag", tag)

        # Also *optionally* pass a single Message Tag if the AMAZON_SES_MESSAGE_TAG_NAME
        # Anymail setting is set (default no). The AWS API restricts tag content in this
        # case. (This is useful for dashboard segmentation; use esp_extra["Tags"] for
        # anything more complex.)
        if tags and self.backend.message_tag_name is not None:
            if len(tags) > 1:
                self.unsupported_feature(
                    "multiple tags with the AMAZON_SES_MESSAGE_TAG_NAME setting"
                )
            self.params.setdefault("Tags", []).append(
                {"Name": self.backend.message_tag_name, "Value": tags[0]}
            )

    def set_template_id(self, template_id):
        raise NotImplementedError(
            "AmazonSESSendRawEmailPayload should not have been used with template_id"
        )

    def set_merge_data(self, merge_data):
        self.unsupported_feature("merge_data without template_id")

    def set_merge_global_data(self, merge_global_data):
        self.unsupported_feature("global_merge_data without template_id")


class AmazonSESSendBulkTemplatedEmailPayload(AmazonSESBasePayload):
    def init_payload(self):
        super().init_payload()
        # late-bind recipients and merge_data in call_send_api
        self.recipients = {"to": [], "cc": [], "bcc": []}
        self.merge_data = {}

    def call_send_api(self, ses_client):
        # include any 'cc' or 'bcc' in every destination
        cc_and_bcc_addresses = {}
        if self.recipients["cc"]:
            cc_and_bcc_addresses["CcAddresses"] = [
                cc.address for cc in self.recipients["cc"]
            ]
        if self.recipients["bcc"]:
            cc_and_bcc_addresses["BccAddresses"] = [
                bcc.address for bcc in self.recipients["bcc"]
            ]

        # set up destination and data for each 'to'
        self.params["Destinations"] = [
            {
                "Destination": dict(ToAddresses=[to.address], **cc_and_bcc_addresses),
                "ReplacementTemplateData": self.serialize_json(
                    self.merge_data.get(to.addr_spec, {})
                ),
            }
            for to in self.recipients["to"]
        ]

        return ses_client.send_bulk_templated_email(**self.params)

    def parse_recipient_status(self, response):
        try:
            # response["Status"] should be a list in Destinations (to) order
            anymail_statuses = [
                AnymailRecipientStatus(
                    message_id=status.get("MessageId", None),
                    status="queued" if status.get("Status") == "Success" else "failed",
                )
                for status in response["Status"]
            ]
        except (KeyError, TypeError) as err:
            raise AnymailAPIError(
                "%s parsing Amazon SES send result %r" % (str(err), response),
                backend=self.backend,
                email_message=self.message,
                payload=self,
            ) from None

        to_addrs = [to.addr_spec for to in self.recipients["to"]]
        if len(anymail_statuses) != len(to_addrs):
            raise AnymailAPIError(
                "Sent to %d destinations, but only %d statuses in Amazon SES"
                " send result %r" % (len(to_addrs), len(anymail_statuses), response),
                backend=self.backend,
                email_message=self.message,
                payload=self,
            )

        return dict(zip(to_addrs, anymail_statuses))

    def set_from_email(self, email):
        # this will RFC2047-encode display_name if needed:
        self.params["Source"] = email.address

    def set_recipients(self, recipient_type, emails):
        # late-bound in call_send_api
        assert recipient_type in ("to", "cc", "bcc")
        self.recipients[recipient_type] = emails

    def set_subject(self, subject):
        # (subject can only come from template; you can use substitution vars in that)
        if subject:
            self.unsupported_feature("overriding template subject")

    def set_reply_to(self, emails):
        if emails:
            self.params["ReplyToAddresses"] = [email.address for email in emails]

    def set_extra_headers(self, headers):
        self.unsupported_feature("extra_headers with template")

    def set_text_body(self, body):
        if body:
            self.unsupported_feature("overriding template body content")

    def set_html_body(self, body):
        if body:
            self.unsupported_feature("overriding template body content")

    def set_attachments(self, attachments):
        if attachments:
            self.unsupported_feature("attachments with template")

    # Anymail-specific payload construction
    def set_envelope_sender(self, email):
        self.params["ReturnPath"] = email.addr_spec

    def set_metadata(self, metadata):
        # no custom headers with SendBulkTemplatedEmail
        self.unsupported_feature("metadata with template")

    def set_tags(self, tags):
        # no custom headers with SendBulkTemplatedEmail, but support
        # AMAZON_SES_MESSAGE_TAG_NAME if used (see tags/metadata in
        # AmazonSESSendRawEmailPayload for more info)
        if tags:
            if self.backend.message_tag_name is not None:
                if len(tags) > 1:
                    self.unsupported_feature(
                        "multiple tags with the AMAZON_SES_MESSAGE_TAG_NAME setting"
                    )
                self.params["DefaultTags"] = [
                    {"Name": self.backend.message_tag_name, "Value": tags[0]}
                ]
            else:
                self.unsupported_feature(
                    "tags with template (unless using the"
                    " AMAZON_SES_MESSAGE_TAG_NAME setting)"
                )

    def set_template_id(self, template_id):
        self.params["Template"] = template_id

    def set_merge_data(self, merge_data):
        # late-bound in call_send_api
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        self.params["DefaultTemplateData"] = self.serialize_json(merge_global_data)


def _get_anymail_boto3_params(esp_name=EmailBackend.esp_name, kwargs=None):
    """Returns 2 dicts of params for boto3.session.Session() and .client()

    Incorporates ANYMAIL["AMAZON_SES_SESSION_PARAMS"] and
    ANYMAIL["AMAZON_SES_CLIENT_PARAMS"] settings.

    Converts config dict to botocore.client.Config if needed

    May remove keys from kwargs, but won't modify original settings
    """
    # (shared with ..webhooks.amazon_ses)
    session_params = get_anymail_setting(
        "session_params", esp_name=esp_name, kwargs=kwargs, default={}
    )
    client_params = get_anymail_setting(
        "client_params", esp_name=esp_name, kwargs=kwargs, default={}
    )

    # Add Anymail user-agent, and convert config dict to botocore.client.Config
    client_params = client_params.copy()  # don't modify source
    config = Config(
        user_agent_extra="django-anymail/{version}-{esp}".format(
            esp=esp_name.lower().replace(" ", "-"), version=__version__
        )
    )
    if "config" in client_params:
        # convert config dict to botocore.client.Config if needed
        client_params_config = client_params["config"]
        if not isinstance(client_params_config, Config):
            client_params_config = Config(**client_params_config)
        config = config.merge(client_params_config)
    client_params["config"] = config

    return session_params, client_params
