import mimetypes

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    BASIC_NUMERIC_TYPES,
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
)
from .base_requests import AnymailRequestsBackend, RequestsPayload


class EmailBackend(AnymailRequestsBackend):
    """
    MailKite (mailkite.dev) API Email Backend

    MailKite is an inbound-first email platform: it sends transactional mail via
    ``POST /v1/send`` (a single-recipient or multi-recipient JSON API) and *receives*
    mail as a signed webhook. This backend implements the send side. (MailKite's
    inbound webhooks deliver received mail to your own endpoint and are not wired
    through Anymail's inbound signals -- see the MailKite docs page.)
    """

    esp_name = "MailKite"

    def __init__(self, **kwargs):
        """Init options from Django settings"""
        esp_name = self.esp_name
        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )
        api_url = get_anymail_setting(
            "api_url",
            esp_name=esp_name,
            kwargs=kwargs,
            default="https://api.mailkite.dev/",
        )
        if not api_url.endswith("/"):
            api_url += "/"

        super().__init__(api_url, **kwargs)

    def build_message_payload(self, message, defaults):
        return MailKitePayload(message, defaults, self)

    def parse_recipient_status(self, response, payload, message):
        parsed_response = self.deserialize_json_response(response, payload, message)

        # Batch send: { "results": [ { "to", "id", "status", "error"?, "code"? }, ... ] }
        if (
            payload.is_batch()
            and isinstance(parsed_response, dict)
            and "results" in parsed_response
        ):
            # Build a map of echoed recipient address -> result, so we can match
            # MailKite's per-recipient outcome back to Anymail's addr_spec keys.
            results_by_addr = {}
            for result in parsed_response["results"]:
                addr = str(result.get("to", ""))
                # Normalise to the addr_spec (user@domain) for matching.
                results_by_addr[addr.lower()] = result

            recipient_status = CaseInsensitiveCasePreservingDict()
            for recip in payload.to_recipients:
                result = results_by_addr.get(recip.addr_spec.lower())
                if result is None:
                    # Couldn't match the echoed address; assume accepted.
                    status = "queued"
                elif str(result.get("status")) == "failed":
                    status = "rejected"
                else:  # "sent" or "scheduled" -- both mean MailKite accepted it
                    status = "queued"
                recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                    message_id=result.get("id") if result else None,
                    status=status,
                )
            # cc/bcc recipients aren't returned individually; mark them accepted.
            for recip in payload.recipients:
                if recip.addr_spec not in recipient_status:
                    recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                        message_id=None, status="queued"
                    )
            return dict(recipient_status)

        # Single send: { "id": "...", "status": "sent" | "scheduled" }
        try:
            message_id = parsed_response["id"]
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                "Invalid MailKite API response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status="queued"
                )
                for recip in payload.recipients
            }
        )
        return dict(recipient_status)


class MailKitePayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []  # for parse_recipient_status
        self.to_recipients = []  # for parse_recipient_status
        self.metadata = {}
        self.merge_metadata = {}
        self.merge_headers = {}
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer %s" % backend.api_key
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        if self.is_batch():
            return "v1/send/batch"
        return "v1/send"

    def serialize_data(self):
        if not self.is_batch():
            return self.serialize_json(self.data)

        # Batch send: MailKite's batch API takes a shared base message plus a
        # `recipients[]` array of { to, headers?, templateData? } per-recipient
        # overrides. Build that from the flat payload Anymail assembled.
        to_emails = self.data.pop("to", [])
        shared = dict(self.data)
        # MailKite's batch endpoint has no cc/bcc/replyTo fields -- each
        # recipient gets their own message addressed only to them.
        shared.pop("cc", None)
        shared.pop("bcc", None)
        shared.pop("replyTo", None)

        recipients = []
        for to_email, recip in zip(to_emails, self.to_recipients):
            recipient = {"to": to_email}
            if recip.addr_spec in self.merge_metadata:
                # Combine global metadata with this recipient's overrides, and
                # ship it as a per-recipient X-Metadata header (per-recipient
                # headers win over shared ones in MailKite's batch API).
                recipient_metadata = self.metadata.copy()
                recipient_metadata.update(self.merge_metadata[recip.addr_spec])
                recipient.setdefault("headers", {})["X-Metadata"] = self.serialize_json(
                    recipient_metadata
                )
            if recip.addr_spec in self.merge_headers:
                recipient.setdefault("headers", {}).update(
                    self.merge_headers[recip.addr_spec]
                )
            recipients.append(recipient)

        payload = dict(shared)
        payload["recipients"] = recipients
        return self.serialize_json(payload)

    #
    # Payload construction
    #

    def init_payload(self):
        self.data = {}  # becomes json

    def set_from_email(self, email):
        self.data["from"] = email.format(idna_encode=self.backend.idna_encode)

    def set_recipients(self, recipient_type, emails):
        assert recipient_type in ["to", "cc", "bcc"]
        if emails:
            field = recipient_type
            self.data[field] = [
                email.format(idna_encode=self.backend.idna_encode) for email in emails
            ]
            self.recipients += emails
            if recipient_type == "to":
                self.to_recipients = emails

    def set_subject(self, subject):
        self.data["subject"] = subject

    def set_reply_to(self, emails):
        # MailKite's API takes a single reply-to address (a string).
        # Only the first is used; multiple reply_to addresses are unsupported.
        if emails:
            if len(emails) > 1:
                self.unsupported_feature("multiple reply_to addresses")
            self.data["replyTo"] = emails[0].format(
                idna_encode=self.backend.idna_encode
            )

    def set_extra_headers(self, headers):
        # MailKite requires header values to be strings.
        self.data.setdefault("headers", {}).update(
            {
                k: str(v) if isinstance(v, BASIC_NUMERIC_TYPES) else v
                for k, v in headers.items()
            }
        )

    def set_text_body(self, body):
        self.data["text"] = body

    def set_html_body(self, body):
        if "html" in self.data:
            # second html body could show up through multiple alternatives,
            # or html body + alternative
            self.unsupported_feature("multiple html parts")
        self.data["html"] = body

    def make_attachment(self, attachment):
        """Returns MailKite attachment dict for attachment"""
        # MailKite's send API does not expose a Content-ID field, so it can't
        # place inline images -- raise rather than silently send them as regular
        # attachments.
        if attachment.inline:
            self.unsupported_feature("inline attachments (Content-ID)")

        filename = attachment.name or ""
        if not filename:
            # No name provided. Generate a default name with a reasonable extension.
            ext = mimetypes.guess_extension(attachment.mimetype)
            if ext:
                filename = "attachment%s" % ext
            else:
                self.unsupported_feature(
                    "unnamed attachments of type %s" % attachment.mimetype
                )
        att = {
            "content": attachment.b64content,
            "filename": filename,
            "contentType": attachment.content_type,
        }
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_metadata(self, metadata):
        # MailKite has no dedicated metadata field. Send it as json in a custom
        # X-Metadata header (custom headers are visible to recipients via "show
        # original" -- don't put secrets in metadata).
        self.data.setdefault("headers", {})["X-Metadata"] = self.serialize_json(
            metadata
        )
        self.metadata = metadata  # may be needed for batch send in serialize_data

    def set_send_at(self, send_at):
        try:
            # MailKite accepts ISO 8601 (and natural language / ms-epoch). Preserve
            # the offset if present; truncate microseconds to seconds.
            send_at = send_at.isoformat(
                timespec="milliseconds" if send_at.microsecond else "seconds"
            )
        except AttributeError:
            # User is responsible for formatting their own string (or POSIX timestamp)
            pass
        self.data["scheduledAt"] = send_at

    def set_tags(self, tags):
        # Send tags using a custom X-Tags header.
        self.data.setdefault("headers", {})["X-Tags"] = self.serialize_json(tags)

    def set_track_clicks(self, track_clicks):
        # MailKite supports per-message click-tracking overrides (unlike Resend).
        self.data["trackClicks"] = bool(track_clicks)

    def set_track_opens(self, track_opens):
        # MailKite supports per-message open-tracking overrides (unlike Resend).
        self.data["trackOpens"] = bool(track_opens)

    def set_template_id(self, template_id):
        # MailKite renders server-side templates (saved or base templates) and
        # fills {{merge_tags}} in subject/html/text.
        self.data["templateId"] = template_id

    def set_merge_global_data(self, merge_global_data):
        # Global merge values, filled into the template / subject / html / text.
        self.data["templateData"] = merge_global_data

    def set_merge_data(self, merge_data):
        # Empty merge_data is a request to use batch send (each To recipient gets
        # their own message, no per-recipient variables). Any actual per-recipient
        # merge data is unsupported.
        if any(recipient_data for recipient_data in merge_data.values()):
            self.unsupported_feature("merge_data")

    def set_merge_metadata(self, merge_metadata):
        self.merge_metadata = merge_metadata  # late bound in serialize_data

    def set_merge_headers(self, merge_headers):
        self.merge_headers = merge_headers  # late bound in serialize_data

    def set_esp_extra(self, extra):
        self.data.update(extra)
