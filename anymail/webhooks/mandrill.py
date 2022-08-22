import json
from datetime import datetime, timezone

import hashlib
import hmac
from base64 import b64encode
from django.utils.crypto import constant_time_compare

from .base import AnymailBaseWebhookView, AnymailCoreWebhookView
from ..exceptions import AnymailWebhookValidationFailure
from ..inbound import AnymailInboundMessage
from ..signals import inbound, tracking, AnymailInboundEvent, AnymailTrackingEvent, EventType
from ..utils import get_anymail_setting, getfirst, get_request_uri


class MandrillSignatureMixin(AnymailCoreWebhookView):
    """Validates Mandrill webhook signature"""

    # These can be set from kwargs in View.as_view, or pulled from settings in init:
    webhook_key = None  # required
    webhook_url = None  # optional; defaults to actual url used

    def __init__(self, **kwargs):
        esp_name = self.esp_name
        # webhook_key is required for POST, but not for HEAD when Mandrill validates webhook url.
        # Defer "missing setting" error until we actually try to use it in the POST...
        webhook_key = get_anymail_setting('webhook_key', esp_name=esp_name, default=None,
                                          kwargs=kwargs, allow_bare=True)
        if webhook_key is not None:
            self.webhook_key = webhook_key.encode('ascii')  # hmac.new requires bytes key
        self.webhook_url = get_anymail_setting('webhook_url', esp_name=esp_name, default=None,
                                               kwargs=kwargs, allow_bare=True)
        super().__init__(**kwargs)

    def validate_request(self, request):
        if self.webhook_key is None:
            # issue deferred "missing setting" error (re-call get-setting without a default)
            get_anymail_setting('webhook_key', esp_name=self.esp_name, allow_bare=True)

        try:
            signature = request.META["HTTP_X_MANDRILL_SIGNATURE"]
        except KeyError:
            raise AnymailWebhookValidationFailure("X-Mandrill-Signature header missing from webhook POST") from None

        # Mandrill signs the exact URL (including basic auth, if used) plus the sorted POST params:
        url = self.webhook_url or get_request_uri(request)
        params = request.POST.dict()
        signed_data = url
        for key in sorted(params.keys()):
            signed_data += key + params[key]

        expected_signature = b64encode(hmac.new(key=self.webhook_key, msg=signed_data.encode('utf-8'),
                                                digestmod=hashlib.sha1).digest())
        if not constant_time_compare(signature, expected_signature):
            raise AnymailWebhookValidationFailure(
                "Mandrill webhook called with incorrect signature (for url %r)" % url)


class MandrillCombinedWebhookView(MandrillSignatureMixin, AnymailBaseWebhookView):
    """Unified view class for Mandrill tracking and inbound webhooks"""

    esp_name = "Mandrill"

    warn_if_no_basic_auth = False  # because we validate against signature
    signal = None  # set in esp_to_anymail_event

    def parse_events(self, request):
        esp_events = json.loads(request.POST['mandrill_events'])
        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    def esp_to_anymail_event(self, esp_event):
        """Route events to the inbound or tracking handler"""
        esp_type = getfirst(esp_event, ['event', 'type'], 'unknown')

        if esp_type == 'inbound':
            assert self.signal is not tracking  # Mandrill should never mix event types in the same batch
            self.signal = inbound
            return self.mandrill_inbound_to_anymail_event(esp_event)
        else:
            assert self.signal is not inbound  # Mandrill should never mix event types in the same batch
            self.signal = tracking
            return self.mandrill_tracking_to_anymail_event(esp_event)

    #
    #  Tracking events
    #

    event_types = {
        # Message events:
        'send': EventType.SENT,
        'deferral': EventType.DEFERRED,
        'hard_bounce': EventType.BOUNCED,
        'soft_bounce': EventType.BOUNCED,
        'open': EventType.OPENED,
        'click': EventType.CLICKED,
        'spam': EventType.COMPLAINED,
        'unsub': EventType.UNSUBSCRIBED,
        'reject': EventType.REJECTED,
        # Sync events (we don't really normalize these well):
        'whitelist': EventType.UNKNOWN,
        'blacklist': EventType.UNKNOWN,
        # Inbound events:
        'inbound': EventType.INBOUND,
    }

    def mandrill_tracking_to_anymail_event(self, esp_event):
        esp_type = getfirst(esp_event, ['event', 'type'], None)
        event_type = self.event_types.get(esp_type, EventType.UNKNOWN)

        try:
            timestamp = datetime.fromtimestamp(esp_event['ts'], tz=timezone.utc)
        except (KeyError, ValueError):
            timestamp = None

        try:
            recipient = esp_event['msg']['email']
        except KeyError:
            try:
                recipient = esp_event['reject']['email']  # sync events
            except KeyError:
                recipient = None

        try:
            mta_response = esp_event['msg']['diag']
        except KeyError:
            mta_response = None

        try:
            description = getfirst(esp_event['reject'], ['detail', 'reason'])
        except KeyError:
            description = None

        try:
            metadata = esp_event['msg']['metadata']
        except KeyError:
            metadata = {}

        try:
            tags = esp_event['msg']['tags']
        except KeyError:
            tags = []

        return AnymailTrackingEvent(
            click_url=esp_event.get('url', None),
            description=description,
            esp_event=esp_event,
            event_type=event_type,
            message_id=esp_event.get('_id', None),
            metadata=metadata,
            mta_response=mta_response,
            recipient=recipient,
            reject_reason=None,  # probably map esp_event['msg']['bounce_description'], but insufficient docs
            tags=tags,
            timestamp=timestamp,
            user_agent=esp_event.get('user_agent', None),
        )

    #
    # Inbound events
    #

    def mandrill_inbound_to_anymail_event(self, esp_event):
        # It's easier (and more accurate) to just work from the original raw mime message
        message = AnymailInboundMessage.parse_raw_mime(esp_event['msg']['raw_msg'])
        message.envelope_sender = None  # (Mandrill's 'sender' field only applies to outbound messages)
        message.envelope_recipient = esp_event['msg'].get('email', None)

        message.spam_detected = None  # no simple boolean field; would need to parse the spam_report
        message.spam_score = esp_event['msg'].get('spam_report', {}).get('score', None)

        try:
            timestamp = datetime.fromtimestamp(esp_event['ts'], tz=timezone.utc)
        except (KeyError, ValueError):
            timestamp = None

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=timestamp,
            event_id=None,  # Mandrill doesn't provide an idempotent inbound message event id
            esp_event=esp_event,
            message=message,
        )


# Backwards-compatibility: earlier Anymail versions had only MandrillTrackingWebhookView:
MandrillTrackingWebhookView = MandrillCombinedWebhookView
