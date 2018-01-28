import uuid
from django.core.mail.backends.console import EmailBackend as DjangoConsoleBackend

from ..exceptions import AnymailError
from .test import EmailBackend as AnymailTestBackend


class EmailBackend(AnymailTestBackend, DjangoConsoleBackend):
    """
    Anymail backend that prints messages to the console, while retaining
    anymail statuses and signals.
    """

    esp_name = "Console"

    def get_esp_message_id(self, message):
        # Generate a guaranteed-unique ID for the message
        return str(uuid.uuid4())

    def send_messages(self, email_messages):
        if not email_messages:
            return
        msg_count = 0
        with self._lock:
            try:
                stream_created = self.open()
                for message in email_messages:
                    try:
                        sent = self._send(message)
                    except AnymailError:
                        if self.fail_silently:
                            sent = False
                        else:
                            raise
                    if sent:
                        self.write_message(message)
                        self.stream.flush()  # flush after each message
                        msg_count += 1
            finally:
                if stream_created:
                    self.close()

        return msg_count
