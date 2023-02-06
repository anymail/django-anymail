from django.dispatch import Signal

#: Outbound message, before sending
#: provides args: message, esp_name
pre_send = Signal()

#: Outbound message, after sending
#: provides args: message, status, esp_name
post_send = Signal()

#: Delivery and tracking events for sent messages
#: provides args: event, esp_name
tracking = Signal()

#: Event for receiving inbound messages
#: provides args: event, esp_name
inbound = Signal()


class AnymailEvent:
    """Base class for normalized Anymail webhook events"""

    def __init__(
        self, event_type, timestamp=None, event_id=None, esp_event=None, **kwargs
    ):
        #: normalized to an EventType str
        self.event_type = event_type
        #: normalized to an aware datetime
        self.timestamp = timestamp
        #: opaque str
        self.event_id = event_id
        #: raw event fields (e.g., parsed JSON dict or POST data QueryDict)
        self.esp_event = esp_event


class AnymailTrackingEvent(AnymailEvent):
    """Normalized delivery and tracking event for sent messages"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.click_url = kwargs.pop("click_url", None)  #: str
        #: str, usually human-readable, not normalized
        self.description = kwargs.pop("description", None)
        self.message_id = kwargs.pop("message_id", None)  #: str, format may vary
        self.metadata = kwargs.pop("metadata", {})  #: dict
        #: str, may include SMTP codes, not normalized
        self.mta_response = kwargs.pop("mta_response", None)
        #: str email address (just the email portion; no name)
        self.recipient = kwargs.pop("recipient", None)
        #: normalized to a RejectReason str
        self.reject_reason = kwargs.pop("reject_reason", None)
        self.tags = kwargs.pop("tags", [])  #: list of str
        self.user_agent = kwargs.pop("user_agent", None)  #: str


class AnymailInboundEvent(AnymailEvent):
    """Normalized inbound message event"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        #: anymail.inbound.AnymailInboundMessage
        self.message = kwargs.pop("message", None)


class EventType:
    """Constants for normalized Anymail event types"""

    # Delivery (and non-delivery) event types
    # (these match message.ANYMAIL_STATUSES where appropriate)

    #: the ESP has accepted the message and will try to send it (possibly later)
    QUEUED = "queued"

    #: the ESP has sent the message (though it may or may not get delivered)
    SENT = "sent"

    #: the ESP refused to send the message
    #: (e.g., suppression list, policy, invalid email)
    REJECTED = "rejected"

    #: the ESP was unable to send the message (e.g., template rendering error)
    FAILED = "failed"

    #: rejected or blocked by receiving MTA
    BOUNCED = "bounced"

    #: delayed by receiving MTA; should be followed by a later BOUNCED or DELIVERED
    DEFERRED = "deferred"

    #: accepted by receiving MTA
    DELIVERED = "delivered"

    #: a bot replied
    AUTORESPONDED = "autoresponded"

    # Tracking event types

    #: open tracking
    OPENED = "opened"

    #: click tracking
    CLICKED = "clicked"

    #: recipient reported as spam (e.g., through feedback loop)
    COMPLAINED = "complained"

    #: recipient attempted to unsubscribe
    UNSUBSCRIBED = "unsubscribed"

    #: signed up for mailing list through ESP-hosted form
    SUBSCRIBED = "subscribed"

    # Inbound event types

    #: received message
    INBOUND = "inbound"

    #: (ESP notification of) error receiving message
    INBOUND_FAILED = "inbound_failed"

    # Other event types

    #: all other ESP events
    UNKNOWN = "unknown"


class RejectReason:
    """Constants for normalized Anymail reject/drop reasons"""

    #: bad address format
    INVALID = "invalid"

    #: (previous) bounce from recipient
    BOUNCED = "bounced"

    #: (previous) repeated failed delivery attempts
    TIMED_OUT = "timed_out"

    #: ESP policy suppression
    BLOCKED = "blocked"

    #: (previous) spam complaint from recipient
    SPAM = "spam"

    #: (previous) unsubscribe request from recipient
    UNSUBSCRIBED = "unsubscribed"

    #: all other ESP reject reasons
    OTHER = "other"
