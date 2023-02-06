import json
from datetime import datetime, timezone

from ..inbound import AnymailInboundMessage
from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from .base import AnymailBaseWebhookView


class MailjetTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for Mailjet delivery and engagement tracking webhooks"""

    esp_name = "Mailjet"
    signal = tracking

    def parse_events(self, request):
        esp_events = json.loads(request.body.decode("utf-8"))
        # Mailjet webhook docs say the payload is "a JSON array of event objects,"
        # but that's not true if "group events" isn't enabled in webhook config...
        try:
            esp_events[0]  # is this really an array of events?
        except IndexError:
            pass  # yep (and it's empty?!)
        except KeyError:
            esp_events = [esp_events]  # nope, it's a single, bare event
        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    # https://dev.mailjet.com/guides/#events
    event_types = {
        # Map Mailjet event: Anymail normalized type
        "sent": EventType.DELIVERED,  # accepted by receiving MTA
        "open": EventType.OPENED,
        "click": EventType.CLICKED,
        "bounce": EventType.BOUNCED,
        "blocked": EventType.REJECTED,
        "spam": EventType.COMPLAINED,
        "unsub": EventType.UNSUBSCRIBED,
    }

    reject_reasons = {
        # Map Mailjet error strings to Anymail normalized reject_reason
        # error_related_to: recipient
        "user unknown": RejectReason.BOUNCED,
        "mailbox inactive": RejectReason.BOUNCED,
        "quota exceeded": RejectReason.BOUNCED,
        "blacklisted": RejectReason.BLOCKED,  # might also be previous unsubscribe
        "spam reporter": RejectReason.SPAM,
        # error_related_to: domain
        "invalid domain": RejectReason.BOUNCED,
        "no mail host": RejectReason.BOUNCED,
        "relay/access denied": RejectReason.BOUNCED,
        "greylisted": RejectReason.OTHER,  # see special handling below
        "typofix": RejectReason.INVALID,
        # error_related_to: spam
        #   (all Mailjet policy/filtering; see above for spam complaints)
        "sender blocked": RejectReason.BLOCKED,
        "content blocked": RejectReason.BLOCKED,
        "policy issue": RejectReason.BLOCKED,
        # error_related_to: mailjet
        "preblocked": RejectReason.BLOCKED,
        "duplicate in campaign": RejectReason.OTHER,
    }

    def esp_to_anymail_event(self, esp_event):
        event_type = self.event_types.get(esp_event["event"], EventType.UNKNOWN)
        if esp_event.get("error", None) == "greylisted" and not esp_event.get(
            "hard_bounce", False
        ):
            # "This is a temporary error due to possible unrecognised senders.
            # Delivery will be re-attempted."
            event_type = EventType.DEFERRED

        try:
            timestamp = datetime.fromtimestamp(esp_event["time"], tz=timezone.utc)
        except (KeyError, ValueError):
            timestamp = None

        try:
            # convert bigint MessageID to str to match backend AnymailRecipientStatus
            message_id = str(esp_event["MessageID"])
        except (KeyError, TypeError):
            message_id = None

        if "error" in esp_event:
            reject_reason = self.reject_reasons.get(
                esp_event["error"], RejectReason.OTHER
            )
        else:
            reject_reason = None

        tag = esp_event.get("customcampaign", None)
        tags = [tag] if tag else []

        try:
            metadata = json.loads(esp_event["Payload"])
        except (KeyError, ValueError):
            metadata = {}

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=None,
            recipient=esp_event.get("email", None),
            reject_reason=reject_reason,
            mta_response=esp_event.get("smtp_reply", None),
            tags=tags,
            metadata=metadata,
            click_url=esp_event.get("url", None),
            user_agent=esp_event.get("agent", None),
            esp_event=esp_event,
        )


class MailjetInboundWebhookView(AnymailBaseWebhookView):
    """Handler for Mailjet inbound (parse API) webhook"""

    esp_name = "Mailjet"
    signal = inbound

    def parse_events(self, request):
        esp_event = json.loads(request.body.decode("utf-8"))
        return [self.esp_to_anymail_event(esp_event)]

    def esp_to_anymail_event(self, esp_event):
        # You could _almost_ reconstruct the raw mime message from Mailjet's Headers
        # and Parts fields, but it's not clear which multipart boundary to use on each
        # individual Part. Although each Part's Content-Type header still has the
        # multipart boundary, not knowing the parent part means typical nested multipart
        # structures can't be reliably recovered from the data Mailjet provides.
        # Just use our standardized multipart inbound constructor.

        headers = self._flatten_mailjet_headers(esp_event.get("Headers", {}))
        attachments = [
            self._construct_mailjet_attachment(part, esp_event)
            for part in esp_event.get("Parts", [])
            # if ContentRef is Attachment<N> or InlineAttachment<N>:
            if "Attachment" in part.get("ContentRef", "")
        ]
        message = AnymailInboundMessage.construct(
            headers=headers,
            text=esp_event.get("Text-part", None),
            html=esp_event.get("Html-part", None),
            attachments=attachments,
        )

        message.envelope_sender = esp_event.get("Sender", None)
        message.envelope_recipient = esp_event.get("Recipient", None)

        # Mailjet doesn't provide a spam boolean; you'll have to interpret spam_score
        message.spam_detected = None
        try:
            message.spam_score = float(esp_event["SpamAssassinScore"])
        except (KeyError, TypeError, ValueError):
            pass

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            # Mailjet doesn't provide inbound event timestamp
            #   (esp_event["Date"] is time sent):
            timestamp=None,
            # Mailjet doesn't provide an idempotent inbound event id:
            event_id=None,
            esp_event=esp_event,
            message=message,
        )

    @staticmethod
    def _flatten_mailjet_headers(headers):
        """
        Convert Mailjet's dict-of-strings-and/or-lists header format
        to our list-of-name-value-pairs

        {'name1': 'value', 'name2': ['value1', 'value2']}
          --> [('name1', 'value'), ('name2', 'value1'), ('name2', 'value2')]
        """
        result = []
        for name, values in headers.items():
            if isinstance(values, list):
                # Mailjet groups repeated headers together as a list of values
                for value in values:
                    result.append((name, value))
            else:
                # single-valued (non-list) header
                result.append((name, values))
        return result

    def _construct_mailjet_attachment(self, part, esp_event):
        # Mailjet includes unparsed attachment headers in each part; it's easiest to
        # temporarily attach them to a MIMEPart for parsing. (We could just turn this
        # into the attachment, but we want to use the payload handling from
        # AnymailInboundMessage.construct_attachment later.)

        # temporary container for parsed attachment headers:
        part_headers = AnymailInboundMessage()
        for name, value in self._flatten_mailjet_headers(part.get("Headers", {})):
            part_headers.add_header(name, value)

        # Mailjet *always* base64-encodes attachments
        content_base64 = esp_event[part["ContentRef"]]

        return AnymailInboundMessage.construct_attachment(
            content_type=part_headers.get_content_type(),
            content=content_base64,
            base64=True,
            filename=part_headers.get_filename(None),
            content_id=part_headers.get("Content-ID", "") or None,
        )
