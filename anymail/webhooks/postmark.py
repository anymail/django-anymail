import json
from email.utils import unquote

from django.utils.dateparse import parse_datetime

from ..exceptions import AnymailConfigurationError
from ..inbound import AnymailInboundMessage
from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from ..utils import EmailAddress, getfirst
from .base import AnymailBaseWebhookView


class PostmarkBaseWebhookView(AnymailBaseWebhookView):
    """Base view class for Postmark webhooks"""

    esp_name = "Postmark"

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        return [self.esp_to_anymail_event(esp_event)]

    def esp_to_anymail_event(self, esp_event):
        raise NotImplementedError()


class PostmarkTrackingWebhookView(PostmarkBaseWebhookView):
    """Handler for Postmark delivery and engagement tracking webhooks"""

    signal = tracking

    event_record_types = {
        # Map Postmark event RecordType --> Anymail normalized event type
        "Bounce": EventType.BOUNCED,  # but check Type field for further info (below)
        "Click": EventType.CLICKED,
        "Delivery": EventType.DELIVERED,
        "Open": EventType.OPENED,
        "SpamComplaint": EventType.COMPLAINED,
        "SubscriptionChange": EventType.UNSUBSCRIBED,
        "Inbound": EventType.INBOUND,  # future, probably
    }

    event_types = {
        # Map Postmark bounce/spam event Type
        #   --> Anymail normalized (event type, reject reason)
        "HardBounce": (EventType.BOUNCED, RejectReason.BOUNCED),
        "Transient": (EventType.DEFERRED, None),
        "Unsubscribe": (EventType.UNSUBSCRIBED, RejectReason.UNSUBSCRIBED),
        "Subscribe": (EventType.SUBSCRIBED, None),
        "AutoResponder": (EventType.AUTORESPONDED, None),
        "AddressChange": (EventType.AUTORESPONDED, None),
        "DnsError": (EventType.DEFERRED, None),  # "temporary DNS error"
        "SpamNotification": (EventType.COMPLAINED, RejectReason.SPAM),
        # Receiving MTA is testing Postmark:
        "OpenRelayTest": (EventType.DEFERRED, None),
        "Unknown": (EventType.UNKNOWN, None),
        # might also receive HardBounce later:
        "SoftBounce": (EventType.BOUNCED, RejectReason.BOUNCED),
        "VirusNotification": (EventType.BOUNCED, RejectReason.OTHER),
        "ChallengeVerification": (EventType.AUTORESPONDED, None),
        "BadEmailAddress": (EventType.REJECTED, RejectReason.INVALID),
        "SpamComplaint": (EventType.COMPLAINED, RejectReason.SPAM),
        "ManuallyDeactivated": (EventType.REJECTED, RejectReason.BLOCKED),
        "Unconfirmed": (EventType.REJECTED, None),
        "Blocked": (EventType.REJECTED, RejectReason.BLOCKED),
        # could occur if user also using Postmark SMTP directly:
        "SMTPApiError": (EventType.FAILED, None),
        "InboundError": (EventType.INBOUND_FAILED, None),
        "DMARCPolicy": (EventType.REJECTED, RejectReason.BLOCKED),
        "TemplateRenderingFailed": (EventType.FAILED, None),
        "ManualSuppression": (EventType.UNSUBSCRIBED, RejectReason.UNSUBSCRIBED),
    }

    def esp_to_anymail_event(self, esp_event):
        reject_reason = None
        try:
            esp_record_type = esp_event["RecordType"]
        except KeyError:
            if "FromFull" in esp_event:
                # This is an inbound event
                event_type = EventType.INBOUND
            else:
                event_type = EventType.UNKNOWN
        else:
            event_type = self.event_record_types.get(esp_record_type, EventType.UNKNOWN)

        if event_type == EventType.INBOUND:
            raise AnymailConfigurationError(
                "You seem to have set Postmark's *inbound* webhook "
                "to Anymail's Postmark *tracking* webhook URL."
            )

        if event_type in (EventType.BOUNCED, EventType.COMPLAINED):
            # additional info is in the Type field
            try:
                event_type, reject_reason = self.event_types[esp_event["Type"]]
            except KeyError:
                pass
        if event_type == EventType.UNSUBSCRIBED:
            if esp_event.get("SuppressSending", True):
                # Postmark doesn't provide a way to distinguish between
                # explicit unsubscribes and bounces
                try:
                    event_type, reject_reason = self.event_types[
                        esp_event["SuppressionReason"]
                    ]
                except KeyError:
                    pass
            else:
                event_type, reject_reason = self.event_types["Subscribe"]

        # Email for bounce; Recipient for open:
        recipient = getfirst(esp_event, ["Email", "Recipient"], None)

        try:
            timestr = getfirst(
                esp_event, ["DeliveredAt", "BouncedAt", "ReceivedAt", "ChangedAt"]
            )
        except KeyError:
            timestamp = None
        else:
            timestamp = parse_datetime(timestr)

        try:
            event_id = str(esp_event["ID"])  # only in bounce events
        except KeyError:
            event_id = None

        metadata = esp_event.get("Metadata", {})
        try:
            tags = [esp_event["Tag"]]
        except KeyError:
            tags = []

        return AnymailTrackingEvent(
            description=esp_event.get("Description", None),
            esp_event=esp_event,
            event_id=event_id,
            event_type=event_type,
            message_id=esp_event.get("MessageID", None),
            metadata=metadata,
            mta_response=esp_event.get("Details", None),
            recipient=recipient,
            reject_reason=reject_reason,
            tags=tags,
            timestamp=timestamp,
            user_agent=esp_event.get("UserAgent", None),
            click_url=esp_event.get("OriginalLink", None),
        )


