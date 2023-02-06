from email.mime.image import MIMEImage
from email.utils import unquote
from pathlib import Path

from django.core.mail import EmailMessage, EmailMultiAlternatives, make_msgid

from .utils import UNSET


class AnymailMessageMixin(EmailMessage):
    """Mixin for EmailMessage that exposes Anymail features.

    Use of this mixin is optional. You can always just set Anymail
    attributes on any EmailMessage.

    (The mixin can be helpful with type checkers and other development
    tools that complain about accessing Anymail's added attributes
    on a regular EmailMessage.)
    """

    def __init__(self, *args, **kwargs):
        self.esp_extra = kwargs.pop("esp_extra", UNSET)
        self.envelope_sender = kwargs.pop("envelope_sender", UNSET)
        self.metadata = kwargs.pop("metadata", UNSET)
        self.send_at = kwargs.pop("send_at", UNSET)
        self.tags = kwargs.pop("tags", UNSET)
        self.track_clicks = kwargs.pop("track_clicks", UNSET)
        self.track_opens = kwargs.pop("track_opens", UNSET)
        self.template_id = kwargs.pop("template_id", UNSET)
        self.merge_data = kwargs.pop("merge_data", UNSET)
        self.merge_global_data = kwargs.pop("merge_global_data", UNSET)
        self.merge_metadata = kwargs.pop("merge_metadata", UNSET)
        self.anymail_status = AnymailStatus()

        super().__init__(*args, **kwargs)

    def attach_inline_image_file(self, path, subtype=None, idstring="img", domain=None):
        """
        Add inline image from file path to an EmailMessage, and return its content id
        """
        assert isinstance(self, EmailMessage)
        return attach_inline_image_file(self, path, subtype, idstring, domain)

    def attach_inline_image(
        self, content, filename=None, subtype=None, idstring="img", domain=None
    ):
        """Add inline image and return its content id"""
        assert isinstance(self, EmailMessage)
        return attach_inline_image(self, content, filename, subtype, idstring, domain)


class AnymailMessage(AnymailMessageMixin, EmailMultiAlternatives):
    pass


def attach_inline_image_file(message, path, subtype=None, idstring="img", domain=None):
    """Add inline image from file path to an EmailMessage, and return its content id"""
    pathobj = Path(path)
    filename = pathobj.name
    content = pathobj.read_bytes()
    return attach_inline_image(message, content, filename, subtype, idstring, domain)


def attach_inline_image(
    message, content, filename=None, subtype=None, idstring="img", domain=None
):
    """Add inline image to an EmailMessage, and return its content id"""
    if domain is None:
        # Avoid defaulting to hostname that might end in '.com', because some ESPs
        # use Content-ID as filename, and Gmail blocks filenames ending in '.com'.
        domain = "inline"  # valid domain for a msgid; will never be a real TLD

    # Content ID per RFC 2045 section 7 (with <...>):
    content_id = make_msgid(idstring, domain)

    image = MIMEImage(content, subtype)
    image.add_header("Content-Disposition", "inline", filename=filename)
    image.add_header("Content-ID", content_id)
    message.attach(image)
    return unquote(content_id)  # Without <...>, for use as the <img> tag src


ANYMAIL_STATUSES = [
    "sent",  # the ESP has sent the message (though it may or may not get delivered)
    "queued",  # the ESP will try to send the message later
    "invalid",  # the recipient email was not valid
    "rejected",  # the recipient is blacklisted
    "failed",  # the attempt to send failed for some other reason
    "unknown",  # anything else
]


class AnymailRecipientStatus:
    """Information about an EmailMessage's send status for a single recipient"""

    def __init__(self, message_id, status):
        try:
            # message_id must be something that can be put in a set
            # (see AnymailStatus.set_recipient_status)
            set([message_id])
        except TypeError:
            raise TypeError("Invalid message_id %r is not scalar type" % message_id)
        if status is not None and status not in ANYMAIL_STATUSES:
            raise ValueError("Invalid status %r" % status)
        self.message_id = message_id  # ESP message id
        self.status = status  # one of ANYMAIL_STATUSES, or None for not yet sent to ESP

    def __repr__(self):
        return "AnymailRecipientStatus({message_id!r}, {status!r})".format(
            message_id=self.message_id, status=self.status
        )


class AnymailStatus:
    """Information about an EmailMessage's send status for all recipients"""

    def __init__(self):
        #: set of ESP message ids across all recipients, or bare id if only one, or None
        self.message_id = None
        #: set of ANYMAIL_STATUSES across all recipients, or None if not yet sent to ESP
        self.status = None
        #: per-recipient: { email: AnymailRecipientStatus, ... }
        self.recipients = {}
        self.esp_response = None

    def __repr__(self):
        def _repr(o):
            if isinstance(o, set):
                # force sorted order, for reproducible testing
                item_reprs = [repr(item) for item in sorted(o)]
                return "{%s}" % ", ".join(item_reprs)
            else:
                return repr(o)

        details = ["status={status}".format(status=_repr(self.status))]
        if self.message_id:
            details.append(
                "message_id={message_id}".format(message_id=_repr(self.message_id))
            )
        if self.recipients:
            details.append(
                "{num_recipients} recipients".format(
                    num_recipients=len(self.recipients)
                )
            )
        return "AnymailStatus<{details}>".format(details=", ".join(details))

    def set_recipient_status(self, recipients):
        self.recipients.update(recipients)
        recipient_statuses = self.recipients.values()
        self.message_id = set(
            [recipient.message_id for recipient in recipient_statuses]
        )
        if len(self.message_id) == 1:
            self.message_id = self.message_id.pop()  # de-set-ify if single message_id
        self.status = set([recipient.status for recipient in recipient_statuses])
