import base64
import hashlib
import hmac
import json
from email.headerregistry import Address
from email.message import EmailMessage

import requests
from django.utils.dateparse import parse_datetime

from ..exceptions import AnymailAPIError, AnymailWebhookValidationFailure
from ..inbound import AnymailInboundMessage
from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from ..utils import angle_wrap, get_anymail_setting
from .base import AnymailBaseWebhookView


class SweegoTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for Sweego delivery and engagement tracking webhooks"""

    esp_name = "Sweego"
    signal = tracking

    # Sweego uses signature-based validation, not basic auth
    warn_if_no_basic_auth = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webhook_secret = get_anymail_setting(
            "webhook_secret",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=None,
            allow_bare=True,
        )

    def validate_request(self, request):
        """Validate the webhook signature using Sweego's method"""
        if self.webhook_secret:
            # Get required headers
            signature = request.headers.get(
                "X-Sweego-Signature"
            ) or request.headers.get("Webhook-Signature")
            webhook_id = request.headers.get("Webhook-Id")
            webhook_timestamp = request.headers.get("Webhook-Timestamp")

            if not signature:
                raise AnymailWebhookValidationFailure(
                    "Missing webhook signature header. "
                    "Webhook signature validation failed."
                )

            if not webhook_id or not webhook_timestamp:
                raise AnymailWebhookValidationFailure(
                    "Missing webhook-id or webhook-timestamp headers. "
                    "Webhook signature validation failed."
                )

            # Format content to sign: WEBHOOK_ID.WEBHOOK_TIMESTAMP.BODY
            # According to Sweego documentation
            body = request.body.decode("utf-8")
            content_to_sign = f"{webhook_id}.{webhook_timestamp}.{body}".encode("utf-8")

            # Decode secret from base64 (Sweego stores it as base64)
            secret_bytes = base64.b64decode(self.webhook_secret)

            # Compute HMAC-SHA256
            expected_signature_bytes = hmac.new(
                secret_bytes, content_to_sign, hashlib.sha256
            ).digest()

            # Convert to base64 for comparison
            expected_signature = base64.b64encode(expected_signature_bytes).decode(
                "utf-8"
            )

            if not hmac.compare_digest(signature, expected_signature):
                raise AnymailWebhookValidationFailure(
                    "Invalid Sweego webhook signature. "
                    "Check your SWEEGO_WEBHOOK_SECRET setting."
                )

    # Map Sweego event_type to Anymail EventType
    # Based on Sweego documentation:
    # - email_sent: email accepted by Sweego
    # - delivered: email delivered to recipient's server
    # - soft-bounce: temporary delivery failure
    # - hard_bounce: permanent delivery failure
    # - list_unsub: unsubscribe via List-Unsubscribe header
    # - complaint: spam complaint (FBL)
    # - email_clicked: link clicked
    # - email_opened: email opened (pixel tracking)
    event_types = {
        "email_sent": EventType.SENT,
        "delivered": EventType.DELIVERED,
        "soft-bounce": EventType.DEFERRED,
        "hard_bounce": EventType.BOUNCED,
        "list_unsub": EventType.UNSUBSCRIBED,
        "complaint": EventType.COMPLAINED,
        "email_clicked": EventType.CLICKED,
        "email_opened": EventType.OPENED,
    }

    def parse_events(self, request):
        """Parse Sweego webhook events"""
        esp_events = json.loads(request.body.decode("utf-8"))

        # Sweego can send single event or batch of events
        if not isinstance(esp_events, list):
            esp_events = [esp_events]

        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    def esp_to_anymail_event(self, esp_event):
        """Convert a Sweego event to an AnymailTrackingEvent"""
        event_type_str = esp_event.get("event_type", "")
        event_type = self.event_types.get(event_type_str, EventType.UNKNOWN)

        # Sweego sends ISO 8601 timestamps like "2024-09-02T08:45:05+00:00"
        timestamp = None
        timestamp_str = esp_event.get("timestamp")
        if timestamp_str:
            timestamp = parse_datetime(timestamp_str)

        # message_id is swg_uid (Sweego's unique identifier)
        message_id = esp_event.get("swg_uid")

        # event_id is unique per event
        event_id = esp_event.get("event_id")

        # recipient email address
        recipient = esp_event.get("recipient")

        # Extract metadata from headers (X-Metadata-* pattern or other custom headers)
        metadata = {}
        tags = []
        headers = esp_event.get("headers", {})
        if headers:
            for key, value in headers.items():
                key_lower = key.lower()
                # Extract X-Metadata-* headers
                if key_lower.startswith("x-metadata-"):
                    metadata_key = key[11:]  # Remove "X-Metadata-" prefix
                    metadata[metadata_key] = value

        # Tags from campaign_tags field (can be string, array, or null)
        campaign_tags = esp_event.get("campaign_tags")
        if campaign_tags:
            if isinstance(campaign_tags, list):
                tags = campaign_tags
            elif isinstance(campaign_tags, str):
                tags = [campaign_tags]

        # Reject reason for bounces
        reject_reason = None
        if event_type == EventType.BOUNCED:
            reject_reason = RejectReason.BOUNCED
        elif event_type == EventType.DEFERRED:
            # Soft bounce - could be temporary
            reject_reason = RejectReason.BOUNCED
        elif event_type == EventType.COMPLAINED:
            reject_reason = RejectReason.SPAM

        # MTA response from details field for bounces
        mta_response = None
        description = None
        if event_type in (EventType.BOUNCED, EventType.DEFERRED):
            details = esp_event.get("details")
            if details:
                mta_response = details
            # response_code might be present for bounces
            response_code = esp_event.get("response_code")
            if response_code:
                description = f"SMTP {response_code}"

        # Click data from 'click' object
        click_url = None
        user_agent = None
        if event_type == EventType.CLICKED:
            click_data = esp_event.get("click", {})
            click_url = click_data.get("url")
            user_agent = click_data.get("user_agent")

        # Open data from 'open' object
        if event_type == EventType.OPENED:
            open_data = esp_event.get("open", {})
            user_agent = open_data.get("user_agent")

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=event_id,
            recipient=recipient,
            reject_reason=reject_reason,
            description=description,
            mta_response=mta_response,
            tags=tags,
            metadata=metadata,
            click_url=click_url,
            user_agent=user_agent,
            esp_event=esp_event,
        )


