import json
from datetime import date, datetime, timezone

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.utils.timezone import get_current_timezone, is_naive, make_aware
from requests.structures import CaseInsensitiveDict

from ..exceptions import (
    AnymailCancelSend,
    AnymailError,
    AnymailRecipientsRefused,
    AnymailSerializationError,
    AnymailUnsupportedFeature,
)
from ..message import AnymailStatus
from ..signals import post_send, pre_send
from ..utils import (
    UNSET,
    Attachment,
    combine,
    force_non_lazy,
    force_non_lazy_dict,
    force_non_lazy_list,
    get_anymail_setting,
    is_lazy,
    last,
    parse_address_list,
    parse_single_address,
)


class AnymailBaseBackend(BaseEmailBackend):
    """
    Base Anymail email backend
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ignore_unsupported_features = get_anymail_setting(
            "ignore_unsupported_features", kwargs=kwargs, default=False
        )
        self.ignore_recipient_status = get_anymail_setting(
            "ignore_recipient_status", kwargs=kwargs, default=False
        )
        self.debug_api_requests = get_anymail_setting(
            "debug_api_requests", kwargs=kwargs, default=False
        )

        # Merge SEND_DEFAULTS and <esp_name>_SEND_DEFAULTS settings
        send_defaults = get_anymail_setting(
            "send_defaults", default={}  # but not from kwargs
        )
        esp_send_defaults = get_anymail_setting(
            "send_defaults", esp_name=self.esp_name, kwargs=kwargs, default=None
        )
        if esp_send_defaults is not None:
            send_defaults = send_defaults.copy()
            send_defaults.update(esp_send_defaults)
        self.send_defaults = send_defaults

    def open(self):
        """
        Open and persist a connection to the ESP's API, and whether
        a new connection was created.

        Callers must ensure they later call close, if (and only if) open
        returns True.
        """
        # Subclasses should use an instance property to maintain a cached
        # connection, and return True iff they initialize that instance
        # property in _this_ open call. (If the cached connection already
        # exists, just do nothing and return False.)
        #
        # Subclasses should swallow operational errors if self.fail_silently
        # (e.g., network errors), but otherwise can raise any errors.
        #
        # (Returning a bool to indicate whether connection was created is
        # borrowed from django.core.email.backends.SMTPBackend)
        return False

    def close(self):
        """
        Close the cached connection created by open.

        You must only call close if your code called open and it returned True.
        """
        # Subclasses should tear down the cached connection and clear
        # the instance property.
        #
        # Subclasses should swallow operational errors if self.fail_silently
        # (e.g., network errors), but otherwise can raise any errors.
        pass

    def send_messages(self, email_messages):
        """
        Sends one or more EmailMessage objects and returns the number of email
        messages sent.
        """
        # This API is specified by Django's core BaseEmailBackend
        # (so you can't change it to, e.g., return detailed status).
        # Subclasses shouldn't need to override.

        num_sent = 0
        if not email_messages:
            return num_sent

        created_session = self.open()

        try:
            for message in email_messages:
                try:
                    sent = self._send(message)
                except AnymailError:
                    if self.fail_silently:
                        sent = False
                    else:
                        raise
                if sent:
                    num_sent += 1
        finally:
            if created_session:
                self.close()

        return num_sent

    def _send(self, message):
        """Sends the EmailMessage message, and returns True if the message was sent.

        This should only be called by the base send_messages loop.

        Implementations must raise exceptions derived from AnymailError for
        anticipated failures that should be suppressed in fail_silently mode.
        """
        message.anymail_status = AnymailStatus()
        if not self.run_pre_send(message):  # (might modify message)
            return False  # cancel send without error

        if not message.recipients():
            return False

        payload = self.build_message_payload(message, self.send_defaults)
        response = self.post_to_esp(payload, message)
        message.anymail_status.esp_response = response

        recipient_status = self.parse_recipient_status(response, payload, message)
        message.anymail_status.set_recipient_status(recipient_status)

        self.run_post_send(message)  # send signal before raising status errors
        self.raise_for_recipient_status(
            message.anymail_status, response, payload, message
        )

        return True

    def run_pre_send(self, message):
        """Send pre_send signal, and return True if message should still be sent"""
        try:
            pre_send.send(self.__class__, message=message, esp_name=self.esp_name)
            return True
        except AnymailCancelSend:
            return False  # abort without causing error

    def run_post_send(self, message):
        """Send post_send signal to all receivers"""
        results = post_send.send_robust(
            self.__class__,
            message=message,
            status=message.anymail_status,
            esp_name=self.esp_name,
        )
        for receiver, response in results:
            if isinstance(response, Exception):
                raise response

    def build_message_payload(self, message, defaults):
        """Returns a payload that will allow message to be sent via the ESP.

        Derived classes must implement, and should subclass :class:BasePayload
        to get standard Anymail options.

        Raises :exc:AnymailUnsupportedFeature for message options that
        cannot be communicated to the ESP.

        :param message: :class:EmailMessage
        :param defaults: dict
        :return: :class:BasePayload
        """
        raise NotImplementedError(
            "%s.%s must implement build_message_payload"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def post_to_esp(self, payload, message):
        """Post payload to ESP send API endpoint, and return the raw response.

        payload is the result of build_message_payload
        message is the original EmailMessage
        return should be a raw response

        Can raise AnymailAPIError (or derived exception) for problems posting to the ESP
        """
        raise NotImplementedError(
            "%s.%s must implement post_to_esp"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def parse_recipient_status(self, response, payload, message):
        """Return a dict mapping email to AnymailRecipientStatus for each recipient.

        Can raise AnymailAPIError (or derived exception) if response is unparsable
        """
        raise NotImplementedError(
            "%s.%s must implement parse_recipient_status"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def raise_for_recipient_status(self, anymail_status, response, payload, message):
        """
        If *all* recipients are refused or invalid, raises AnymailRecipientsRefused
        """
        if not self.ignore_recipient_status:
            # Error if *all* recipients are invalid or refused. (This behavior parallels
            # smtplib.SMTPRecipientsRefused from Django's SMTP EmailBackend.)
            if anymail_status.status.issubset({"invalid", "rejected"}):
                raise AnymailRecipientsRefused(
                    email_message=message,
                    payload=payload,
                    response=response,
                    backend=self,
                )

    @property
    def esp_name(self):
        """
        Read-only name of the ESP for this backend.

        Concrete backends must override with class attr. E.g.:
            esp_name = "Postmark"
            esp_name = "SendGrid"  # (use ESP's preferred capitalization)
        """
        raise NotImplementedError(
            "%s.%s must declare esp_name class attr"
            % (self.__class__.__module__, self.__class__.__name__)
        )


class BasePayload:
    # Listing of EmailMessage/EmailMultiAlternatives attributes
    # to process into Payload. Each item is in the form:
    #   (attr, combiner, converter)
    #   attr: the property name
    #   combiner: optional function(default_value, value) -> value
    #     to combine settings defaults with the EmailMessage property value
    #     (usually `combine` to merge, or `last` for message value to override default;
    #     use `None` if settings defaults aren't supported)
    #   converter: optional function(value) -> value transformation
    #     (can be a callable or the string name of a Payload method, or `None`)
    #     The converter must force any Django lazy translation strings to text.
    # The Payload's `set_<attr>` method will be called with
    # the combined/converted results for each attr.
    base_message_attrs = (
        # Standard EmailMessage/EmailMultiAlternatives props
        ("from_email", last, parse_address_list),  # multiple from_emails are allowed
        ("to", combine, parse_address_list),
        ("cc", combine, parse_address_list),
        ("bcc", combine, parse_address_list),
        ("subject", last, force_non_lazy),
        ("reply_to", combine, parse_address_list),
        ("extra_headers", combine, force_non_lazy_dict),
        ("body", last, force_non_lazy),  # set_body handles content_subtype
        ("alternatives", combine, "prepped_alternatives"),
        ("attachments", combine, "prepped_attachments"),
    )
    anymail_message_attrs = (
        # Anymail expando-props
        ("envelope_sender", last, parse_single_address),
        ("metadata", combine, force_non_lazy_dict),
        ("send_at", last, "aware_datetime"),
        ("tags", combine, force_non_lazy_list),
        ("track_clicks", last, None),
        ("track_opens", last, None),
        ("template_id", last, force_non_lazy),
        ("merge_data", combine, force_non_lazy_dict),
        ("merge_global_data", combine, force_non_lazy_dict),
        ("merge_metadata", combine, force_non_lazy_dict),
        ("esp_extra", combine, force_non_lazy_dict),
    )
    esp_message_attrs = ()  # subclasses can override

    # If any of these attrs are set on a message, treat the message
    # as a batch send (separate message for each `to` recipient):
    batch_attrs = ("merge_data", "merge_metadata")

    def __init__(self, message, defaults, backend):
        self.message = message
        self.defaults = defaults
        self.backend = backend
        self.esp_name = backend.esp_name
        self._batch_attrs_used = {attr: UNSET for attr in self.batch_attrs}

        self.init_payload()

        # we should consider hoisting the first text/html
        # out of alternatives into set_html_body
        message_attrs = (
            self.base_message_attrs
            + self.anymail_message_attrs
            + self.esp_message_attrs
        )
        for attr, combiner, converter in message_attrs:
            value = getattr(message, attr, UNSET)
            if attr in ("to", "cc", "bcc", "reply_to") and value is not UNSET:
                self.validate_not_bare_string(attr, value)
            if combiner is not None:
                default_value = self.defaults.get(attr, UNSET)
                value = combiner(default_value, value)
            if value is not UNSET:
                if converter is not None:
                    if not callable(converter):
                        converter = getattr(self, converter)
                    if converter in (parse_address_list, parse_single_address):
                        # hack to include field name in error message
                        value = converter(value, field=attr)
                    else:
                        value = converter(value)
            if value is not UNSET:
                if attr == "from_email":
                    setter = self.set_from_email_list
                elif attr == "extra_headers":
                    setter = self.process_extra_headers
                else:
                    # AttributeError here? Your Payload subclass is missing
                    # a set_<attr> implementation
                    setter = getattr(self, "set_%s" % attr)
                setter(value)
            if attr in self.batch_attrs:
                self._batch_attrs_used[attr] = value is not UNSET

    def is_batch(self):
        """
        Return True if the message should be treated as a batch send.

        Intended to be used inside serialize_data or similar, after all relevant
        attributes have been processed. Will error if called before that (e.g.,
        inside a set_<attr> method or during __init__).
        """
        batch_attrs_used = self._batch_attrs_used.values()
        assert (
            UNSET not in batch_attrs_used
        ), "Cannot call is_batch before all attributes processed"
        return any(batch_attrs_used)

    def unsupported_feature(self, feature):
        if not self.backend.ignore_unsupported_features:
            raise AnymailUnsupportedFeature(
                "%s does not support %s" % (self.esp_name, feature),
                email_message=self.message,
                payload=self,
                backend=self.backend,
            )

    def process_extra_headers(self, headers):
        # Handle some special-case headers, and pass the remainder to set_extra_headers.
        # (Subclasses shouldn't need to override this.)

        # email headers are case-insensitive per RFC-822 et seq:
        headers = CaseInsensitiveDict(headers)

        reply_to = headers.pop("Reply-To", None)
        if reply_to:
            # message.extra_headers['Reply-To'] will override message.reply_to
            # (because the extra_headers attr is processed after reply_to).
            # This matches the behavior of Django's EmailMessage.message().
            self.set_reply_to(
                parse_address_list([reply_to], field="extra_headers['Reply-To']")
            )

        if "From" in headers:
            # If message.extra_headers['From'] is supplied, it should override
            # message.from_email, but message.from_email should be used as the
            # envelope_sender. See:
            #   https://code.djangoproject.com/ticket/9214
            #   https://github.com/django/django/blob/1.8/django/core/mail/message.py#L269
            #   https://github.com/django/django/blob/1.8/django/core/mail/backends/smtp.py#L118
            header_from = parse_address_list(
                headers.pop("From"), field="extra_headers['From']"
            )
            # sender must be single:
            envelope_sender = parse_single_address(
                self.message.from_email, field="from_email"
            )
            self.set_from_email_list(header_from)
            self.set_envelope_sender(envelope_sender)

        if "To" in headers:
            # If message.extra_headers['To'] is supplied, message.to is used only as
            # the envelope recipients (SMTP.sendmail to_addrs), and the header To is
            # spoofed. See:
            #   https://github.com/django/django/blob/1.8/django/core/mail/message.py#L270
            #   https://github.com/django/django/blob/1.8/django/core/mail/backends/smtp.py#L119-L120
            # No current ESP supports this, so this code is mainly here to flag
            # the SMTP backend's behavior as an unsupported feature in Anymail:
            header_to = headers.pop("To")
            self.set_spoofed_to_header(header_to)

        if headers:
            self.set_extra_headers(headers)

    #
    # Attribute validators
    #

    def validate_not_bare_string(self, attr, value):
        """EmailMessage to, cc, bcc, and reply_to are specced to be lists of strings.

        This catches the common error where a single string is used instead.
        (See also checks in EmailMessage.__init__.)
        """
        # Note: this actually only runs for reply_to. If to, cc, or bcc are
        # set to single strings, you'll end up with an earlier cryptic TypeError
        # from EmailMesssage.recipients (called from EmailMessage.send) before
        # the Anymail backend even gets involved:
        #   TypeError: must be str, not list
        #   TypeError: can only concatenate list (not "str") to list
        #   TypeError: Can't convert 'list' object to str implicitly
        if isinstance(value, str) or is_lazy(value):
            raise TypeError(
                '"{attr}" attribute must be a list or other iterable'.format(attr=attr)
            )

    #
    # Attribute converters
    #

    def prepped_alternatives(self, alternatives):
        return [
            (force_non_lazy(content), mimetype) for (content, mimetype) in alternatives
        ]

    def prepped_attachments(self, attachments):
        str_encoding = self.message.encoding or settings.DEFAULT_CHARSET
        return [
            Attachment(attachment, str_encoding)  # (handles lazy content, filename)
            for attachment in attachments
        ]

    def aware_datetime(self, value):
        """Converts a date or datetime or timestamp to an aware datetime.

        Naive datetimes are assumed to be in Django's current_timezone.
        Dates are interpreted as midnight that date, in Django's current_timezone.
        Integers are interpreted as POSIX timestamps (which are inherently UTC).

        Anything else (e.g., str) is returned unchanged, which won't be portable.
        """
        if isinstance(value, datetime):
            dt = value
        else:
            if isinstance(value, date):
                dt = datetime(value.year, value.month, value.day)  # naive, midnight
            else:
                try:
                    dt = datetime.utcfromtimestamp(value).replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    return value
        if is_naive(dt):
            dt = make_aware(dt, get_current_timezone())
        return dt

    #
    # Abstract implementation
    #

    def init_payload(self):
        raise NotImplementedError(
            "%s.%s must implement init_payload"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_from_email_list(self, emails):
        # If your backend supports multiple from emails, override this to handle
        # the whole list; otherwise just implement set_from_email
        if len(emails) > 1:
            self.unsupported_feature("multiple from emails")
            # fall through if ignoring unsupported features
        if len(emails) > 0:
            self.set_from_email(emails[0])

    def set_from_email(self, email):
        raise NotImplementedError(
            "%s.%s must implement set_from_email or set_from_email_list"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_to(self, emails):
        return self.set_recipients("to", emails)

    def set_cc(self, emails):
        return self.set_recipients("cc", emails)

    def set_bcc(self, emails):
        return self.set_recipients("bcc", emails)

    def set_recipients(self, recipient_type, emails):
        for email in emails:
            self.add_recipient(recipient_type, email)

    def add_recipient(self, recipient_type, email):
        raise NotImplementedError(
            "%s.%s must implement add_recipient, set_recipients, or set_{to,cc,bcc}"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_subject(self, subject):
        raise NotImplementedError(
            "%s.%s must implement set_subject"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_reply_to(self, emails):
        self.unsupported_feature("reply_to")

    def set_extra_headers(self, headers):
        # headers is a CaseInsensitiveDict, and is a copy (so is safe to modify)
        self.unsupported_feature("extra_headers")

    def set_body(self, body):
        # Interpret message.body depending on message.content_subtype.
        # (Subclasses should generally implement set_text_body and set_html_body
        # rather than overriding this.)
        content_subtype = self.message.content_subtype
        if content_subtype == "plain":
            self.set_text_body(body)
        elif content_subtype == "html":
            self.set_html_body(body)
        else:
            self.add_alternative(body, "text/%s" % content_subtype)

    def set_text_body(self, body):
        raise NotImplementedError(
            "%s.%s must implement set_text_body"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_html_body(self, body):
        raise NotImplementedError(
            "%s.%s must implement set_html_body"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_alternatives(self, alternatives):
        # Handle treating first text/{plain,html} alternatives as bodies.
        # (Subclasses should generally implement add_alternative
        # rather than overriding this.)
        has_plain_body = self.message.content_subtype == "plain" and self.message.body
        has_html_body = self.message.content_subtype == "html" and self.message.body
        for content, mimetype in alternatives:
            if mimetype == "text/plain" and not has_plain_body:
                self.set_text_body(content)
                has_plain_body = True
            elif mimetype == "text/html" and not has_html_body:
                self.set_html_body(content)
                has_html_body = True
            else:
                self.add_alternative(content, mimetype)

    def add_alternative(self, content, mimetype):
        if mimetype == "text/plain":
            self.unsupported_feature("multiple plaintext parts")
        elif mimetype == "text/html":
            self.unsupported_feature("multiple html parts")
        else:
            self.unsupported_feature("alternative part with type '%s'" % mimetype)

    def set_attachments(self, attachments):
        for attachment in attachments:
            self.add_attachment(attachment)

    def add_attachment(self, attachment):
        raise NotImplementedError(
            "%s.%s must implement add_attachment or set_attachments"
            % (self.__class__.__module__, self.__class__.__name__)
        )

    def set_spoofed_to_header(self, header_to):
        # In the unlikely case an ESP supports *completely replacing* the To message
        # header without altering the actual envelope recipients, the backend can
        # implement this.
        self.unsupported_feature("spoofing `To` header")

    # Anymail-specific payload construction
    def set_envelope_sender(self, email):
        self.unsupported_feature("envelope_sender")

    def set_metadata(self, metadata):
        self.unsupported_feature("metadata")

    def set_send_at(self, send_at):
        self.unsupported_feature("send_at")

    def set_tags(self, tags):
        self.unsupported_feature("tags")

    def set_track_clicks(self, track_clicks):
        self.unsupported_feature("track_clicks")

    def set_track_opens(self, track_opens):
        self.unsupported_feature("track_opens")

    def set_template_id(self, template_id):
        self.unsupported_feature("template_id")

    def set_merge_data(self, merge_data):
        self.unsupported_feature("merge_data")

    def set_merge_global_data(self, merge_global_data):
        self.unsupported_feature("merge_global_data")

    def set_merge_metadata(self, merge_metadata):
        self.unsupported_feature("merge_metadata")

    # ESP-specific payload construction
    def set_esp_extra(self, extra):
        self.unsupported_feature("esp_extra")

    #
    # Helpers for concrete implementations
    #

    def serialize_json(self, data):
        """Returns data serialized to json, raising appropriate errors.

        Essentially json.dumps with added context in any errors.

        Useful for implementing, e.g., serialize_data in a subclass,
        """
        try:
            return json.dumps(data, default=self._json_default)
        except TypeError as err:
            # Add some context to the "not JSON serializable" message
            raise AnymailSerializationError(
                orig_err=err,
                email_message=self.message,
                backend=self.backend,
                payload=self,
            ) from None

    @staticmethod
    def _json_default(o):
        """json.dump default function that handles some common Payload data types"""
        if isinstance(o, CaseInsensitiveDict):  # used for headers
            return dict(o)
        raise TypeError(
            "Object of type '%s' is not JSON serializable" % o.__class__.__name__
        )
