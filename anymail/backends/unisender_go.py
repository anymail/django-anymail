from __future__ import annotations

import typing
import uuid
from datetime import datetime, timezone

from django.core.mail import EmailMessage
from requests import Response
from requests.structures import CaseInsensitiveDict

from anymail.backends.base_requests import AnymailRequestsBackend, RequestsPayload
from anymail.message import AnymailRecipientStatus
from anymail.utils import (
    Attachment,
    EmailAddress,
    get_anymail_setting,
    has_specials,
    rfc2047_encode,
    update_deep,
)


class EmailBackend(AnymailRequestsBackend):
    """Unisender Go v1 Web API Email Backend"""

    esp_name = "Unisender Go"

    def __init__(self, **kwargs: typing.Any):
        """Init options from Django settings"""
        esp_name = self.esp_name

        self.api_key = get_anymail_setting(
            "api_key", esp_name=esp_name, kwargs=kwargs, allow_bare=True
        )

        self.generate_message_id = get_anymail_setting(
            "generate_message_id", esp_name=esp_name, kwargs=kwargs, default=True
        )

        # No default for api_url setting -- it depends on account's data center. E.g.:
        # - https://go1.unisender.ru/ru/transactional/api/v1
        # - https://go2.unisender.ru/ru/transactional/api/v1
        api_url = get_anymail_setting("api_url", esp_name=esp_name, kwargs=kwargs)
        if not api_url.endswith("/"):
            api_url += "/"

        # Undocumented setting to control workarounds for Unisender Go display-name issues
        # (see below). If/when Unisender Go fixes the problems, you can disable Anymail's
        # workarounds by adding `"UNISENDER_GO_WORKAROUND_DISPLAY_NAME_BUGS": False`
        # to your `ANYMAIL` settings.
        self.workaround_display_name_bugs = get_anymail_setting(
            "workaround_display_name_bugs",
            esp_name=esp_name,
            kwargs=kwargs,
            default=True,
        )

        super().__init__(api_url, **kwargs)

    def build_message_payload(
        self, message: EmailMessage, defaults: dict
    ) -> UnisenderGoPayload:
        return UnisenderGoPayload(message=message, defaults=defaults, backend=self)

    # Map Unisender Go "failed_email" code -> AnymailRecipientStatus.status
    _unisender_failure_status = {
        # "duplicate": ignored (see parse_recipient_status)
        "invalid": "invalid",
        "permanent_unavailable": "rejected",
        "temporary_unavailable": "failed",
        "unsubscribed": "rejected",
    }

    def parse_recipient_status(
        self, response: Response, payload: UnisenderGoPayload, message: EmailMessage
    ) -> dict:
        """
        Response example:
        {
          "status": "success",
          "job_id": "1ZymBc-00041N-9X",
          "emails": [
            "user@example.com",
            "email@example.com",
          ],
          "failed_emails": {
            "email1@gmail.com": "temporary_unavailable",
            "bad@address": "invalid",
            "email@example.com": "duplicate",
            "root@example.org": "permanent_unavailable",
            "olduser@example.net": "unsubscribed"
          }
        }
        """
        parsed_response = self.deserialize_json_response(response, payload, message)
        # job_id serves as message_id when not self.generate_message_id
        job_id = parsed_response.get("job_id")
        succeed_emails = {
            recipient: AnymailRecipientStatus(
                message_id=payload.message_ids.get(recipient, job_id), status="queued"
            )
            for recipient in parsed_response["emails"]
        }
        failed_emails = {
            recipient: AnymailRecipientStatus(
                # Message wasn't sent to this recipient, so Unisender Go hasn't stored
                # any metadata (including message_id)
                message_id=None,
                status=self._unisender_failure_status.get(status, "failed"),
            )
            for recipient, status in parsed_response.get("failed_emails", {}).items()
            if status != "duplicate"  # duplicates are in both succeed and failed lists
        }
        return {**succeed_emails, **failed_emails}


