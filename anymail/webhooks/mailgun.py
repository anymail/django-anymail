import hashlib
import hmac
import json
from datetime import datetime, timezone

from django.utils.crypto import constant_time_compare

from ..exceptions import (
    AnymailConfigurationError,
    AnymailInvalidAddress,
    AnymailWebhookValidationFailure,
)
from ..inbound import AnymailInboundMessage
from ..signals import (
    AnymailInboundEvent,
    AnymailTrackingEvent,
    EventType,
    RejectReason,
    inbound,
    tracking,
)
from ..utils import (
    UNSET,
    get_anymail_setting,
    merge_dicts_shallow,
    parse_single_address,
    querydict_getfirst,
)
from .base import AnymailBaseWebhookView


class MailgunBaseWebhookView(AnymailBaseWebhookView):
    """Base view class for Mailgun webhooks"""

    esp_name = "Mailgun"
    warn_if_no_basic_auth = False  # because we validate against signature

    # (Declaring class attr allows override by kwargs in View.as_view.)
    webhook_signing_key = None

    # The `api_key` attribute name is still allowed for compatibility
    # with earlier Anymail releases.
    api_key = None  # (Declaring class attr allows override by kwargs in View.as_view.)

    def __init__(self, **kwargs):
        # webhook_signing_key: falls back to api_key if webhook_signing_key not provided
        api_key = get_anymail_setting(
            "api_key",
            esp_name=self.esp_name,
            kwargs=kwargs,
            allow_bare=True,
            default=None,
        )
        webhook_signing_key = get_anymail_setting(
            "webhook_signing_key",
            esp_name=self.esp_name,
            kwargs=kwargs,
            default=UNSET if api_key is None else api_key,
        )
        # hmac.new requires bytes key:
        self.webhook_signing_key = webhook_signing_key.encode("ascii")
        super().__init__(**kwargs)

    def validate_request(self, request):
        super().validate_request(request)  # first check basic auth if enabled
        if request.content_type == "application/json":
            # New-style webhook: json payload with separate signature block
            try:
                event = json.loads(request.body.decode("utf-8"))
                signature_block = event["signature"]
                token = signature_block["token"]
                timestamp = signature_block["timestamp"]
                signature = signature_block["signature"]
            except (KeyError, ValueError, UnicodeDecodeError) as err:
                raise AnymailWebhookValidationFailure(
                    "Mailgun webhook called with invalid payload format"
                ) from err
        else:
            # Legacy webhook: signature fields are interspersed with other POST data
            try:
                # Must use the *last* value of these fields if there are conflicting
                # merged user-variables. (Fortunately, Django QueryDict is specced to
                # return the last value.)
                token = request.POST["token"]
                timestamp = request.POST["timestamp"]
                signature = request.POST["signature"]
            except KeyError as err:
                raise AnymailWebhookValidationFailure(
                    "Mailgun webhook called without required security fields"
                ) from err

        expected_signature = hmac.new(
            key=self.webhook_signing_key,
            msg="{}{}".format(timestamp, token).encode("ascii"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        if not constant_time_compare(signature, expected_signature):
            raise AnymailWebhookValidationFailure(
                "Mailgun webhook called with incorrect signature"
            )


class MailgunTrackingWebhookView(MailgunBaseWebhookView):
    """Handler for Mailgun delivery and engagement tracking webhooks"""

    signal = tracking

    def parse_events(self, request):
        if request.content_type == "application/json":
            esp_event = json.loads(request.body.decode("utf-8"))
            return [self.esp_to_anymail_event(esp_event)]
        else:
            return [self.mailgun_legacy_to_anymail_event(request.POST)]

    event_types = {
        # Map Mailgun event: Anymail normalized type
        "accepted": EventType.QUEUED,  # not delivered to webhooks (8/2018)
        "rejected": EventType.REJECTED,
        "delivered": EventType.DELIVERED,
        "failed": EventType.BOUNCED,
        "opened": EventType.OPENED,
        "clicked": EventType.CLICKED,
        "unsubscribed": EventType.UNSUBSCRIBED,
        "complained": EventType.COMPLAINED,
    }

    reject_reasons = {
        # Map Mailgun event_data.reason: Anymail normalized RejectReason (these appear
        # in webhook doc examples, but aren't actually documented anywhere)
        "bounce": RejectReason.BOUNCED,
        "suppress-bounce": RejectReason.BOUNCED,
        # ??? "generic" appears to be used for any temporary failure?
        "generic": RejectReason.OTHER,
    }

    severities = {
        # Remap some event types based on "severity" payload field
        (EventType.BOUNCED, "temporary"): EventType.DEFERRED
    }

    def esp_to_anymail_event(self, esp_event):
        event_data = esp_event.get("event-data", {})

        event_type = self.event_types.get(event_data["event"], EventType.UNKNOWN)

        event_type = self.severities.get(
            (EventType.BOUNCED, event_data.get("severity")), event_type
        )

        # Use signature.token for event_id, rather than event_data.id,
        # because the latter is only "guaranteed to be unique within a day".
        event_id = esp_event.get("signature", {}).get("token")

        recipient = event_data.get("recipient")

        try:
            timestamp = datetime.fromtimestamp(
                float(event_data["timestamp"]), tz=timezone.utc
            )
        except KeyError:
            timestamp = None

        try:
            message_id = event_data["message"]["headers"]["message-id"]
        except KeyError:
            message_id = None
        if message_id and not message_id.startswith("<"):
            message_id = "<{}>".format(message_id)

        metadata = event_data.get("user-variables", {})
        tags = event_data.get("tags", [])

        try:
            delivery_status = event_data["delivery-status"]
        except KeyError:
            description = None
            mta_response = None
        else:
            description = delivery_status.get("description")
            mta_response = delivery_status.get("message")

        if "reason" in event_data:
            reject_reason = self.reject_reasons.get(
                event_data["reason"], RejectReason.OTHER
            )
        else:
            reject_reason = None

        if event_type == EventType.REJECTED:
            # This event has a somewhat different structure than the others...
            description = description or event_data.get("reject", {}).get("reason")
            reject_reason = reject_reason or RejectReason.OTHER
            if not recipient:
                try:
                    to_email = parse_single_address(
                        event_data["message"]["headers"]["to"]
                    )
                except (AnymailInvalidAddress, KeyError):
                    pass
                else:
                    recipient = to_email.addr_spec

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
            click_url=event_data.get("url"),
            user_agent=event_data.get("client-info", {}).get("user-agent"),
            esp_event=esp_event,
        )

    # Legacy event handling
    # (Prior to 2018-06-29, these were the only Mailgun events.)

    legacy_event_types = {
        # Map Mailgun event: Anymail normalized type
        "delivered": EventType.DELIVERED,
        "dropped": EventType.REJECTED,
        "bounced": EventType.BOUNCED,
        "complained": EventType.COMPLAINED,
        "unsubscribed": EventType.UNSUBSCRIBED,
        "opened": EventType.OPENED,
        "clicked": EventType.CLICKED,
        # Mailgun does not send events corresponding to QUEUED or DEFERRED
    }

    legacy_reject_reasons = {
        # Map Mailgun (SMTP) error codes to Anymail normalized reject_reason.
        # By default, we will treat anything 400-599 as REJECT_BOUNCED
        # so only exceptions are listed here.
        499: RejectReason.TIMED_OUT,  # unable to connect to MX
        # (499 also covers invalid recipients)
        # These 6xx codes appear to be Mailgun extensions to SMTP
        # (and don't seem to be documented anywhere):
        605: RejectReason.BOUNCED,  # previous bounce
        607: RejectReason.SPAM,  # previous spam complaint
    }

    def mailgun_legacy_to_anymail_event(self, esp_event):
        # esp_event is a Django QueryDict (from request.POST),
        # which has multi-valued fields, but is *not* case-insensitive.
        # Because of the way Mailgun merges user-variables into the event,
        # we must generally use the *first* value of any multi-valued field
        # to avoid potential conflicting user-data.
        esp_event.getfirst = querydict_getfirst.__get__(esp_event)

        if "event" not in esp_event and "sender" in esp_event:
            # Inbound events don't (currently) have an event field
            raise AnymailConfigurationError(
                "You seem to have set Mailgun's *inbound* route "
                "to Anymail's Mailgun *tracking* webhook URL."
            )

        event_type = self.legacy_event_types.get(
            esp_event.getfirst("event"), EventType.UNKNOWN
        )
        # use *last* value of timestamp:
        timestamp = datetime.fromtimestamp(int(esp_event["timestamp"]), tz=timezone.utc)
        # Message-Id is not documented for every event, but seems to always be included.
        # (It's sometimes spelled as 'message-id', lowercase, and missing the
        # <angle-brackets>.)
        message_id = esp_event.getfirst("Message-Id", None) or esp_event.getfirst(
            "message-id", None
        )
        if message_id and not message_id.startswith("<"):
            message_id = "<{}>".format(message_id)

        description = esp_event.getfirst("description", None)
        mta_response = esp_event.getfirst("error", None) or esp_event.getfirst(
            "notification", None
        )
        reject_reason = None
        try:
            mta_status = int(esp_event.getfirst("code"))
        except (KeyError, TypeError):
            pass
        except ValueError:
            # RFC-3463 extended SMTP status code
            # (class.subject.detail, where class is "2", "4" or "5")
            try:
                status_class = esp_event.getfirst("code").split(".")[0]
            except (TypeError, IndexError):
                # illegal SMTP status code format
                pass
            else:
                reject_reason = (
                    RejectReason.BOUNCED
                    if status_class in ("4", "5")
                    else RejectReason.OTHER
                )
        else:
            reject_reason = self.legacy_reject_reasons.get(
                mta_status,
                RejectReason.BOUNCED if 400 <= mta_status < 600 else RejectReason.OTHER,
            )

        metadata = self._extract_legacy_metadata(esp_event)

        # tags are supposed to be in 'tag' fields,
        # but are sometimes in undocumented X-Mailgun-Tag
        tags = esp_event.getlist("tag", None) or esp_event.getlist("X-Mailgun-Tag", [])

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=esp_event.get("token", None),  # use *last* value of token
            recipient=esp_event.getfirst("recipient", None),
            reject_reason=reject_reason,
            description=description,
            mta_response=mta_response,
            tags=tags,
            metadata=metadata,
            click_url=esp_event.getfirst("url", None),
            user_agent=esp_event.getfirst("user-agent", None),
            esp_event=esp_event,
        )

    def _extract_legacy_metadata(self, esp_event):
        # Mailgun merges user-variables into the POST fields. If you know which user
        # variable you want to retrieve--and it doesn't conflict with a Mailgun event
        # field--that's fine. But if you want to extract all user-variables (like we
        # do), it's more complicated...
        event_type = esp_event.getfirst("event")
        metadata = {}

        if "message-headers" in esp_event:
            # For events where original message headers are available, it's most
            # reliable to recover user-variables from the X-Mailgun-Variables header(s).
            headers = json.loads(esp_event["message-headers"])
            variables = [
                value for [field, value] in headers if field == "X-Mailgun-Variables"
            ]
            if len(variables) >= 1:
                # Each X-Mailgun-Variables value is JSON. Parse and merge them all into
                # single dict:
                metadata = merge_dicts_shallow(
                    *[json.loads(value) for value in variables]
                )

        elif event_type in self._known_legacy_event_fields:
            # For other events, we must extract from the POST fields, ignoring known
            # Mailgun event parameters, and treating all other values as user-variables.
            known_fields = self._known_legacy_event_fields[event_type]
            for field, values in esp_event.lists():
                if field not in known_fields:
                    # Unknown fields are assumed to be user-variables. (There should
                    # really only be a single value, but just in case take the last one
                    # to match QueryDict semantics.)
                    metadata[field] = values[-1]
                elif field == "tag":
                    # There's no way to distinguish a user-variable named 'tag' from
                    # an actual tag, so don't treat this/these value(s) as metadata.
                    pass
                elif len(values) == 1:
                    # This is an expected event parameter, and since there's only a
                    # single value it must be the event param, not metadata.
                    pass
                else:
                    # This is an expected event parameter, but there are (at least) two
                    # values. One is the event param, and the other is a user-variable
                    # metadata value. Which is which depends on the field:
                    if field in {"signature", "timestamp", "token"}:
                        # values = [user-variable, event-param]
                        metadata[field] = values[0]
                    else:
                        # values = [event-param, user-variable]
                        metadata[field] = values[-1]

        return metadata

    _common_legacy_event_fields = {
        # These fields are documented to appear in all Mailgun
        # opened, clicked and unsubscribed events:
        "event",
        "recipient",
        "domain",
        "ip",
        "country",
        "region",
        "city",
        "user-agent",
        "device-type",
        "client-type",
        "client-name",
        "client-os",
        "campaign-id",
        "campaign-name",
        "tag",
        "mailing-list",
        "timestamp",
        "token",
        "signature",
        # Undocumented, but observed in actual events:
        "body-plain",
        "h",
        "message-id",
    }
    _known_legacy_event_fields = {
        # For all Mailgun event types that *don't* include message-headers,
        # map Mailgun (not normalized) event type to set of expected event fields.
        # Used for metadata extraction.
        "clicked": _common_legacy_event_fields | {"url"},
        "opened": _common_legacy_event_fields,
        "unsubscribed": _common_legacy_event_fields,
    }


