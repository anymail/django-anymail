import email.charset
import email.encoders
import email.policy

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
        missing_package="boto3", backend="amazon_sesv2"
    ) from err


# boto3 has several root exception classes; this is meant to cover all of them
BOTO_BASE_ERRORS = (BotoCoreError, ClientError, ConnectionError)


class EmailBackend(AnymailBaseBackend):
    """
    Amazon SES v2 Email Backend (using boto3)
    """

    # Deliberately no "v2" in the esp_name: we don't want to force client changes
    # when the v1 backend is retired and this one replace it as just "amazon_ses".
    esp_name = "Amazon SES"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        super().__init__(**kwargs)
        # AMAZON_SES_CLIENT_PARAMS is optional
        # (boto3 can find credentials several other ways)
        self.session_params, self.client_params = _get_anymail_boto3_params(
            esp_name=self.esp_name, kwargs=kwargs
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
                "sesv2", **self.client_params
            )
        except BOTO_BASE_ERRORS:
            if not self.fail_silently:
                raise
        else:
            return True  # created client

    def close(self):
        if self.client is None:
            return
        self.client.close()
        self.client = None

    def build_message_payload(self, message, defaults):
        if getattr(message, "template_id", UNSET) is not UNSET:
            # For simplicity, use SESv2 SendBulkEmail for all templated messages
            # (even though SESv2 SendEmail has a template option).
            return AmazonSESV2SendBulkEmailPayload(message, defaults, self)
        else:
            return AmazonSESV2SendEmailPayload(message, defaults, self)

    def post_to_esp(self, payload, message):
        payload.finalize_payload()
        try:
            client_send_api = getattr(self.client, payload.api_name)
        except AttributeError:
            raise NotImplementedError(
                f"boto3 sesv2 client does not have method {payload.api_name!r}."
                f" Check {payload.__class__.__name__}.api_name."
            ) from None
        try:
            response = client_send_api(**payload.params)
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
    #: Name of the boto3 SES/SESv2 client method to call
    api_name = "SUBCLASS_MUST_OVERRIDE"

    def init_payload(self):
        self.params = {}
        if self.backend.configuration_set_name is not None:
            self.params["ConfigurationSetName"] = self.backend.configuration_set_name

    def finalize_payload(self):
        pass

    def parse_recipient_status(self, response):
        # response is the parsed (dict) JSON returned from the API call
        raise NotImplementedError()

    def set_esp_extra(self, extra):
        # e.g., ConfigurationSetName, FromEmailAddressIdentityArn,
        # FeedbackForwardingEmailAddress, ListManagementOptions
        self.params.update(extra)


