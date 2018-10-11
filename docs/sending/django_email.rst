.. currentmodule:: anymail

.. _sending-django-email:

Django email support
====================

Anymail builds on Django's core email functionality. If you are already sending
email using Django's default SMTP :class:`~django.core.mail.backends.smtp.EmailBackend`,
switching to Anymail will be easy. Anymail is designed to "just work" with Django.

If you're not familiar with Django's email functions, please take a look at
":mod:`sending email <django.core.mail>`" in the Django docs first.

Anymail supports most of the functionality of Django's :class:`~django.core.mail.EmailMessage`
and :class:`~django.core.mail.EmailMultiAlternatives` classes.

Anymail handles **all** outgoing email sent through Django's
:mod:`django.core.mail` module, including :func:`~django.core.mail.send_mail`,
:func:`~django.core.mail.send_mass_mail`, the :class:`~django.core.mail.EmailMessage` class,
and even :func:`~django.core.mail.mail_admins`.
If you'd like to selectively send only some messages through Anymail,
or you'd like to use different ESPs for particular messages,
there are ways to use :ref:`multiple email backends <multiple-backends>`.


.. _sending-html:

HTML email
----------

To send an HTML message, you can simply use Django's :func:`~django.core.mail.send_mail`
function with the ``html_message`` parameter:

    .. code-block:: python

        from django.core.mail import send_mail

        send_mail("Subject", "text body", "from@example.com",
                  ["to@example.com"], html_message="<html>html body</html>")

However, many Django email capabilities -- and additional Anymail features --
are only available when working with an :class:`~django.core.mail.EmailMultiAlternatives`
object. Use its :meth:`~django.core.mail.EmailMultiAlternatives.attach_alternative`
method to send HTML:

    .. code-block:: python

        from django.core.mail import EmailMultiAlternatives

        msg = EmailMultiAlternatives("Subject", "text body",
                                     "from@example.com", ["to@example.com"])
        msg.attach_alternative("<html>html body</html>", "text/html")
        # you can set any other options on msg here, then...
        msg.send()

It's good practice to send equivalent content in your plain-text body
and the html version.


.. _sending-attachments:

Attachments
-----------

Anymail will send a message's attachments to your ESP. You can add attachments
with the :meth:`~django.core.mail.EmailMessage.attach` or
:meth:`~django.core.mail.EmailMessage.attach_file` methods
of Django's :class:`~django.core.mail.EmailMessage`.

Note that some ESPs impose limits on the size and type of attachments they
will send.

.. rubric:: Inline images

If your message has any attachments with :mailheader:`Content-Disposition: inline`
headers, Anymail will tell your ESP to treat them as inline rather than ordinary
attached files. If you want to reference an attachment from an `<img>` in your
HTML source, the attachment also needs a :mailheader:`Content-ID` header.

Anymail comes with :func:`~message.attach_inline_image` and
:func:`~message.attach_inline_image_file` convenience functions that
do the right thing. See :ref:`inline-images` in the "Anymail additions" section.

(If you prefer to do the work yourself, Python's :class:`~email.mime.image.MIMEImage`
and :meth:`~email.message.Message.add_header` should be helpful.)

Even if you mark an attachment as inline, some email clients may decide to also
display it as an attachment. This is largely outside your control.