class SweegoInboundWebhookView(AnymailBaseWebhookView):
    """Handler for Sweego inbound email webhooks.

    Sweego's Inbound Email Routing feature parses incoming emails
    and delivers them as JSON payloads via webhook.

    Webhook payload format (email_inbound event):
    {
        "event_type": "email_inbound",
        "timestamp": "2024-12-19T13:49:28.849638+00:00",
        "swg_uid": "test-inbound-msg-uuid-aaaa-bbbb-aaaaaaaabbbb",
        "from_": {"email": "sender@example.com", "name": "Sender Name"},
        "to": [{"email": "recipient@inbound.example.com", "name": ""}],
        "cc": [],
        "text": "Plain text body",
        "html": "<p>HTML body</p>",
        "subject": "Email subject",
        "inbound_domain": "inbound.example.com",
        "event_id": "10c072f1-7821-4f30-9574-f13e3890701a",
        "channel": "email",
        "transaction_id": null,
        "attachments": [...]  # Optional
    }
    """

    esp_name = "Sweego"
    signal = inbound

    # Sweego uses signature-based validation, not basic auth
    warn_if_no_basic_auth = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.webhook_secret = get_anymail_setting(
            "webhook_secret",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=None,
            allow_bare=True,
        )
        # For fetching attachments via API
        self.api_key = get_anymail_setting(
            "api_key",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=None,
            allow_bare=True,
        )
        self.client_uuid = get_anymail_setting(
            "client_uuid",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=None,
            allow_bare=True,
        )
        self.api_url = get_anymail_setting(
            "api_url",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default="https://api.sweego.io",
            allow_bare=True,
        )

    def validate_request(self, request):
        """Validate the webhook signature using Sweego's method"""
        if self.webhook_secret:
            # Get required headers
            signature = request.headers.get(
                "X-Sweego-Signature"
            ) or request.headers.get("Webhook-Signature")
            webhook_id = request.headers.get("Webhook-Id")
            webhook_timestamp = request.headers.get("Webhook-Timestamp")

            if not signature:
                raise AnymailWebhookValidationFailure(
                    "Missing webhook signature header. "
                    "Webhook signature validation failed."
                )

            if not webhook_id or not webhook_timestamp:
                raise AnymailWebhookValidationFailure(
                    "Missing webhook-id or webhook-timestamp headers. "
                    "Webhook signature validation failed."
                )

            # Format content to sign: WEBHOOK_ID.WEBHOOK_TIMESTAMP.BODY
            # According to Sweego documentation
            body = request.body.decode("utf-8")
            content_to_sign = f"{webhook_id}.{webhook_timestamp}.{body}".encode("utf-8")

            # Decode secret from base64 (Sweego stores it as base64)
            secret_bytes = base64.b64decode(self.webhook_secret)

            # Compute HMAC-SHA256
            expected_signature_bytes = hmac.new(
                secret_bytes, content_to_sign, hashlib.sha256
            ).digest()

            # Convert to base64 for comparison
            expected_signature = base64.b64encode(expected_signature_bytes).decode(
                "utf-8"
            )

            if not hmac.compare_digest(signature, expected_signature):
                raise AnymailWebhookValidationFailure(
                    "Invalid Sweego webhook signature. "
                    "Check your SWEEGO_WEBHOOK_SECRET setting."
                )

    def parse_events(self, request):
        """Parse Sweego inbound webhook events"""
        esp_events = json.loads(request.body.decode("utf-8"))

        # Sweego can send single event or batch of events
        if not isinstance(esp_events, list):
            esp_events = [esp_events]

        return [
            self.esp_to_anymail_event(esp_event)
            for esp_event in esp_events
            if esp_event.get("event_type") == "email_inbound"
        ]

    def esp_to_anymail_event(self, esp_event):
        """Convert a Sweego inbound event to an AnymailInboundEvent"""
        # Build the message using AnymailInboundMessage
        message = self._build_inbound_message(esp_event)

        # Parse timestamp
        timestamp = None
        timestamp_str = esp_event.get("timestamp")
        if timestamp_str:
            timestamp = parse_datetime(timestamp_str)

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timestamp,
            event_id=esp_event.get("event_id"),
            esp_event=esp_event,
            message=message,
        )

    def _build_inbound_message(self, esp_event):
        """Build an AnymailInboundMessage from Sweego's JSON payload"""
        # Extract from address
        from_data = esp_event.get("from_", {})
        from_email = from_data.get("email", "")
        from_name = from_data.get("name", "")

        # Extract to addresses
        to_list = esp_event.get("to", [])
        to_addresses = []
        for addr in to_list:
            email = addr.get("email", "")
            name = addr.get("name", "")
            if name:
                # Use Address to safely construct formatted address
                to_addresses.append(str(Address(display_name=name, addr_spec=email)))
            else:
                to_addresses.append(email)

        # Extract cc addresses
        cc_list = esp_event.get("cc", [])
        cc_addresses = []
        for addr in cc_list:
            email = addr.get("email", "")
            name = addr.get("name", "")
            if name:
                # Use Address to safely construct formatted address
                cc_addresses.append(str(Address(display_name=name, addr_spec=email)))
            else:
                cc_addresses.append(email)

        # Get body content
        text_body = esp_event.get("text")
        html_body = esp_event.get("html")
        subject = esp_event.get("subject", "")

        # Build lazy attachments from metadata
        # Sweego only provides attachment metadata in webhooks (uuid, name, content_type, size)
        # The actual content must be fetched via API when accessed
        attachments = None
        if esp_event.get("attachments") and self.api_key and self.client_uuid:
            attachments = [
                construct_sweego_lazy_attachment(
                    attachment_data=att,
                    api_url=self.api_url,
                    api_key=self.api_key,
                    client_uuid=self.client_uuid,
                )
                for att in esp_event["attachments"]
            ]

        # Use AnymailInboundMessage.construct for proper multipart handling
        # Safely construct from_email using Address to prevent header injection
        from_email_formatted = (
            str(Address(display_name=from_name, addr_spec=from_email))
            if from_name
            else from_email
        )

        message = AnymailInboundMessage.construct(
            from_email=from_email_formatted,
            to=", ".join(to_addresses) if to_addresses else None,
            cc=", ".join(cc_addresses) if cc_addresses else None,
            subject=subject,
            text=text_body,
            html=html_body,
            attachments=attachments,
        )

        # Set Anymail-specific envelope fields
        # envelope_sender: the actual sending address from MAIL FROM
        message.envelope_sender = from_email if from_email else None

        # envelope_recipient: typically the first To address
        if to_list:
            message.envelope_recipient = to_list[0].get("email")
        else:
            message.envelope_recipient = None

        # Sweego doesn't provide spam detection info
        message.spam_detected = None
        message.spam_score = None

        # stripped_text is not provided by Sweego
        message.stripped_text = None
        message.stripped_html = None

        return message


