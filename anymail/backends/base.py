from datetime import date, datetime

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.utils.timezone import is_naive, get_current_timezone, make_aware, utc

from ..exceptions import AnymailCancelSend, AnymailError, AnymailUnsupportedFeature, AnymailRecipientsRefused
from ..message import AnymailStatus
from ..signals import pre_send, post_send
from ..utils import (Attachment, ParsedEmail, UNSET, combine, last, get_anymail_setting,
                     force_non_lazy, force_non_lazy_list, force_non_lazy_dict)


class AnymailBaseBackend(BaseEmailBackend):
    """
    Base Anymail email backend
    """

    def __init__(self, *args, **kwargs):
        super(AnymailBaseBackend, self).__init__(*args, **kwargs)

        self.ignore_unsupported_features = get_anymail_setting('ignore_unsupported_features',
                                                               kwargs=kwargs, default=False)
        self.ignore_recipient_status = get_anymail_setting('ignore_recipient_status',
                                                           kwargs=kwargs, default=False)

        # Merge SEND_DEFAULTS and <esp_name>_SEND_DEFAULTS settings
        send_defaults = get_anymail_setting('send_defaults', default={})  # but not from kwargs
        esp_send_defaults = get_anymail_setting('send_defaults', esp_name=self.esp_name,
                                                kwargs=kwargs, default=None)
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
        self.raise_for_recipient_status(message.anymail_status, response, payload, message)

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
            self.__class__, message=message, status=message.anymail_status, esp_name=self.esp_name)
        for (receiver, response) in results:
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
        raise NotImplementedError("%s.%s must implement build_message_payload" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def post_to_esp(self, payload, message):
        """Post payload to ESP send API endpoint, and return the raw response.

        payload is the result of build_message_payload
        message is the original EmailMessage
        return should be a raw response

        Can raise AnymailAPIError (or derived exception) for problems posting to the ESP
        """
        raise NotImplementedError("%s.%s must implement post_to_esp" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def parse_recipient_status(self, response, payload, message):
        """Return a dict mapping email to AnymailRecipientStatus for each recipient.

        Can raise AnymailAPIError (or derived exception) if response is unparsable
        """
        raise NotImplementedError("%s.%s must implement parse_recipient_status" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def raise_for_recipient_status(self, anymail_status, response, payload, message):
        """If *all* recipients are refused or invalid, raises AnymailRecipientsRefused"""
        if not self.ignore_recipient_status:
            # Error if *all* recipients are invalid or refused
            # (This behavior parallels smtplib.SMTPRecipientsRefused from Django's SMTP EmailBackend)
            if anymail_status.status.issubset({"invalid", "rejected"}):
                raise AnymailRecipientsRefused(email_message=message, payload=payload, response=response)

    @property
    def esp_name(self):
        """
        Read-only name of the ESP for this backend.

        (E.g., MailgunBackend will return "Mailgun")
        """
        return self.__class__.__name__.replace("Backend", "")


class BasePayload(object):
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
        ('from_email', last, 'parsed_email'),
        ('to', combine, 'parsed_emails'),
        ('cc', combine, 'parsed_emails'),
        ('bcc', combine, 'parsed_emails'),
        ('subject', last, force_non_lazy),
        ('reply_to', combine, 'parsed_emails'),
        ('extra_headers', combine, force_non_lazy_dict),
        ('body', last, force_non_lazy),  # special handling below checks message.content_subtype
        ('alternatives', combine, 'prepped_alternatives'),
        ('attachments', combine, 'prepped_attachments'),
    )
    anymail_message_attrs = (
        # Anymail expando-props
        ('metadata', combine, force_non_lazy_dict),
        ('send_at', last, 'aware_datetime'),
        ('tags', combine, force_non_lazy_list),
        ('track_clicks', last, None),
        ('track_opens', last, None),
        ('template_id', last, force_non_lazy),
        ('merge_data', combine, force_non_lazy_dict),
        ('merge_global_data', combine, force_non_lazy_dict),
        ('esp_extra', combine, force_non_lazy_dict),
    )
    esp_message_attrs = ()  # subclasses can override

    def __init__(self, message, defaults, backend):
        self.message = message
        self.defaults = defaults
        self.backend = backend
        self.esp_name = backend.esp_name

        self.init_payload()

        # we should consider hoisting the first text/html out of alternatives into set_html_body
        message_attrs = self.base_message_attrs + self.anymail_message_attrs + self.esp_message_attrs
        for attr, combiner, converter in message_attrs:
            value = getattr(message, attr, UNSET)
            if combiner is not None:
                default_value = self.defaults.get(attr, UNSET)
                value = combiner(default_value, value)
            if value is not UNSET:
                if converter is not None:
                    if not callable(converter):
                        converter = getattr(self, converter)
                    value = converter(value)
            if value is not UNSET:
                if attr == 'body':
                    setter = self.set_html_body if message.content_subtype == 'html' else self.set_text_body
                else:
                    # AttributeError here? Your Payload subclass is missing a set_<attr> implementation
                    setter = getattr(self, 'set_%s' % attr)
                setter(value)

    def unsupported_feature(self, feature):
        if not self.backend.ignore_unsupported_features:
            raise AnymailUnsupportedFeature("%s does not support %s" % (self.esp_name, feature),
                                            email_message=self.message, payload=self, backend=self.backend)

    #
    # Attribute converters
    #

    def parsed_email(self, address):
        return ParsedEmail(address, self.message.encoding)  # (handles lazy address)

    def parsed_emails(self, addresses):
        encoding = self.message.encoding
        return [ParsedEmail(address, encoding)  # (handles lazy address)
                for address in addresses]

    def prepped_alternatives(self, alternatives):
        return [(force_non_lazy(content), mimetype)
                for (content, mimetype) in alternatives]

    def prepped_attachments(self, attachments):
        str_encoding = self.message.encoding or settings.DEFAULT_CHARSET
        return [Attachment(attachment, str_encoding)  # (handles lazy content, filename)
                for attachment in attachments]

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
                    dt = datetime.utcfromtimestamp(value).replace(tzinfo=utc)
                except (TypeError, ValueError):
                    return value
        if is_naive(dt):
            dt = make_aware(dt, get_current_timezone())
        return dt

    #
    # Abstract implementation
    #

    def init_payload(self):
        raise NotImplementedError("%s.%s must implement init_payload" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def set_from_email(self, email):
        raise NotImplementedError("%s.%s must implement set_from_email" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def set_to(self, emails):
        return self.set_recipients('to', emails)

    def set_cc(self, emails):
        return self.set_recipients('cc', emails)

    def set_bcc(self, emails):
        return self.set_recipients('bcc', emails)

    def set_recipients(self, recipient_type, emails):
        for email in emails:
            self.add_recipient(recipient_type, email)

    def add_recipient(self, recipient_type, email):
        raise NotImplementedError("%s.%s must implement add_recipient, set_recipients, or set_{to,cc,bcc}" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def set_subject(self, subject):
        raise NotImplementedError("%s.%s must implement set_subject" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def set_reply_to(self, emails):
        self.unsupported_feature('reply_to')

    def set_extra_headers(self, headers):
        self.unsupported_feature('extra_headers')

    def set_text_body(self, body):
        raise NotImplementedError("%s.%s must implement set_text_body" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def set_html_body(self, body):
        raise NotImplementedError("%s.%s must implement set_html_body" %
                                  (self.__class__.__module__, self.__class__.__name__))

    def set_alternatives(self, alternatives):
        for content, mimetype in alternatives:
            if mimetype == "text/html":
                # This assumes that there's at most one html alternative,
                # and so it should be the html body. (Most ESPs don't
                # support multiple html alternative parts anyway.)
                self.set_html_body(content)
            else:
                self.add_alternative(content, mimetype)

    def add_alternative(self, content, mimetype):
        self.unsupported_feature("alternative part with type '%s'" % mimetype)

    def set_attachments(self, attachments):
        for attachment in attachments:
            self.add_attachment(attachment)

    def add_attachment(self, attachment):
        raise NotImplementedError("%s.%s must implement add_attachment or set_attachments" %
                                  (self.__class__.__module__, self.__class__.__name__))

    # Anymail-specific payload construction
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

    # ESP-specific payload construction
    def set_esp_extra(self, extra):
        self.unsupported_feature("esp_extra")
