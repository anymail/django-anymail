import json
from datetime import datetime

import hashlib
import hmac
from base64 import b64encode
from django.utils.crypto import constant_time_compare
from django.utils.timezone import utc

from .base import AnymailBaseWebhookView
from ..exceptions import AnymailWebhookValidationFailure, AnymailConfigurationError
from ..signals import tracking, AnymailTrackingEvent, EventType
from ..utils import get_anymail_setting, getfirst


class MandrillSignatureMixin(object):
    """Validates Mandrill webhook signature"""

    # These can be set from kwargs in View.as_view, or pulled from settings in init:
    webhook_key = None  # required
    webhook_url = None  # optional; defaults to actual url used

    def __init__(self, **kwargs):
        # noinspection PyUnresolvedReferences
        esp_name = self.esp_name
        webhook_key = get_anymail_setting('webhook_key', esp_name=esp_name,
                                          kwargs=kwargs, allow_bare=True)
        self.webhook_key = webhook_key.encode('ascii')  # hmac.new requires bytes key in python 3
        self.webhook_url = get_anymail_setting('webhook_url', esp_name=esp_name, default=None,
                                               kwargs=kwargs, allow_bare=True)
        # noinspection PyArgumentList
        super(MandrillSignatureMixin, self).__init__(**kwargs)

    def validate_request(self, request):
        try:
            signature = request.META["HTTP_X_MANDRILL_SIGNATURE"]
        except KeyError:
            raise AnymailWebhookValidationFailure("X-Mandrill-Signature header missing from webhook POST")

        # Mandrill signs the exact URL plus the sorted POST params:
        signed_data = self.webhook_url or request.build_absolute_uri()
        params = request.POST.dict()
        for key in sorted(params.keys()):
            signed_data += key + params[key]

        expected_signature = b64encode(hmac.new(key=self.webhook_key, msg=signed_data.encode('utf-8'),
                                                digestmod=hashlib.sha1).digest())
        if not constant_time_compare(signature, expected_signature):
            raise AnymailWebhookValidationFailure("Mandrill webhook called with incorrect signature")


class MandrillBaseWebhookView(MandrillSignatureMixin, AnymailBaseWebhookView):
    """Base view class for Mandrill webhooks"""

    warn_if_no_basic_auth = False  # because we validate against signature

    def parse_events(self, request):
        esp_events = json.loads(request.POST['mandrill_events'])
        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    def esp_to_anymail_event(self, esp_event):
        raise NotImplementedError()


class MandrillTrackingWebhookView(MandrillBaseWebhookView):

    signal = tracking

    event_types = {
        # Message events:
        'send': EventType.SENT,
        'deferral': EventType.DEFERRED,
        'hard_bounce': EventType.BOUNCED,
        'soft_bounce': EventType.DEFERRED,
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

    def esp_to_anymail_event(self, esp_event):
        esp_type = getfirst(esp_event, ['event', 'type'], None)
        event_type = self.event_types.get(esp_type, EventType.UNKNOWN)
        if event_type == EventType.INBOUND:
            raise AnymailConfigurationError(
                "You seem to have set Mandrill's *inbound* webhook URL "
                "to Anymail's Mandrill *tracking* webhook URL.")

        try:
            timestamp = datetime.fromtimestamp(esp_event['ts'], tz=utc)
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
            metadata = None

        try:
            tags = esp_event['msg']['tags']
        except KeyError:
            tags = None

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
