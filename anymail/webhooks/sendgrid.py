import json
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as default_policy


from .base import AnymailBaseWebhookView
from ..inbound import AnymailInboundMessage
from ..signals import AnymailInboundEvent, AnymailTrackingEvent, EventType, RejectReason, inbound, tracking


class SendGridTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for SendGrid delivery and engagement tracking webhooks"""

    esp_name = "SendGrid"
    signal = tracking

    def parse_events(self, request):
        esp_events = json.loads(request.body.decode('utf-8'))
        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    event_types = {
        # Map SendGrid event: Anymail normalized type
        'bounce': EventType.BOUNCED,
        'deferred': EventType.DEFERRED,
        'delivered': EventType.DELIVERED,
        'dropped': EventType.REJECTED,
        'processed': EventType.QUEUED,
        'click': EventType.CLICKED,
        'open': EventType.OPENED,
        'spamreport': EventType.COMPLAINED,
        'unsubscribe': EventType.UNSUBSCRIBED,
        'group_unsubscribe': EventType.UNSUBSCRIBED,
        'group_resubscribe': EventType.SUBSCRIBED,
    }

    reject_reasons = {
        # Map SendGrid reason/type strings (lowercased) to Anymail normalized reject_reason
        'invalid': RejectReason.INVALID,
        'unsubscribed address': RejectReason.UNSUBSCRIBED,
        'bounce': RejectReason.BOUNCED,
        'blocked': RejectReason.BLOCKED,
        'expired': RejectReason.TIMED_OUT,
    }

    def esp_to_anymail_event(self, esp_event):
        event_type = self.event_types.get(esp_event['event'], EventType.UNKNOWN)
        try:
            timestamp = datetime.fromtimestamp(esp_event['timestamp'], tz=timezone.utc)
        except (KeyError, ValueError):
            timestamp = None

        if esp_event['event'] == 'dropped':
            mta_response = None  # dropped at ESP before even getting to MTA
            reason = esp_event.get('type', esp_event.get('reason', ''))  # cause could be in 'type' or 'reason'
            reject_reason = self.reject_reasons.get(reason.lower(), RejectReason.OTHER)
        else:
            # MTA response is in 'response' for delivered; 'reason' for bounce
            mta_response = esp_event.get('response', esp_event.get('reason', None))
            reject_reason = None

        # SendGrid merges metadata ('unique_args') with the event.
        # We can (sort of) split metadata back out by filtering known
        # SendGrid event params, though this can miss metadata keys
        # that duplicate SendGrid params, and can accidentally include
        # non-metadata keys if SendGrid modifies their event records.
        metadata_keys = set(esp_event.keys()) - self.sendgrid_event_keys
        if len(metadata_keys) > 0:
            metadata = {key: esp_event[key] for key in metadata_keys}
        else:
            metadata = {}

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=esp_event.get('anymail_id', esp_event.get('smtp-id')),  # backwards compatibility
            event_id=esp_event.get('sg_event_id', None),
            recipient=esp_event.get('email', None),
            reject_reason=reject_reason,
            mta_response=mta_response,
            tags=esp_event.get('category', []),
            metadata=metadata,
            click_url=esp_event.get('url', None),
            user_agent=esp_event.get('useragent', None),
            esp_event=esp_event,
        )

    # Known keys in SendGrid events (used to recover metadata above)
    sendgrid_event_keys = {
        'anymail_id',
        'asm_group_id',
        'attempt',  # MTA deferred count
        'category',
        'cert_err',
        'email',
        'event',
        'ip',
        'marketing_campaign_id',
        'marketing_campaign_name',
        'newsletter',  # ???
        'nlvx_campaign_id',
        'nlvx_campaign_split_id',
        'nlvx_user_id',
        'pool',
        'post_type',
        'reason',  # MTA bounce/drop reason; SendGrid suppression reason
        'response',  # MTA deferred/delivered message
        'send_at',
        'sg_event_id',
        'sg_message_id',
        'smtp-id',
        'status',  # SMTP status code
        'timestamp',
        'tls',
        'type',  # suppression reject reason ("bounce", "blocked", "expired")
        'url',  # click tracking
        'url_offset',  # click tracking
        'useragent',  # click/open tracking
    }


class SendGridInboundWebhookView(AnymailBaseWebhookView):
    """Handler for SendGrid inbound webhook"""

    esp_name = "SendGrid"
    signal = inbound

    def parse_events(self, request):
        return [self.esp_to_anymail_event(request)]

    def esp_to_anymail_event(self, request):
        # Inbound uses the entire Django request as esp_event, because we need POST and FILES.
        # Note that request.POST is case-sensitive (unlike email.message.Message headers).
        esp_event = request
        # Must access body before any POST fields, or it won't be available if we need
        # it later (see text_charset and html_charset handling below).
        _ensure_body_is_available_later = request.body  # noqa: F841
        if 'headers' in request.POST:
            # Default (not "Send Raw") inbound fields
            message = self.message_from_sendgrid_parsed(esp_event)
        elif 'email' in request.POST:
            # "Send Raw" full MIME
            message = AnymailInboundMessage.parse_raw_mime(request.POST['email'])
        else:
            raise KeyError("Invalid SendGrid inbound event data (missing both 'headers' and 'email' fields)")

        try:
            envelope = json.loads(request.POST['envelope'])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            message.envelope_sender = envelope['from']
            message.envelope_recipient = envelope['to'][0]

        message.spam_detected = None  # no simple boolean field; would need to parse the spam_report
        try:
            message.spam_score = float(request.POST['spam_score'])
        except (KeyError, TypeError, ValueError):
            pass

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=None,  # SendGrid doesn't provide an inbound event timestamp
            event_id=None,  # SendGrid doesn't provide an idempotent inbound message event id
            esp_event=esp_event,
            message=message,
        )

    def message_from_sendgrid_parsed(self, request):
        """Construct a Message from SendGrid's "default" (non-raw) fields"""

        try:
            charsets = json.loads(request.POST['charsets'])
        except (KeyError, ValueError):
            charsets = {}

        try:
            attachment_info = json.loads(request.POST['attachment-info'])
        except (KeyError, ValueError):
            attachments = None
        else:
            # Load attachments from posted files
            attachments = []
            for attachment_id in sorted(attachment_info.keys()):
                try:
                    file = request.FILES[attachment_id]
                except KeyError:
                    # Django's multipart/form-data handling drops FILES with certain
                    # filenames (for security) or with empty filenames (Django ticket 15879).
                    # (To avoid this problem, enable SendGrid's "raw, full MIME" inbound option.)
                    pass
                else:
                    # (This deliberately ignores attachment_info[attachment_id]["filename"],
                    # which has not passed through Django's filename sanitization.)
                    content_id = attachment_info[attachment_id].get("content-id")
                    attachment = AnymailInboundMessage.construct_attachment_from_uploaded_file(
                        file, content_id=content_id)
                    attachments.append(attachment)

        default_charset = request.POST.encoding.lower()  # (probably utf-8)
        text = request.POST.get('text')
        text_charset = charsets.get('text', default_charset).lower()
        html = request.POST.get('html')
        html_charset = charsets.get('html', default_charset).lower()
        if (text and text_charset != default_charset) or (html and html_charset != default_charset):
            # Django has parsed text and/or html fields using the wrong charset.
            # We need to re-parse the raw form data and decode each field separately,
            # using the indicated charsets. The email package parses multipart/form-data
            # retaining bytes content. (In theory, we could instead just change
            # request.encoding and access the POST fields again, per Django docs,
            # but that seems to be have bugs around the cached request._files.)
            raw_data = b"".join([
                b"Content-Type: ", request.META['CONTENT_TYPE'].encode('ascii'),
                b"\r\n\r\n",
                request.body
            ])
            parsed_parts = BytesParser(policy=default_policy).parsebytes(raw_data).get_payload()
            for part in parsed_parts:
                name = part.get_param('name', header='content-disposition')
                if name == 'text':
                    text = part.get_payload(decode=True).decode(text_charset)
                elif name == 'html':
                    html = part.get_payload(decode=True).decode(html_charset)
                # (subject, from, to, etc. are parsed from raw headers field,
                # so no need to worry about their separate POST field charsets)

        return AnymailInboundMessage.construct(
            raw_headers=request.POST.get('headers', ""),  # includes From, To, Cc, Subject, etc.
            text=text, html=html, attachments=attachments)
