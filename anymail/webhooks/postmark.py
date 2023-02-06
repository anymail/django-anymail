import json

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
            if esp_event["SuppressSending"]:
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
        if esp_event.get("RecordType", "Inbound") != "Inbound":
            raise AnymailConfigurationError(
                "You seem to have set Postmark's *%s* webhook "
                "to Anymail's Postmark *inbound* webhook URL." % esp_event["RecordType"]
            )

        attachments = [
            AnymailInboundMessage.construct_attachment(
                content_type=attachment["ContentType"],
                content=attachment["Content"],
                base64=True,
                filename=attachment.get("Name", "") or None,
                content_id=attachment.get("ContentID", "") or None,
            )
            for attachment in esp_event.get("Attachments", [])
        ]

        message = AnymailInboundMessage.construct(
            from_email=self._address(esp_event.get("FromFull")),
            to=", ".join([self._address(to) for to in esp_event.get("ToFull", [])]),
            cc=", ".join([self._address(cc) for cc in esp_event.get("CcFull", [])]),
            # bcc? Postmark specs this for inbound events,
            # but it's unclear how it could occur
            subject=esp_event.get("Subject", ""),
            headers=[
                (header["Name"], header["Value"])
                for header in esp_event.get("Headers", [])
            ],
            text=esp_event.get("TextBody", ""),
            html=esp_event.get("HtmlBody", ""),
            attachments=attachments,
        )

        # Postmark strips these headers and provides them as separate event fields:
        if "Date" in esp_event and "Date" not in message:
            message["Date"] = esp_event["Date"]
        if "ReplyTo" in esp_event and "Reply-To" not in message:
            message["Reply-To"] = esp_event["ReplyTo"]

        # Postmark doesn't have a separate envelope-sender field, but it can
        # be extracted from the Received-SPF header that Postmark will have added.
        # (More than one Received-SPF? someone's up to something weird?)
        if len(message.get_all("Received-SPF", [])) == 1:
            received_spf = message["Received-SPF"].lower()
            if received_spf.startswith(  # not fail/softfail
                "pass"
            ) or received_spf.startswith("neutral"):
                message.envelope_sender = message.get_param(
                    "envelope-from", None, header="Received-SPF"
                )

        message.envelope_recipient = esp_event.get("OriginalRecipient", None)
        message.stripped_text = esp_event.get("StrippedTextReply", None)

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

    @staticmethod
    def _address(full):
        """
        Return a formatted email address
        from a Postmark inbound {From,To,Cc}Full dict
        """
        if full is None:
            return ""
        return str(
            EmailAddress(
                display_name=full.get("Name", ""),
                addr_spec=full.get("Email", ""),
            )
        )
