from django.core import mail

from ..exceptions import AnymailAPIError
from ..message import AnymailRecipientStatus
from .base import AnymailBaseBackend, BasePayload


class EmailBackend(AnymailBaseBackend):
    """
    Anymail backend that simulates sending messages, useful for testing.

    Sent messages are collected in django.core.mail.outbox
    (as with Django's locmem backend).

    In addition:
    * Anymail send params parsed from the message will be attached
      to the outbox message as a dict in the attr `anymail_test_params`
    * If the caller supplies an `anymail_test_response` attr on the message,
      that will be used instead of the default "sent" response. It can be either
      an AnymailRecipientStatus or an instance of AnymailAPIError (or a subclass)
      to raise an exception.
    """

    esp_name = "Test"

    def __init__(self, *args, **kwargs):
        # Allow replacing the payload, for testing.
        # (Real backends would generally not implement this option.)
        self._payload_class = kwargs.pop("payload_class", TestPayload)
        super().__init__(*args, **kwargs)
        if not hasattr(mail, "outbox"):
            mail.outbox = []  # see django.core.mail.backends.locmem

    def get_esp_message_id(self, message):
        # Get a unique ID for the message.  The message must have been added to
        # the outbox first.
        return mail.outbox.index(message)

    def build_message_payload(self, message, defaults):
        return self._payload_class(backend=self, message=message, defaults=defaults)

    def post_to_esp(self, payload, message):
        # Keep track of the sent messages and params (for test cases)
        message.anymail_test_params = payload.get_params()
        mail.outbox.append(message)
        try:
            # Tests can supply their own message.test_response:
            response = message.anymail_test_response
            if isinstance(response, AnymailAPIError):
                raise response
        except AttributeError:
            # Default is to return 'sent' for each recipient
            status = AnymailRecipientStatus(
                message_id=self.get_esp_message_id(message), status="sent"
            )
            response = {
                "recipient_status": {
                    email: status for email in payload.recipient_emails
                }
            }
        return response

    def parse_recipient_status(self, response, payload, message):
        try:
            return response["recipient_status"]
        except KeyError as err:
            raise AnymailAPIError("Unparsable test response") from err


class TestPayload(BasePayload):
    # For test purposes, just keep a dict of the params we've received.
    # (This approach is also useful for native API backends -- think of
    # payload.params as collecting kwargs for esp_native_api.send().)

    def init_payload(self):
        self.params = {}
        self.recipient_emails = []

    def get_params(self):
        # Test backend callers can check message.anymail_test_params['is_batch_send']
        # to verify whether Anymail thought the message should use batch send logic.
        self.params["is_batch_send"] = self.is_batch()
        return self.params

    def set_from_email(self, email):
        self.params["from"] = email

    def set_envelope_sender(self, email):
        self.params["envelope_sender"] = email.addr_spec

    def set_to(self, emails):
        self.params["to"] = emails
        self.recipient_emails += [email.addr_spec for email in emails]

    def set_cc(self, emails):
        self.params["cc"] = emails
        self.recipient_emails += [email.addr_spec for email in emails]

    def set_bcc(self, emails):
        self.params["bcc"] = emails
        self.recipient_emails += [email.addr_spec for email in emails]

    def set_subject(self, subject):
        self.params["subject"] = subject

    def set_reply_to(self, emails):
        self.params["reply_to"] = emails

    def set_extra_headers(self, headers):
        self.params["extra_headers"] = headers

    def set_text_body(self, body):
        self.params["text_body"] = body

    def set_html_body(self, body):
        self.params["html_body"] = body

    def add_alternative(self, content, mimetype):
        # For testing purposes, we allow all "text/*" alternatives,
        # but not any other mimetypes.
        if mimetype.startswith("text"):
            self.params.setdefault("alternatives", []).append((content, mimetype))
        else:
            self.unsupported_feature("alternative part with type '%s'" % mimetype)

    def add_attachment(self, attachment):
        self.params.setdefault("attachments", []).append(attachment)

    def set_metadata(self, metadata):
        self.params["metadata"] = metadata

    def set_send_at(self, send_at):
        self.params["send_at"] = send_at

    def set_tags(self, tags):
        self.params["tags"] = tags

    def set_track_clicks(self, track_clicks):
        self.params["track_clicks"] = track_clicks

    def set_track_opens(self, track_opens):
        self.params["track_opens"] = track_opens

    def set_template_id(self, template_id):
        self.params["template_id"] = template_id

    def set_merge_data(self, merge_data):
        self.params["merge_data"] = merge_data

    def set_merge_metadata(self, merge_metadata):
        self.params["merge_metadata"] = merge_metadata

    def set_merge_global_data(self, merge_global_data):
        self.params["merge_global_data"] = merge_global_data

    def set_esp_extra(self, extra):
        # Merge extra into params
        self.params.update(extra)