class UnisenderGoPayload(RequestsPayload):
    # Payload: see https://godocs.unisender.ru/web-api-ref#email-send

    data: dict

    def __init__(
        self,
        message: EmailMessage,
        defaults: dict,
        backend: EmailBackend,
        *args: typing.Any,
        **kwargs: typing.Any,
    ):
        self.generate_message_id = backend.generate_message_id
        self.message_ids = CaseInsensitiveDict()  # recipient -> generated message_id

        http_headers = kwargs.pop("headers", {})
        http_headers["Content-Type"] = "application/json"
        http_headers["Accept"] = "application/json"
        http_headers["X-API-KEY"] = backend.api_key
        super().__init__(
            message, defaults, backend, headers=http_headers, *args, **kwargs
        )

    def get_api_endpoint(self) -> str:
        return "email/send.json"

    def init_payload(self) -> None:
        self.data = {  # becomes json
            "headers": CaseInsensitiveDict(),
            "recipients": [],
        }

    def serialize_data(self) -> str:
        if self.generate_message_id:
            self.set_anymail_id()

        headers = self.data["headers"]
        if self.is_batch():
            # Remove the all-recipient "to" header for batch sends.
            # Unisender Go will construct a single-recipient "to" for each recipient.
            # Unisender Go doesn't allow a "cc" header without an explicit "to"
            # header, so we cannot support "cc" for batch sends.
            headers.pop("to", None)
            if headers.pop("cc", None):
                self.unsupported_feature(
                    "cc with batch send (merge_data, merge_metadata, or merge_headers)"
                )

        if not headers:
            del self.data["headers"]  # don't send empty headers

        return self.serialize_json({"message": self.data})

    def set_anymail_id(self) -> None:
        """Ensure each personalization has a known anymail_id for event tracking"""
        for recipient in self.data["recipients"]:
            # This ensures duplicate recipients get same anymail_id
            # (because Unisender Go only sends to first instance of duplicate)
            email_address = recipient["email"]
            anymail_id = self.message_ids.get(email_address) or str(uuid.uuid4())
            recipient.setdefault("metadata", {})["anymail_id"] = anymail_id
            self.message_ids[email_address] = anymail_id

    #
    # Payload construction
    #

    def set_from_email(self, email: EmailAddress) -> None:
        self.data.update(
            email.as_dict(
                email="from_email",
                name="from_name",
                idna_encode=self.backend.idna_encode,
            )
        )

    _display_name_bug_chars = set(",<>@")

    def _format_email_address(self, address):
        """
        Return EmailAddress address formatted for use with Unisender Go to/cc headers.

        Works around a bug in Unisender Go's API that rejects To or Cc headers
        containing commas, angle brackets, or @ in any display-name, despite those
        names being properly enclosed in "quotes" per RFC 5322. Workaround substitutes
        an RFC 2047 encoded word, which avoids the problem characters.

        Note that parens, quote chars, and other special characters appearing
        in "quoted strings" don't cause problems. (Unisender Go tech support
        has confirmed the problem is limited to , < > @.)

        This workaround is only necessary in the To and Cc headers. Unisender Go
        properly formats commas and other characters in `to_name` and `from_name`.
        (But see set_reply_to for a related issue.)
        """
        use_rfc2047 = True
        if (
            self.backend.workaround_display_name_bugs
            and not self._display_name_bug_chars.isdisjoint(address.display_name)
        ):
            use_rfc2047 = "force"
        return address.format(
            use_rfc2047=use_rfc2047, idna_encode=self.backend.idna_encode
        )

    def set_recipients(self, recipient_type: str, emails: list[EmailAddress]):
        for email in emails:
            recipient = {
                "email": email.format_addr_spec(idna_encode=self.backend.idna_encode)
            }
            if email.display_name:
                recipient["substitutions"] = {"to_name": email.display_name}
            self.data["recipients"].append(recipient)

        if emails and recipient_type in {"to", "cc"}:
            # Add "to" or "cc" header listing all recipients of type.
            # See https://godocs.unisender.ru/cc-and-bcc.
            # (For batch sends, these will be adjusted later in self.serialize_data.)
            self.data["headers"][recipient_type] = ", ".join(
                self._format_email_address(email) for email in emails
            )

    def set_subject(self, subject: str) -> None:
        if subject:
            self.data["subject"] = subject

    def set_reply_to(self, emails: list[EmailAddress]) -> None:
        # Unisender Go only supports a single address in the reply_to API param.
        if len(emails) > 1:
            self.unsupported_feature("multiple reply_to addresses")
        if len(emails) > 0:
            reply_to = emails[0]
            self.data["reply_to"] = reply_to.format_addr_spec(
                idna_encode=self.backend.idna_encode
            )
            display_name = reply_to.display_name
            if display_name:
                use_rfc2047 = False
                if self.backend.workaround_display_name_bugs:
                    # Unisender Go has two bugs with display names in their generated
                    # Reply-To headers:
                    # - Non-ASCII display names are sent as unencoded (8-bit)
                    #   ISO-8859-1, which can interfere with delivery.
                    # - Display names with special characters (comma, parens, etc.) are
                    #   not properly quoted (per RFC 5322), resulting in an invalid
                    #   Reply-To header that can cause problems when the recipient
                    #   tries to reply.
                    # These issues only affect the reply_to_name. Unisender Go correctly
                    # encodes display names in other address headers.
                    if not display_name.isascii() or has_specials(display_name):
                        use_rfc2047 = "force"
                self.data["reply_to_name"] = reply_to.format_display_name(
                    use_rfc2047=use_rfc2047
                )

    def set_extra_headers(self, headers: dict[str, str]) -> None:
        # Unisender Go incorrectly converts non-ASCII extra headers to ISO-8859-1
        # and sends them as 8-bit content. Work around by converting to RFC 2047.
        self.data["headers"].update(
            {
                field: (
                    rfc2047_encode(value)
                    if isinstance(value, str) and not value.isascii()
                    else value
                )
                for field, value in headers.items()
            }
        )

    def set_text_body(self, body: str) -> None:
        if body:
            self.data.setdefault("body", {})["plaintext"] = body

    def set_html_body(self, body: str) -> None:
        if body:
            self.data.setdefault("body", {})["html"] = body

    def add_alternative(self, content: str, mimetype: str):
        if mimetype.lower() == "text/x-amp-html":
            if "amp" in self.data.get("body", {}):
                self.unsupported_feature("multiple amp-html parts")
            self.data.setdefault("body", {})["amp"] = content
        else:
            super().add_alternative(content, mimetype)

    def add_attachment(self, attachment: Attachment) -> None:
        name = attachment.cid if attachment.inline else attachment.name
        att = {
            "content": attachment.b64content,
            "type": attachment.mimetype,
            "name": name or "",  # required - submit empty string if unknown
        }
        if attachment.inline:
            self.data.setdefault("inline_attachments", []).append(att)
        else:
            self.data.setdefault("attachments", []).append(att)

    def set_metadata(self, metadata: dict[str, str]) -> None:
        self.data["global_metadata"] = metadata

    def set_send_at(self, send_at: datetime | str) -> None:
        try:
            # "Date and time in the format “YYYY-MM-DD hh:mm:ss” in the UTC time zone."
            # If send_at is a datetime, it's guaranteed to be aware, but maybe not UTC.
            # Convert to UTC, then strip tzinfo to avoid isoformat "+00:00" at end.
            send_at_utc = send_at.astimezone(timezone.utc).replace(tzinfo=None)
            send_at_formatted = send_at_utc.isoformat(sep=" ", timespec="seconds")
            assert len(send_at_formatted) == 19
        except (AttributeError, TypeError):
            # Not a datetime - caller is responsible for formatting
            send_at_formatted = send_at
        self.data.setdefault("options", {})["send_at"] = send_at_formatted

    def set_tags(self, tags: list[str]) -> None:
        self.data["tags"] = tags

    def set_track_clicks(self, track_clicks: typing.Any):
        self.data["track_links"] = 1 if track_clicks else 0

    def set_track_opens(self, track_opens: typing.Any):
        self.data["track_read"] = 1 if track_opens else 0

    def set_template_id(self, template_id: str) -> None:
        self.data["template_id"] = template_id

    def set_merge_data(self, merge_data: dict[str, dict[str, str]]) -> None:
        if not merge_data:
            return
        assert self.data["recipients"]  # must be called after set_to
        for recipient in self.data["recipients"]:
            recipient_email = recipient["email"]
            if recipient_email in merge_data:
                # (substitutions may already be present with "to_email")
                recipient.setdefault("substitutions", {}).update(
                    merge_data[recipient_email]
                )

    def set_merge_global_data(self, merge_global_data: dict[str, str]) -> None:
        self.data["global_substitutions"] = merge_global_data

    def set_merge_metadata(self, merge_metadata: dict[str, str]) -> None:
        assert self.data["recipients"]  # must be called after set_to
        for recipient in self.data["recipients"]:
            recipient_email = recipient["email"]
            if recipient_email in merge_metadata:
                recipient["metadata"] = merge_metadata[recipient_email]

    # Unisender Go supports header substitution only with List-Unsubscribe.
    # (See https://godocs.unisender.ru/web-api-ref#email-send under "substitutions".)
    SUPPORTED_MERGE_HEADERS = {"List-Unsubscribe"}

    def set_merge_headers(self, merge_headers: dict[str, dict[str, str]]) -> None:
        assert self.data["recipients"]  # must be called after set_to
        if merge_headers:
            for recipient in self.data["recipients"]:
                recipient_email = recipient["email"]
                for key, value in merge_headers.get(recipient_email, {}).items():
                    field = key.title()  # canonicalize field name capitalization
                    if field in self.SUPPORTED_MERGE_HEADERS:
                        # Set up a substitution for Header__Field_Name
                        field_sub = "Header__" + field.replace("-", "_")
                        recipient.setdefault("substitutions", {})[field_sub] = value
                        self.data.setdefault("headers", {})[field] = (
                            "{{%s}}" % field_sub
                        )
                    else:
                        self.unsupported_feature(f"{field!r} in merge_headers")

    def set_esp_extra(self, extra: dict) -> None:
        update_deep(self.data, extra)