class PostmarkInboundWebhookView(PostmarkBaseWebhookView):
    """Handler for Postmark inbound webhook"""

    signal = inbound

    def esp_to_anymail_event(self, esp_event):
        # Check correct webhook (inbound events don't have RecordType):
        esp_record_type = esp_event.get("RecordType", "Inbound")
        if esp_record_type != "Inbound":
            raise AnymailConfigurationError(
                f"You seem to have set Postmark's *{esp_record_type}* webhook"
                f" to Anymail's Postmark *inbound* webhook URL."
            )

        headers = esp_event.get("Headers", [])

        # Postmark inbound prepends "Return-Path" to Headers list
        # (but it doesn't appear in original message or RawEmail).
        # (A Return-Path anywhere else in the headers or RawEmail
        # can't be considered legitimate.)
        envelope_sender = None
        if len(headers) > 0 and headers[0]["Name"].lower() == "return-path":
            envelope_sender = unquote(headers[0]["Value"])  # remove <>
            headers = headers[1:]  # don't include in message construction

        if "RawEmail" in esp_event:
            message = AnymailInboundMessage.parse_raw_mime(esp_event["RawEmail"])
            # Postmark provides Bcc when delivered-to is not in To header,
            # but doesn't add it to the RawEmail.
            if esp_event.get("BccFull") and "Bcc" not in message:
                message["Bcc"] = self._addresses(esp_event["BccFull"])

        else:
            # RawEmail not included in payload; construct from parsed data.
            attachments = [
                AnymailInboundMessage.construct_attachment(
                    content_type=attachment["ContentType"],
                    # Real payloads have "Content", test payloads have "Data" (?!):
                    content=attachment.get("Content") or attachment["Data"],
                    base64=True,
                    filename=attachment.get("Name"),
                    content_id=attachment.get("ContentID"),
                )
                for attachment in esp_event.get("Attachments", [])
            ]
            message = AnymailInboundMessage.construct(
                from_email=self._address(esp_event.get("FromFull")),
                to=self._addresses(esp_event.get("ToFull")),
                cc=self._addresses(esp_event.get("CcFull")),
                bcc=self._addresses(esp_event.get("BccFull")),
                subject=esp_event.get("Subject", ""),
                headers=((header["Name"], header["Value"]) for header in headers),
                text=esp_event.get("TextBody", ""),
                html=esp_event.get("HtmlBody", ""),
                attachments=attachments,
            )
            # Postmark strips these headers and provides them as separate event fields:
            if esp_event.get("Date") and "Date" not in message:
                message["Date"] = esp_event["Date"]
            if esp_event.get("ReplyTo") and "Reply-To" not in message:
                message["Reply-To"] = esp_event["ReplyTo"]

        message.envelope_sender = envelope_sender
        message.envelope_recipient = esp_event.get("OriginalRecipient")
        message.stripped_text = esp_event.get("StrippedTextReply")

        message.spam_detected = message.get("X-Spam-Status", "No").lower() == "yes"
        try:
            message.spam_score = float(message["X-Spam-Score"])
        except (TypeError, ValueError):
            pass

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            # Postmark doesn't provide inbound event timestamp:
            timestamp=None,
            # Postmark uuid, different from Message-ID mime header:
            event_id=esp_event.get("MessageID", None),
            esp_event=esp_event,
            message=message,
        )

    @classmethod
    def _address(cls, full):
        """
        Return a formatted email address
        from a Postmark inbound {From,To,Cc,Bcc}Full dict
        """
        if full is None:
            return ""
        return str(
            EmailAddress(
                display_name=full.get("Name", ""),
                addr_spec=full.get("Email", ""),
            )
        )

    @classmethod
    def _addresses(cls, full_list):
        """
        Return a formatted email address list string
        from a Postmark inbound {To,Cc,Bcc}Full[] list of dicts
        """
        if full_list is None:
            return None
        return ", ".join(cls._address(addr) for addr in full_list)
