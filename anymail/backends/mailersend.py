import mimetypes

from ..exceptions import AnymailRequestsAPIError, AnymailUnsupportedFeature
from ..message import AnymailRecipientStatus
from ..utils import CaseInsensitiveCasePreservingDict, get_anymail_setting, update_deep
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    MailerSend Email Backend
    """

    esp_name = "MailerSend"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_token = get_anymail_setting(
            "api_token", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.mailersend.com/v1/",
        )
        if not api_url.endswith("/"):
            api_url += "/"

        #: Can set to "use-bulk-email" or "expose-to-list" or default None
        self.batch_send_mode = get_anymail_setting(
            "batch_send_mode", default=None, esp_name=esp_name, kwargs=kwargs
        )
        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailerSendPayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        # The "email" API endpoint responds with an empty text/html body
        # if no warnings, otherwise json with suppression info.
        # The "bulk-email" API endpoint always returns json.
        if response.headers["Content-Type"] == "application/json":
            parsed_response = self.deserialize_json_response(response, payload, message)
        else:
            parsed_response = {}

        try:
            # "email" API endpoint success or SOME_SUPPRESSED
            message_id = response.headers["X-Message-Id"]
            default_status = "queued"
        except KeyError:
            try:
                # "bulk-email" API endpoint
                bulk_id = parsed_response["bulk_email_id"]
                # Add "bulk:" prefix to distinguish from actual message_id.
                message_id = f"bulk:{bulk_id}"
                # Status is determined later; must query API to find out
                default_status = "unknown"
            except KeyError:
                # "email" API endpoint with ALL_SUPPRESSED
                message_id = None
                default_status = "failed"

        # Don't swallow errors (which should have been handled with a non-2xx
        # status, earlier) or any warnings that we won't consume below.
        errors = parsed_response.get("errors", [])
        warnings = parsed_response.get("warnings", [])
        if errors or any(
            warning["type"] not in ("ALL_SUPPRESSED", "SOME_SUPPRESSED")
            for warning in warnings
        ):
            raise AnymailRequestsAPIError(
                "Unexpected MailerSend API response errors/warnings",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            )

        # Collect a list of all problem recipients from any suppression warnings.
        # (warnings[].recipients[].reason[] will contain some combination of
        # "hard_bounced", "spam_complaint", "unsubscribed", and/or
        # "blocklisted", all of which map to Anymail's "rejected" status.)
        try:
            # warning["type"] is guaranteed to be {ALL,SOME}_SUPPRESSED at this point.
            rejected_emails = [
                recipient["email"]
                for warning in warnings
                for recipient in warning["recipients"]
            ]
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                f"Unexpected MailerSend API response format: {err!s}",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from None

        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recipient.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status=default_status
                )
                for recipient in payload.all_recipients
            }
        )
        for rejected_email in rejected_emails:
            recipient_status[rejected_email] = AnymailRecipientStatus(
                message_id=None, status="rejected"
            )

        return dict(recipient_status)


class MailerSendPayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Token may be changed in set_esp_extra below:
            "Authorization": f"Bearer {backend.api_token}",
        }
        self.all_recipients = []  # needed for parse_recipient_status
        self.merge_data = {}  # late bound
        self.merge_global_data = None  # late bound
        self.batch_send_mode = backend.batch_send_mode  # can override in esp_extra
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        if self.is_batch():
            # MailerSend's "email" endpoint supports per-recipient customizations
            # (merge_data) for batch sending, but exposes the complete "To" list
            # to all recipients. This conflicts with Anymail's batch send model, which
            # expects each recipient can only see their own "To" email.
            #
            # MailerSend's "bulk-email" endpoint can send separate messages to each
            # "To" email, but doesn't return a message_id. (It returns a batch_email_id
            # that can later resolve to message_ids by polling a status API.)
            #
            # Since either of these would cause unexpected behavior, require the user
            # to opt into one via batch_send_mode.
            if self.batch_send_mode == "use-bulk-email":
                return "bulk-email"
            elif self.batch_send_mode == "expose-to-list":
                return "email"
            elif len(self.data["to"]) <= 1:
                # With only one "to", exposing the recipient list is moot.
                # (This covers the common case of single-recipient template merge.)
                return "email"
            else:
                # Unconditionally raise, even if IGNORE_UNSUPPORTED_FEATURES enabled.
                # We can't guess which API to use for this send.
                raise AnymailUnsupportedFeature(
                    f"{self.esp_name} requires MAILERSEND_BATCH_SEND_MODE set to either"
                    f" 'use-bulk-email' or 'expose-to-list' for using batch send"
                    f" (merge_data) with multiple recipients. See the Anymail docs."
                )
        else:
            return "email"

    def serialize_data(self):
        api_endpoint = self.get_api_endpoint()
        needs_personalization = self.merge_data or self.merge_global_data
        if api_endpoint == "email":
            if needs_personalization:
                self.data["personalization"] = [
                    self.personalization_for_email(to["email"])
                    for to in self.data["to"]
                ]
            data = self.data
        elif api_endpoint == "bulk-email":
            # Burst the payload into individual bulk-email recipients:
            data = []
            for to in self.data["to"]:
                recipient_data = self.data.copy()
                recipient_data["to"] = [to]
                if needs_personalization:
                    recipient_data["personalization"] = [
                        self.personalization_for_email(to["email"])
                    ]
                data.append(recipient_data)
        else:
            raise AssertionError(
                f"MailerSendPayload.serialize_data missing"
                f" case for api_endpoint {api_endpoint!r}"
            )
        return self.serialize_json(data)

    def personalization_for_email(self, email):
        """
        Return a MailerSend personalization object for email address.

        Composes merge_global_data and merge_data[email].
        """
        if email in self.merge_data:
            if self.merge_global_data:
                recipient_data = self.merge_global_data.copy()
                recipient_data.update(self.merge_data[email])
            else:
                recipient_data = self.merge_data[email]
        elif self.merge_global_data:
            recipient_data = self.merge_global_data
        else:
            recipient_data = {}
        return {"email": email, "data": recipient_data}

    #
    # Payload construction
    #

    def make_mailersend_email(self, email):
        """Return MailerSend email/name object for an EmailAddress"""
        obj = {"email": email.addr_spec}
        if email.display_name:
            obj["name"] = email.display_name
        return obj

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email(self, email):
        self.data["from"] = self.make_mailersend_email(email)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            self.data[recipient_type] = [
                self.make_mailersend_email(email) for email in emails
            ]
            self.all_recipients += emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to emails")
        elif emails:
            self.data["reply_to"] = self.make_mailersend_email(emails[0])

    def set_extra_headers(self, headers):
        # MailerSend doesn't support arbitrary email headers, but has
        # individual API params for In-Reply-To and Precedence: bulk.
        # (headers is a CaseInsensitiveDict, and is a copy so safe to modify.)
        in_reply_to = headers.pop("In-Reply-To", None)
        if in_reply_to is not None:
            self.data["in_reply_to"] = in_reply_to

        precedence = headers.pop("Precedence", None)
        if precedence is not None:
            # Overrides MailerSend domain-level setting
            is_bulk = precedence.lower() in ("bulk", "junk", "list")
            self.data["precedence_bulk"] = is_bulk

        if headers:
            self.unsupported_feature("most extra_headers (see docs)")

    def set_text_body(self, body):
        self.data["text"] = body

    def set_html_body(self, body):
        if "html" in self.data:
            # second html body could show up through multiple alternatives,
            # or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["html"] = body

    def add_attachment(self, attachment):
        # Add a MailerSend attachments[] object for attachment:
        attachment_object = {
            "filename": attachment.name,
            "content": attachment.b64content,
            "disposition": "attachment",
        }
        if not attachment_object["filename"]:
            # MailerSend requires filename, and determines mimetype from it
            # (even for inline attachments). For unnamed attachments, try
            # to generate a generic filename with the correct extension:
            ext = mimetypes.guess_extension(attachment.mimetype, strict=False)
            if ext is not None:
                attachment_object["filename"] = f"attachment{ext}"
        if attachment.inline:
            attachment_object["disposition"] = "inline"
            attachment_object["id"] = attachment.cid
        self.data.setdefault("attachments", []).append(attachment_object)

    # MailerSend doesn't have metadata
    # def set_metadata(self, metadata):

    def set_send_at(self, send_at):
        # Backend has converted pretty much everything to
        # a datetime by here; MailerSend expects unix timestamp
        self.data["send_at"] = int(send_at.timestamp())  # strip microseconds

    def set_tags(self, tags):
        if tags:
            self.data["tags"] = tags

    def set_track_clicks(self, track_clicks):
        self.data.setdefault("settings", {})["track_clicks"] = track_clicks

    def set_track_opens(self, track_opens):
        self.data.setdefault("settings", {})["track_opens"] = track_opens

    def set_template_id(self, template_id):
        self.data["template_id"] = template_id

    def set_merge_data(self, merge_data):
        # late bound in serialize_data
        self.merge_data = merge_data

    def set_merge_global_data(self, merge_global_data):
        # late bound in serialize_data
        self.merge_global_data = merge_global_data

    # MailerSend doesn't have metadata
    # def set_merge_metadata(self, merge_metadata):

    def set_esp_extra(self, extra):
        # Deep merge to allow (e.g.,) {"settings": {"track_content": True}}:
        update_deep(self.data, extra)

        # Allow overriding api_token on individual message:
        try:
            api_token = self.data.pop("api_token")
        except KeyError:
            pass
        else:
            self.headers["Authorization"] = f"Bearer {api_token}"

        # Allow overriding batch_send_mode on individual message:
        try:
            self.batch_send_mode = self.data.pop("batch_send_mode")
        except KeyError:
            pass
