import json
from datetime import datetime

import hashlib
import hmac
from django.utils.crypto import constant_time_compare
from django.utils.timezone import utc

from .base import AnymailBaseWebhookView
from ..exceptions import AnymailWebhookValidationFailure
from ..signals import tracking, AnymailTrackingEvent, EventType, RejectReason
from ..utils import get_anymail_setting, combine


class MailgunBaseWebhookView(AnymailBaseWebhookView):
    """Base view class for Mailgun webhooks"""

    warn_if_no_basic_auth = False  # because we validate against signature

    api_key = None  # (Declaring class attr allows override by kwargs in View.as_view.)

    def __init__(self, **kwargs):
        api_key = get_anymail_setting('api_key', esp_name=self.esp_name,
                                      kwargs=kwargs, allow_bare=True)
        self.api_key = api_key.encode('ascii')  # hmac.new requires bytes key in python 3
        super(MailgunBaseWebhookView, self).__init__(**kwargs)

    def validate_request(self, request):
        super(MailgunBaseWebhookView, self).validate_request(request)  # first check basic auth if enabled
        try:
            token = request.POST['token']
            timestamp = request.POST['timestamp']
            signature = str(request.POST['signature'])  # force to same type as hexdigest() (for python2)
        except KeyError:
            raise AnymailWebhookValidationFailure("Mailgun webhook called without required security fields")
        expected_signature = hmac.new(key=self.api_key, msg='{}{}'.format(timestamp, token).encode('ascii'),
                                      digestmod=hashlib.sha256).hexdigest()
        if not constant_time_compare(signature, expected_signature):
            raise AnymailWebhookValidationFailure("Mailgun webhook called with incorrect signature")

    def parse_events(self, request):
        return [self.esp_to_anymail_event(request.POST)]

    def esp_to_anymail_event(self, esp_event):
        raise NotImplementedError()


class MailgunTrackingWebhookView(MailgunBaseWebhookView):
    """Handler for Mailgun delivery and engagement tracking webhooks"""

    signal = tracking

    event_types = {
        # Map Mailgun event: Anymail normalized type
        'delivered': EventType.DELIVERED,
        'dropped': EventType.REJECTED,
        'bounced': EventType.BOUNCED,
        'complained': EventType.COMPLAINED,
        'unsubscribed': EventType.UNSUBSCRIBED,
        'opened': EventType.OPENED,
        'clicked': EventType.CLICKED,
        # Mailgun does not send events corresponding to QUEUED or DEFERRED
    }

    reject_reasons = {
        # Map Mailgun (SMTP) error codes to Anymail normalized reject_reason.
        # By default, we will treat anything 400-599 as REJECT_BOUNCED
        # so only exceptions are listed here.
        499: RejectReason.TIMED_OUT,  # unable to connect to MX (also covers invalid recipients)
        # These 6xx codes appear to be Mailgun extensions to SMTP
        # (and don't seem to be documented anywhere):
        605: RejectReason.BOUNCED,  # previous bounce
        607: RejectReason.SPAM,  # previous spam complaint
    }

    def esp_to_anymail_event(self, esp_event):
        # esp_event is a Django QueryDict (from request.POST),
        # which has multi-valued fields, but is *not* case-insensitive

        event_type = self.event_types.get(esp_event['event'], EventType.UNKNOWN)
        timestamp = datetime.fromtimestamp(int(esp_event['timestamp']), tz=utc)
        # Message-Id is not documented for every event, but seems to always be included.
        # (It's sometimes spelled as 'message-id', lowercase, and missing the <angle-brackets>.)
        message_id = esp_event.get('Message-Id', esp_event.get('message-id', None))
        if message_id and not message_id.startswith('<'):
            message_id = "<{}>".format(message_id)

        description = esp_event.get('description', None)
        mta_response = esp_event.get('error', esp_event.get('notification', None))
        reject_reason = None
        try:
            mta_status = int(esp_event['code'])
        except (KeyError, TypeError):
            pass
        else:
            reject_reason = self.reject_reasons.get(
                mta_status,
                RejectReason.BOUNCED if 400 <= mta_status < 600
                else RejectReason.OTHER)

        # Mailgun merges metadata fields with the other event fields.
        # However, it also includes the original message headers,
        # which have the metadata separately as X-Mailgun-Variables.
        try:
            headers = json.loads(esp_event['message-headers'])
        except (KeyError, ):
            metadata = None
        else:
            variables = [value for [field, value] in headers
                         if field == 'X-Mailgun-Variables']
            if len(variables) >= 1:
                # Each X-Mailgun-Variables value is JSON. Parse and merge them all into single dict:
                metadata = combine(*[json.loads(value) for value in variables])
            else:
                metadata = None

        # tags are sometimes delivered as X-Mailgun-Tag fields, sometimes as tag
        tags = esp_event.getlist('tag', esp_event.getlist('X-Mailgun-Tag', None))

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=esp_event.get('token', None),
            recipient=esp_event.get('recipient', None),
            reject_reason=reject_reason,
            description=description,
            mta_response=mta_response,
            tags=tags,
            metadata=metadata,
            click_url=esp_event.get('url', None),
            user_agent=esp_event.get('user-agent', None),
            esp_event=esp_event,
        )