class AmazonSESV2SendEmailPayload(AmazonSESBasePayload):
    api_name = "send_email"

    def init_payload(self):
        super().init_payload()
        self.all_recipients = []  # for parse_recipient_status
        self.mime_message = self.message.message()

    def finalize_payload(self):
        # (The boto3 SES client handles base64 encoding raw_message.)
        raw_message = self.generate_raw_message()
        self.params["Content"] = {"Raw": {"Data": raw_message}}

    def generate_raw_message(self):
        """
        Serialize self.mime_message as an RFC-5322/-2045 MIME message,
        encoded as 7bit-clean, us-ascii byte data.
        """
        # Amazon SES does not support `Content-Transfer-Encoding: 8bit`. And using 8bit
        # with SES open or click tracking results in mis-encoded characters. To avoid
        # this, convert any 8bit parts to 7bit quoted printable or base64. (We own
        # self.mime_message, so destructively modifying it should be OK.)
        # (You might think cte_type="7bit" in the email.policy below would cover this,
        # but it seems that cte_type is only examined as the MIME parts are constructed,
        # not when an email.generator serializes them.)
        for part in self.mime_message.walk():
            if part["Content-Transfer-Encoding"] == "8bit":
                del part["Content-Transfer-Encoding"]
                if part.get_content_maintype() == "text":
                    # (Avoid base64 for text parts, which can trigger spam filters)
                    email.encoders.encode_quopri(part)
                else:
                    email.encoders.encode_base64(part)

        self.mime_message.policy = email.policy.default.clone(cte_type="7bit")
        return self.mime_message.as_bytes()

    def parse_recipient_status(self, response):
        try:
            message_id = response["MessageId"]
        except (KeyError, TypeError) as err:
            raise AnymailAPIError(
                f"{err!s} parsing Amazon SES send result {response!r}",
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
                f"Anymail send defaults for '{attr}' with Amazon SES"
            )

    def set_from_email(self, email):
        # If params["FromEmailAddress"] is not provided, SES will parse it from the raw
        # mime_message headers. (And setting it replaces any From header. Note that
        # v2 SendEmail doesn't have an equivalent to v1 SendRawEmail's Sender param.)
        self._no_send_defaults("from_email")

    def set_recipients(self, recipient_type, emails):
        # Although Amazon SES can parse the 'to' and 'cc' recipients from the raw
        # mime_message headers, providing them in the Destination param makes it
        # explicit (and is required for 'bcc' and for spoofed 'to').
        self.all_recipients += emails  # save for parse_recipient_status
        self._no_send_defaults(recipient_type)

        if emails:
            # params["Destination"] = {"ToAddresses": [...], "CcAddresses": etc.}
            # (Unlike most SendEmail params, these _don't_ replace the corresponding
            # raw mime_message headers.)
            assert recipient_type in ("to", "cc", "bcc")
            destination_key = f"{recipient_type.capitalize()}Addresses"
            self.params.setdefault("Destination", {})[destination_key] = [
                email.address for email in emails
            ]

    def set_subject(self, subject):
        # included in mime_message
        self._no_send_defaults("subject")

    def set_reply_to(self, emails):
        # included in mime_message
        # (and setting params["ReplyToAddresses"] replaces any Reply-To header)
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
        # Amazon SES will generate a unique mailfrom, and then forward any delivery
        # problem reports that address receives to the address specified here:
        self.params["FeedbackForwardingEmailAddress"] = email.addr_spec

    def set_spoofed_to_header(self, header_to):
        # django.core.mail.EmailMessage.message() has already set
        #   self.mime_message["To"] = header_to
        # and performed any necessary header sanitization.
        #
        # The actual "to" is already in params["Destination"]["ToAddresses"].
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
            self.params.setdefault("EmailTags", []).append(
                {"Name": self.backend.message_tag_name, "Value": tags[0]}
            )

    def set_template_id(self, template_id):
        raise NotImplementedError(
            f"{self.__class__.__name__} should not have been used with template_id"
        )

    def set_merge_data(self, merge_data):
        self.unsupported_feature("merge_data without template_id")

    def set_merge_global_data(self, merge_global_data):
        self.unsupported_feature("global_merge_data without template_id")


