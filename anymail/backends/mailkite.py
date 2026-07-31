import mimetypes

from ..exceptions import AnymailRequestsAPIError
from ..message import AnymailRecipientStatus
from ..utils import (
    BASIC_NUMERIC_TYPES,
    CaseInsensitiveCasePreservingDict,
    get_anymail_setting,
)
from .base_requests import AnymailRequestsBackend, RequestsPayload

# MailKite message status values returned from the send endpoint, mapped to
# Anymail's normalized recipient statuses. The API documents the send response
# as ``{"id": "...", "status": "..."}`` (e.g. ``"queued"``, or ``"scheduled"``
# for a send_at message parked for later delivery); we normalize ``"scheduled"``
# to Anymail's ``"queued"`` and pass other statuses through as-is, defaulting
# to ``"queued"`` when the ESP omits the status.
DEFAULT_RESPONSE_STATUS = "queued"
RESPONSE_STATUS_MAP = {"scheduled": "queued"}


class EmailBackend(AnymailRequestsBackend):
    """
    MailKite (mailkite.dev) API Email Backend

    MailKite is an inbound-first email platform: it sends transactional mail over
    a single JSON API and (unlike most ESPs) also *receives* mail — parsed body
    plus an authentication verdict, delivered as one signed webhook. This backend
    implements the transactional send API.
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

        if isinstance(parsed_response, dict) and "results" in parsed_response:
            # Batch send: per-recipient outcomes, in the same order as the
            # recipients we posted. A batch can partially succeed -- failed
            # recipients get status "failed" (no exception is raised).
            results = parsed_response["results"]
            if not isinstance(results, list) or len(results) != len(
                payload.to_recipients
            ):
                raise AnymailRequestsAPIError(
                    "Invalid MailKite API batch response format",
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                )
            recipient_status = CaseInsensitiveCasePreservingDict()
            for recip, result in zip(payload.to_recipients, results):
                status = result.get("status", DEFAULT_RESPONSE_STATUS)
                if status == "failed" and result.get("code") == "recipient_suppressed":
                    # unsubscribed / bounced / complained address
                    status = "rejected"
                status = RESPONSE_STATUS_MAP.get(status, status)
                recipient_status[recip.addr_spec] = AnymailRecipientStatus(
                    message_id=result.get("id"), status=status
                )
            return dict(recipient_status)

        try:
            message_id = parsed_response["id"]
            status = parsed_response.get("status", DEFAULT_RESPONSE_STATUS)
            status = RESPONSE_STATUS_MAP.get(status, status)
        except (KeyError, TypeError) as err:
            raise AnymailRequestsAPIError(
                "Invalid MailKite API response format",
                email_message=message,
                payload=payload,
                response=response,
                backend=self,
            ) from err

        # MailKite sends one message (one returned id) covering every recipient.
        recipient_status = CaseInsensitiveCasePreservingDict(
            {
                recip.addr_spec: AnymailRecipientStatus(
                    message_id=message_id, status=status
                )
                for recip in payload.recipients
            }
        )
        return dict(recipient_status)


class MailKitePayload(RequestsPayload):
    def __init__(self, message, defaults, backend, *args, **kwargs):
        self.recipients = []  # for parse_recipient_status
        self.to_recipients = []  # `to` only, for batch fan-out
        self.metadata = None  # needed to merge with merge_metadata in batch
        self.merge_data = {}
        self.merge_metadata = {}
        self.merge_headers = {}
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = "Bearer %s" % backend.api_key
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        super().__init__(message, defaults, backend, headers=headers, *args, **kwargs)

    def get_api_endpoint(self):
        if self.is_batch():
            # One personalized message per `to` recipient.
            return "v1/send/batch"
        return "v1/send"

    def serialize_data(self):
        if self.is_batch():
            self.restructure_data_for_batch()
        return self.serialize_json(self.data)

    def restructure_data_for_batch(self):
        """Convert the single-send payload to MailKite's batch-send shape"""
        # Shared fields (from/subject/html/text/templateId/templateData/headers/
        # replyTo/attachments/scheduledAt/...) stay as built; the `to` list
        # becomes recipients[], each entry carrying its own templateData and
        # headers merged over the shared ones (per-recipient wins).
        if "cc" in self.data or "bcc" in self.data:
            # Batch sends one message per `to` recipient; there is no cc/bcc.
            self.unsupported_feature("cc or bcc with batch send")
        self.data.pop("to", None)
        recipients = []
        for email in self.to_recipients:
            recipient = {"to": email.format(idna_encode=self.backend.idna_encode)}
            recipient_data = self.merge_data.get(email.addr_spec)
            if recipient_data:
                recipient["templateData"] = recipient_data
            headers = {}
            if email.addr_spec in self.merge_metadata:
                # Anymail semantics: this recipient's metadata is `metadata`
                # updated with their merge_metadata entry.
                recipient_metadata = dict(self.metadata or {})
                recipient_metadata.update(self.merge_metadata[email.addr_spec])
                headers["X-Metadata"] = self.serialize_json(recipient_metadata)
            if email.addr_spec in self.merge_headers:
                headers.update(self.merge_headers[email.addr_spec])
            if headers:
                recipient["headers"] = headers
            recipients.append(recipient)
        self.data["recipients"] = recipients

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
        # MailKite's ``replyTo`` is a single string. A header value can hold
        # multiple addresses, so join them rather than dropping any.
        if emails:
            self.data["replyTo"] = ", ".join(
                email.format(idna_encode=self.backend.idna_encode) for email in emails
            )

    def set_extra_headers(self, headers):
        # MailKite requires header values to be strings. Stringify ints/floats;
        # anything else is the caller's responsibility.
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
        """Returns a MailKite attachment dict for the attachment"""
        if attachment.inline:
            # The MailKite send API has no Content-ID / inline-attachment field,
            # so we can't accurately communicate inline attachments.
            self.unsupported_feature("inline attachments")

        filename = attachment.name or ""
        if not filename:
            # MailKite requires a filename. Generate a reasonable default.
            ext = mimetypes.guess_extension(attachment.mimetype or "")
            if ext:
                filename = "attachment%s" % ext
            else:
                self.unsupported_feature(
                    "unnamed attachments of type %s" % attachment.mimetype
                )
        att = {
            "filename": filename,
            "content": attachment.b64content,
        }
        if attachment.mimetype:
            att["contentType"] = attachment.mimetype
        return att

    def set_attachments(self, attachments):
        if attachments:
            self.data["attachments"] = [
                self.make_attachment(attachment) for attachment in attachments
            ]

    def set_metadata(self, metadata):
        # MailKite has no dedicated metadata field; carry it as JSON in a custom
        # header (the ESP accepts arbitrary string-valued raw MIME headers).
        self.data.setdefault("headers", {})["X-Metadata"] = self.serialize_json(
            metadata
        )
        self.metadata = metadata  # merged with merge_metadata in a batch send

    def set_tags(self, tags):
        # MailKite has no tags field; carry them as JSON in a custom header.
        self.data.setdefault("headers", {})["X-Tags"] = self.serialize_json(tags)

    def set_send_at(self, send_at):
        # A future scheduledAt parks the message for MailKite's scheduler;
        # an omitted or past value sends immediately.
        try:
            send_at = send_at.isoformat(
                timespec="milliseconds" if send_at.microsecond else "seconds"
            )
        except AttributeError:
            # User is responsible for formatting their own string
            pass
        self.data["scheduledAt"] = send_at

    def set_track_opens(self, track_opens):
        # Per-send open-tracking override (HTML messages only). When omitted,
        # the from-domain's default applies.
        self.data["trackOpens"] = track_opens

    def set_track_clicks(self, track_clicks):
        # Per-send click-tracking override (HTML messages only): MailKite
        # rewrites links to a signed redirect that records the click. When
        # omitted, the from-domain's default applies.
        self.data["trackClicks"] = track_clicks

    # def set_envelope_sender(self, envelope_sender):

    def set_template_id(self, template_id):
        self.data["templateId"] = template_id

    def set_merge_global_data(self, merge_global_data):
        # MailKite renders templates server-side from templateData.
        self.data["templateData"] = merge_global_data

    # Setting any of merge_data / merge_metadata / merge_headers switches to
    # MailKite's batch-send endpoint: one personalized message per `to`
    # recipient, with per-recipient values merged over the shared ones.
    # The payload is restructured in serialize_data (see
    # restructure_data_for_batch), once every attribute has been processed.

    def set_merge_data(self, merge_data):
        self.merge_data = merge_data

    def set_merge_metadata(self, merge_metadata):
        self.merge_metadata = merge_metadata

    def set_merge_headers(self, merge_headers):
        self.merge_headers = merge_headers

    def set_esp_extra(self, extra):
        self.data.update(extra)