"""
Sweego-specific inbound email attachment handling.

Sweego's inbound email routing does not include attachment content in webhooks.
Instead, it provides attachment metadata (uuid, name, content_type, size) and
requires a separate API call to fetch the actual attachment content.
"""


class SweegoLazyAttachment(EmailMessage):
    """
    A lazy-loading attachment for Sweego inbound emails.

    The attachment content is only fetched from Sweego's API when accessed.
    This avoids unnecessary API calls if the attachment is never used.

    Attributes:
        uuid: Sweego's unique identifier for this attachment
        filename: Original filename
        content_type: MIME type
        size: Size in bytes
        api_url: Base URL for Sweego API
        api_key: API key for authentication
        client_uuid: Sweego client UUID
    """

    def __init__(
        self,
        uuid,
        filename,
        content_type,
        size,
        api_url,
        api_key,
        client_uuid,
        content_id=None,
    ):
        super().__init__()

        # Sweego attachment metadata
        self.uuid = uuid
        self.filename = filename
        self.size = size
        self.api_url = api_url
        self.api_key = api_key
        self.client_uuid = client_uuid

        # Cached content
        self._content = None
        self._fetched = False

        # Set email message headers
        self["Content-Type"] = content_type
        self["Content-Disposition"] = (
            "inline" if content_id is not None else "attachment"
        )

        if filename:
            self.set_param("name", filename, header="Content-Type")
            self.set_param("filename", filename, header="Content-Disposition")

        if content_id is not None:
            self["Content-ID"] = angle_wrap(content_id)

    def _fetch_content(self):
        """
        Fetch the attachment content from Sweego's API.

        Makes a GET request to:
        https://api.sweego.io/clients/{client_uuid}/domains/inbound/attachments/{uuid}

        Raises:
            AnymailAPIError: If the API request fails
        """
        if self._fetched:
            return

        url = (
            f"{self.api_url}/clients/{self.client_uuid}"
            f"/domains/inbound/attachments/{self.uuid}"
        )

        headers = {
            "Api-Key": self.api_key,
            "Accept": "application/octet-stream",  # Get raw binary content
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            self._content = response.content
            self._fetched = True
        except requests.RequestException as e:
            raise AnymailAPIError(
                f"Failed to fetch Sweego attachment {self.uuid}: {e}",
                backend=None,
                email_message=None,
                payload=None,
            ) from e

    def get_payload(self, i=None, decode=False):
        """
        Override to fetch content on first access.

        This method is called by get_content(), get_content_bytes(), etc.
        """
        if not self._fetched:
            self._fetch_content()

        if self._content is None:
            return None

        # If decode=True, the caller wants the decoded content
        # For binary attachments, we just return the raw bytes
        if decode:
            return self._content

        # If decode=False, we need to return the content in a way
        # that email.message.EmailMessage expects
        return self._content

    def set_payload(self, payload, charset=None):
        """
        Override to cache the content without fetching.

        This allows the attachment to be pre-populated if needed.
        """
        self._content = payload
        self._fetched = True

    def get_content_bytes(self):
        """Get the raw attachment content as bytes."""
        if not self._fetched:
            self._fetch_content()
        return self._content

    def get_content_text(self, encoding=None):
        """
        Get the attachment content as text.

        Only appropriate for text/* content types.
        """
        content = self.get_content_bytes()
        if content is None:
            return None

        if encoding is None:
            # Try to get encoding from Content-Type charset parameter
            charset = self.get_param("charset")
            encoding = charset if charset else "utf-8"

        return content.decode(encoding, errors="replace")

    def get_filename(self):
        """Get the attachment filename."""
        # Try Content-Disposition first (standard)
        filename = self.get_param("filename", header="Content-Disposition")
        if filename:
            return filename

        # Fall back to Content-Type name parameter
        filename = self.get_param("name", header="Content-Type")
        if filename:
            return filename

        # Fall back to our stored filename
        return self.filename

    def is_inline(self):
        """Check if this attachment is inline (e.g., embedded image)."""
        return self.get_content_disposition() == "inline"

    def __repr__(self):
        return (
            f"<SweegoLazyAttachment: {self.filename} "
            f"({self.get_content_type()}, {self.size} bytes, "
            f"fetched={self._fetched})>"
        )


def construct_sweego_lazy_attachment(
    attachment_data,
    api_url,
    api_key,
    client_uuid,
):
    """
    Construct a lazy attachment from Sweego webhook attachment metadata.

    Args:
        attachment_data: Dict with keys 'uuid', 'name', 'content_type', 'size'
        api_url: Base URL for Sweego API (e.g., 'https://api.sweego.io')
        api_key: API key for authentication
        client_uuid: Sweego client UUID

    Returns:
        SweegoLazyAttachment instance
    """
    return SweegoLazyAttachment(
        uuid=attachment_data["uuid"],
        filename=attachment_data.get("name", "attachment"),
        content_type=attachment_data.get("content_type", "application/octet-stream"),
        size=attachment_data.get("size", 0),
        api_url=api_url,
        api_key=api_key,
        client_uuid=client_uuid,
        content_id=attachment_data.get("content_id"),  # For inline images
    )