class AmazonSESV2SendBulkEmailPayload(AmazonSESBasePayload):
    api_name = "send_bulk_email"

    def init_payload(self):
        super().init_payload()
        # late-bind recipients and merge_data in finalize_payload
        self.recipients = {"to": [], "cc": [], "bcc": []}
        self.merge_data = {}

    def finalize_payload(self):
        # Build BulkEmailEntries from recipients and merge_data.

        # Any cc and bcc recipients should be included in every entry:
        cc_and_bcc_addresses = {}
        if self.recipients["cc"]:
            cc_and_bcc_addresses["CcAddresses"] = [
                cc.address for cc in self.recipients["cc"]
            ]
        if self.recipients["bcc"]:
            cc_and_bcc_addresses["BccAddresses"] = [
                bcc.address for bcc in self.recipients["bcc"]
            ]

        # Construct an entry with merge data for each "to" recipient:
        self.params["BulkEmailEntries"] = [
            {
                "Destination": dict(ToAddresses=[to.address], **cc_and_bcc_addresses),
                "ReplacementEmailContent": {
                    "ReplacementTemplate": {
                        "ReplacementTemplateData": self.serialize_json(
                            self.merge_data.get(to.addr_spec, {})
                        ),
                    }
                },
            }
            for to in self.recipients["to"]
        ]

    def parse_recipient_status(self, response):
        try:
            results = response["BulkEmailEntryResults"]
            ses_status_set = set(result["Status"] for result in results)
            anymail_statuses = [
                AnymailRecipientStatus(
                    message_id=result.get("MessageId", None),
                    status="queued" if result["Status"] == "SUCCESS" else "failed",
                )
                for result in results
            ]
        except (KeyError, TypeError) as err:
            raise AnymailAPIError(
                f"{err!s} parsing Amazon SES send result {response!r}",
                backend=self.backend,
                email_message=self.message,
                payload=self,
            ) from None

        # If all BulkEmailEntryResults[].Status are the same non-success status,
        # raise an APIError to expose the error message/reason (matching behavior
        # of non-template SendEmail call).
        if len(ses_status_set) == 1 and ses_status_set != {"SUCCESS"}:
            raise AnymailAPIError(
                # use Error text if available, else the Status enum, from first result
                results[0].get("Error", results[0]["Status"]),
                backend=self.backend,
                email_message=self.message,
                payload=self,
                response=response,
            )

        # Otherwise, return per-recipient status (just "queued" or "failed") for
        # all-success, mixed success/error, or all-error mixed-reason cases.
        # The BulkEmailEntryResults are in the same order as the Destination param
        # (which is in the same order as recipients["to"]).
        to_addrs = [to.addr_spec for to in self.recipients["to"]]
        if len(anymail_statuses) != len(to_addrs):
            raise AnymailAPIError(
                f"Sent to {len(to_addrs)} destinations,"
                f" but only {len(anymail_statuses)} statuses"
                f" in Amazon SES send result {response!r}",
                backend=self.backend,
                email_message=self.message,
                payload=self,
            )
        return dict(zip(to_addrs, anymail_statuses))

    def set_from_email(self, email):
        # this will RFC2047-encode display_name if needed:
        self.params["FromEmailAddress"] = email.address

    def set_recipients(self, recipient_type, emails):
        # late-bound in finalize_payload
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
        # Amazon SES will generate a unique mailfrom, and then forward any delivery
        # problem reports that address receives to the address specified here:
        self.params["FeedbackForwardingEmailAddress"] = email.addr_spec

    def set_metadata(self, metadata):
        # no custom headers with SendBulkEmail
        self.unsupported_feature("metadata with template")

    def set_tags(self, tags):
        # no custom headers with SendBulkEmail, but support
        # AMAZON_SES_MESSAGE_TAG_NAME if used (see tags/metadata in
        # AmazonSESV2SendEmailPayload for more info)
        if tags:
            if self.backend.message_tag_name is not None:
                if len(tags) > 1:
                    self.unsupported_feature(
                        "multiple tags with the AMAZON_SES_MESSAGE_TAG_NAME setting"
                    )
                self.params["DefaultEmailTags"] = [
                    {"Name": self.backend.message_tag_name, "Value": tags[0]}
                ]
            else:
                self.unsupported_feature(
                    "tags with template (unless using the"
                    " AMAZON_SES_MESSAGE_TAG_NAME setting)"
                )

    def set_template_id(self, template_id):
        # DefaultContent.Template.TemplateName
        self.params.setdefault("DefaultContent", {}).setdefault("Template", {})[
            "TemplateName"
        ] = template_id

    def set_merge_data(self, merge_data):
        # late-bound in finalize_payload
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        # DefaultContent.Template.TemplateData
        self.params.setdefault("DefaultContent", {}).setdefault("Template", {})[
            "TemplateData"
        ] = self.serialize_json(merge_global_data)


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