class MailgunInboundWebhookView(MailgunBaseWebhookView):
    """Handler for Mailgun inbound (route forward-to-url) webhook"""

    signal = inbound

    def parse_events(self, request):
        if request.content_type == "application/json":
            esp_event = json.loads(request.body.decode("utf-8"))
            event_type = esp_event.get("event-data", {}).get("event", "")
            raise AnymailConfigurationError(
                "You seem to have set Mailgun's *%s tracking* webhook "
                "to Anymail's Mailgun *inbound* webhook URL. "
                "(Or Mailgun has changed inbound events to use json.)" % event_type
            )
        return [self.esp_to_anymail_event(request)]

    def esp_to_anymail_event(self, request):
        # Inbound uses the entire Django request as esp_event, because
        # we need POST and FILES. Note that request.POST is case-sensitive
        # (unlike email.message.Message headers).
        esp_event = request

        if request.POST.get("event", "inbound") != "inbound":
            # (Legacy) tracking event
            raise AnymailConfigurationError(
                "You seem to have set Mailgun's *%s tracking* webhook "
                "to Anymail's Mailgun *inbound* webhook URL." % request.POST["event"]
            )

        if "attachments" in request.POST:
            # Inbound route used store() rather than forward().
            # ("attachments" seems to be the only POST param that differs between
            # store and forward; Anymail could support store by handling the JSON
            # attachments param in message_from_mailgun_parsed.)
            raise AnymailConfigurationError(
                "You seem to have configured Mailgun's receiving route using"
                " the store() action. Anymail's inbound webhook requires"
                " the forward() action."
            )

        if "body-mime" in request.POST:
            # Raw-MIME
            message = AnymailInboundMessage.parse_raw_mime(request.POST["body-mime"])
        else:
            # Fully-parsed
            message = self.message_from_mailgun_parsed(request)

        message.envelope_sender = request.POST.get("sender", None)
        message.envelope_recipient = request.POST.get("recipient", None)
        message.stripped_text = request.POST.get("stripped-text", None)
        message.stripped_html = request.POST.get("stripped-html", None)

        message.spam_detected = message.get("X-Mailgun-Sflag", "No").lower() == "yes"
        try:
            message.spam_score = float(message["X-Mailgun-Sscore"])
        except (TypeError, ValueError):
            pass

        return AnymailInboundEvent(
            event_type=EventType.INBOUND,
            timestamp=datetime.fromtimestamp(
                int(request.POST["timestamp"]), tz=timezone.utc
            ),
            event_id=request.POST.get("token", None),
            esp_event=esp_event,
            message=message,
        )

    def message_from_mailgun_parsed(self, request):
        """Construct a Message from Mailgun's "fully-parsed" fields"""
        # Mailgun transcodes all fields to UTF-8 for "fully parsed" messages
        try:
            attachment_count = int(request.POST["attachment-count"])
        except (KeyError, TypeError):
            attachments = None
        else:
            # Load attachments from posted files: attachment-1, attachment-2, etc.
            # content-id-map is {content-id: attachment-id}, identifying which files
            # are inline attachments. Invert it to {attachment-id: content-id}, while
            # handling potentially duplicate content-ids.
            field_to_content_id = json.loads(
                request.POST.get("content-id-map", "{}"),
                object_pairs_hook=lambda pairs: {
                    att_id: cid for (cid, att_id) in pairs
                },
            )
            attachments = []
            for n in range(1, attachment_count + 1):
                attachment_id = "attachment-%d" % n
                try:
                    file = request.FILES[attachment_id]
                except KeyError:
                    # Django's multipart/form-data handling drops FILES with certain
                    # filenames (for security) or with empty filenames (Django ticket
                    # 15879).
                    # (To avoid this problem, use Mailgun's "raw MIME" inbound option.)
                    pass
                else:
                    content_id = field_to_content_id.get(attachment_id)
                    attachment = (
                        AnymailInboundMessage.construct_attachment_from_uploaded_file(
                            file, content_id=content_id
                        )
                    )
                    attachments.append(attachment)

        return AnymailInboundMessage.construct(
            # message-headers includes From, To, Cc, Subject, etc.
            headers=json.loads(request.POST["message-headers"]),
            text=request.POST.get("body-plain", None),
            html=request.POST.get("body-html", None),
            attachments=attachments,
        )