.. versionchanged:: 4.3

    For convenience, Anymail will treat an attachment with a :mailheader:`Content-ID`
    but no :mailheader:`Content-Disposition` as inline. (Many---though not all---email
    clients make the same assumption. But to ensure consistent behavior with non-Anymail
    email backends, you should always set *both* :mailheader:`Content-ID` and
    :mailheader:`Content-Disposition: inline` headers for inline images. Or just use
    Anymail's :ref:`inline image helpers <inline-images>`, which handle this for you.)


.. _message-headers:

Additional headers
------------------

Anymail passes additional headers to your ESP. (Some ESPs may limit
which headers they'll allow.) EmailMessage expects a `dict` of headers:

    .. code-block:: python

        # Use `headers` when creating an EmailMessage
        msg = EmailMessage( ...
            headers={
                "List-Unsubscribe": unsubscribe_url,
                "X-Example-Header": "myapp",
            }
        )

        # Or use the `extra_headers` attribute later
        msg.extra_headers["In-Reply-To"] = inbound_msg["Message-ID"]

Anymail treats header names as case-*insensitive* (because that's how email handles them).
If you supply multiple headers that differ only in case, only one of them will make it
into the resulting email.

Django's default :class:`SMTP EmailBackend <django.core.mail.backends.smtp.EmailBackend>`
has special handling for certain headers. Anymail replicates its behavior for compatibility:

.. Django doesn't doc EmailMessage :attr:`to`, :attr:`from_email`, etc. So just link to
   the :class:`EmailMessage` docs to refer to them.

* If you supply a "Reply-To" header, it will *override* the message's
  :class:`reply_to <django.core.mail.EmailMessage>` attribute.

* If you supply a "From" header, it will override the message's
  :class:`from_email <django.core.mail.EmailMessage>` and become the :mailheader:`From` field the
  recipient sees. In addition, the original :class:`from_email <django.core.mail.EmailMessage>` value
  will be used as the message's :attr:`~anymail.message.AnymailMessage.envelope_sender`, which becomes
  the :mailheader:`Return-Path` at the recipient end. (Only if your ESP supports altering envelope
  sender, otherwise you'll get an :ref:`unsupported feature <unsupported-features>` error.)

* If you supply a "To" header, you'll usually get an :ref:`unsupported feature <unsupported-features>` error.
  With Django's SMTP EmailBackend, this can be used to show the recipient a :mailheader:`To` address
  that's different from the actual envelope recipients in the message's
  :class:`to <django.core.mail.EmailMessage>` list. Spoofing the :mailheader:`To` header like this
  is popular with spammers, and almost none of Anymail's supported ESPs allow it.

.. versionchanged:: 2.0

    Improved header-handling compatibility with Django's SMTP EmailBackend.


.. _unsupported-features:

Unsupported features
--------------------

Some email capabilities aren't supported by all ESPs. When you try to send a
message using features Anymail can't communicate to the current ESP, you'll get an
:exc:`~exceptions.AnymailUnsupportedFeature` error, and the message won't be sent.

For example, very few ESPs support alternative message parts added with
:meth:`~django.core.mail.EmailMultiAlternatives.attach_alternative`
(other than a single :mimetype:`text/html` part that becomes the HTML body).
If you try to send a message with other alternative parts, Anymail will
raise :exc:`~exceptions.AnymailUnsupportedFeature`.

.. setting:: ANYMAIL_IGNORE_UNSUPPORTED_FEATURES

If you'd like to silently ignore :exc:`~exceptions.AnymailUnsupportedFeature`
errors and send the messages anyway, set :setting:`!ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`
to `True` in your settings.py:

  .. code-block:: python

      ANYMAIL = {
          ...
          "IGNORE_UNSUPPORTED_FEATURES": True,
      }


.. _recipients-refused:

Refused recipients
------------------

If *all* recipients (to, cc, bcc) of a message are invalid or rejected by
your ESP *at send time,* the send call will raise an
:exc:`~exceptions.AnymailRecipientsRefused` error.

You can examine the message's :attr:`~message.AnymailMessage.anymail_status`
attribute to determine the cause of the error. (See :ref:`esp-send-status`.)

If a single message is sent to multiple recipients, and *any* recipient is valid
(or the message is queued by your ESP because of rate limiting or
:attr:`~message.AnymailMessage.send_at`), then this exception will not be raised.
You can still examine the message's :attr:`~message.AnymailMessage.anymail_status`
property after the send to determine the status of each recipient.

You can disable this exception by setting :setting:`ANYMAIL_IGNORE_RECIPIENT_STATUS`
to `True` in your settings.py, which will cause Anymail to treat any non-API-error response
from your ESP as a successful send.

.. note::

    Many ESPs don't check recipient status during the send API call. For example,
    Mailgun always queues sent messages, so you'll never catch
    :exc:`AnymailRecipientsRefused` with the Mailgun backend.

    For those ESPs, use Anymail's :ref:`delivery event tracking <event-tracking>`
    if you need to be notified of sends to blacklisted or invalid emails.
