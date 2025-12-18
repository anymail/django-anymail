.. _signals:

Pre- and post-send signals
==========================

Anymail provides :ref:`pre-send <pre-send-signal>` and :ref:`post-send <post-send-signal>`
signals you can connect to trigger actions whenever messages are sent through an Anymail backend.

Be sure to read Django's `listening to signals`_ docs for information on defining
and connecting signal receivers.

.. _listening to signals:
    https://docs.djangoproject.com/en/stable/topics/signals/#listening-to-signals


.. _pre-send-signal:

Pre-send signal
---------------

You can use Anymail's :data:`~anymail.signals.pre_send` signal to examine
or modify messages before they are sent.
For example, you could implement your own email suppression list:

.. code-block:: python

    from anymail.exceptions import AnymailCancelSend
    from anymail.signals import pre_send
    from django.dispatch import receiver
    from email.utils import parseaddr

    from your_app.models import EmailBlockList

    @receiver(pre_send)
    def filter_blocked_recipients(sender, message, **kwargs):
        # Cancel the entire send if the from_email is blocked:
        if not ok_to_send(message.from_email):
            raise AnymailCancelSend("Blocked from_email")
        # Otherwise filter the recipients before sending:
        message.to = [addr for addr in message.to if ok_to_send(addr)]
        message.cc = [addr for addr in message.cc if ok_to_send(addr)]

    def ok_to_send(addr):
        # This assumes you've implemented an EmailBlockList model
        # that holds emails you want to reject...
        name, email = parseaddr(addr)  # just want the <email> part
        try:
            EmailBlockList.objects.get(email=email)
            return False  # in the blocklist, so *not* OK to send
        except EmailBlockList.DoesNotExist:
            return True  # *not* in the blocklist, so OK to send

Any changes you make to the message in your pre-send signal receiver
will be reflected in the ESP send API call, as shown for the filtered
"to" and "cc" lists above. Note that this will modify the original
EmailMessage (not a copy)---be sure this won't confuse your sending
code that created the message.

If you want to cancel the message altogether, your pre-send receiver
function can raise an :exc:`~anymail.signals.AnymailCancelSend` exception,
as shown for the "from_email" above. This will silently cancel the send
without raising any other errors.


.. data:: anymail.signals.pre_send

    Signal delivered before each EmailMessage is sent.

    Your pre_send receiver must be a function with this signature:

    .. function:: def my_pre_send_handler(sender, message, esp_name, **kwargs):

       (You can name it anything you want.)

       :param class sender:
           The Anymail backend class processing the message.
           This parameter is required by Django's signal mechanism,
           and despite the name has nothing to do with the *email message's* sender.
           (You generally won't need to examine this parameter.)
       :param ~django.core.mail.EmailMessage message:
           The message being sent. If your receiver modifies the message, those
           changes will be reflected in the ESP send call.
       :param str esp_name:
           The name of the ESP backend in use (e.g., "Amazon SES" or "Mailgun").
       :param \**kwargs:
           Required by Django's signal mechanism (to support future extensions).
       :raises:
           :exc:`anymail.exceptions.AnymailCancelSend` if your receiver wants
           to cancel this message without causing errors or interrupting a batch send.



.. _post-send-signal:

Post-send signal
----------------

You can use Anymail's :data:`~anymail.signals.post_send` signal to examine
messages after they are sent. This is useful to centralize handling of
the :ref:`sent status <esp-send-status>` for all messages.

For example, you could implement your own ESP logging dashboard
(perhaps combined with Anymail's :ref:`event-tracking webhooks <event-tracking>`):

.. code-block:: python

    from anymail.signals import post_send
    from django.dispatch import receiver

    from your_app.models import SentMessage

    @receiver(post_send)
    def log_sent_message(sender, message, status, esp_name, **kwargs):
        # This assumes you've implemented a SentMessage model for tracking sends.
        # status.recipients is a dict of email: status for each recipient
        for email, recipient_status in status.recipients.items():
            SentMessage.objects.create(
                esp=esp_name,
                message_id=recipient_status.message_id,  # might be None if send failed
                email=email,
                subject=message.subject,
                status=recipient_status.status,  # 'sent' or 'rejected' or ...
            )


.. data:: anymail.signals.post_send

    Signal delivered after each EmailMessage is sent.

    If you register multiple post-send receivers, Anymail will ensure that
    all of them are called, even if one raises an error.

    Your post_send receiver must be a function with this signature:

    .. function:: def my_post_send_handler(sender, message, status, esp_name, **kwargs):

       (You can name it anything you want.)

       :param class sender:
           The Anymail backend class processing the message.
           This parameter is required by Django's signal mechanism,
           and despite the name has nothing to do with the *email message's* sender.
           (You generally won't need to examine this parameter.)
       :param ~django.core.mail.EmailMessage message:
           The message that was sent. You should not modify this in a post-send receiver.
       :param ~anymail.message.AnymailStatus status:
           The normalized response from the ESP send call. (Also available as
           :attr:`message.anymail_status <anymail.message.AnymailMessage.anymail_status>`.)
       :param str esp_name:
           The name of the ESP backend in use (e.g., "Amazon SES" or "Mailgun").
       :param \**kwargs:
           Required by Django's signal mechanism (to support future extensions).
