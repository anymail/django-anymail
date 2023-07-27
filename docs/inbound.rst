.. _inbound:

Receiving mail
==============

For ESPs that support receiving inbound email, Anymail offers normalized handling
of inbound events.

If you didn't set up webhooks when first installing Anymail, you'll need to
:ref:`configure webhooks <webhooks-configuration>` to get started with inbound email.
(You should also review :ref:`securing-webhooks`.)

Once you've enabled webhooks, Anymail will send a ``anymail.signals.inbound``
custom Django :doc:`signal <django:topics/signals>` for each ESP inbound message it receives.
You can connect your own receiver function to this signal for further processing.
(This is very much like how Anymail handles :ref:`status tracking <event-tracking>`
events for sent messages. Inbound events just use a different signal receiver
and have different event parameters.)

Be sure to read Django's :doc:`listening to signals <django:topics/signals>` docs
for information on defining and connecting signal receivers.

Example:

.. code-block:: python

    from anymail.signals import inbound
    from django.dispatch import receiver

    @receiver(inbound)  # add weak=False if inside some other function/class
    def handle_inbound(sender, event, esp_name, **kwargs):
        message = event.message
        print("Received message from %s (envelope sender %s) with subject '%s'" % (
              message.from_email, message.envelope_sender, message.subject))

Some ESPs batch up multiple inbound messages into a single webhook call. Anymail will
invoke your signal receiver once, separately, for each message in the batch.

.. _inbound-security:

.. warning:: **Be careful with inbound email**

    Inbound email is user-supplied content. There are all kinds of ways a
    malicious sender can abuse the email format to give your app misleading
    or dangerous data. Treat inbound email content with the same suspicion
    you'd apply to any user-submitted data. Among other concerns:

    * Senders can spoof the From header. An inbound message's
      :attr:`~anymail.inbound.AnymailInboundMessage.from_email` may
      or may not match the actual address that sent the message. (There are both
      legitimate and malicious uses for this capability.)

    * Most other fields in email can be falsified. E.g., an inbound message's
      :attr:`~anymail.inbound.AnymailInboundMessage.date` may or may not accurately
      reflect when the message was sent.

    * Inbound attachments have the same security concerns as user-uploaded files.
      If you process inbound attachments, you'll need to verify that the
      attachment content is valid.

      This is particularly important if you publish the attachment content
      through your app. For example, an "image" attachment could actually contain an
      executable file or raw HTML. You wouldn't want to serve that as a user's avatar.

      It's *not* sufficient to check the attachment's content-type or
      filename extension---senders can falsify both of those.
      Consider `using python-magic`_ or a similar approach
      to validate the *actual attachment content*.

    The Django docs have additional notes on
    :ref:`user-supplied content security <django:user-uploaded-content-security>`.

.. _using python-magic:
   https://blog.hayleyanderson.us/2015/07/18/validating-file-types-in-django/


.. _inbound-event:

Normalized inbound event
------------------------

.. class:: anymail.signals.AnymailInboundEvent

    The `event` parameter to Anymail's `inbound`
    :ref:`signal receiver <inbound-signal-receivers>` is an object
    with the following attributes:

    .. attribute:: message

        An :class:`~anymail.inbound.AnymailInboundMessage` representing the email
        that was received. Most of what you're interested in will be on this :attr:`!message`
        attribute. See the full details :ref:`below <inbound-message>`.

    .. attribute:: event_type

        A normalized `str` identifying the type of event. For inbound events,
        this is always `'inbound'`.

    .. attribute:: timestamp

        A `~datetime.datetime` indicating when the inbound event was generated
        by the ESP, if available; otherwise `None`. (Very few ESPs provide this info.)

        This is typically when the ESP received the message or shortly
        thereafter. (Use :attr:`event.message.date <anymail.inbound.AnymailInboundMessage.date>`
        if you're interested in when the message was sent.)

        (The timestamp's timezone is often UTC, but the exact behavior depends
        on your ESP and account settings. Anymail ensures that this value is
        an *aware* datetime with an accurate timezone.)

    .. attribute:: event_id

        A `str` unique identifier for the event, if available; otherwise `None`.
        Can be used to avoid processing the same event twice. The exact format varies
        by ESP, and very few ESPs provide an event_id for inbound messages.

        An alternative approach to avoiding duplicate processing is to use the
        inbound message's :mailheader:`Message-ID` header (``event.message['Message-ID']``).

    .. attribute:: esp_event

        The "raw" event data from the ESP, deserialized into a python data structure.
        For most ESPs this is either parsed JSON (as a `dict`), or sometimes the
        complete Django :class:`~django.http.HttpRequest` received by the webhook.

        This gives you (non-portable) access to original event provided by your ESP,
        which can be helpful if you need to access data Anymail doesn't normalize.


.. _inbound-message:

Normalized inbound message
--------------------------

.. class:: anymail.inbound.AnymailInboundMessage

    The :attr:`~AnymailInboundEvent.message` attribute of an :class:`AnymailInboundEvent`
    is an AnymailInboundMessage---an extension of Python's standard :class:`email.message.EmailMessage`
    with additional features to simplify inbound handling.

    .. versionchanged:: 10.1

        Earlier releases extended Python's legacy :class:`email.message.Message` class.
        :class:`~email.message.EmailMessage` is a superset that fixes bugs and improves
        compatibility with email standards.

    In addition to the base :class:`~email.message.EmailMessage` functionality,
    :class:`!AnymailInboundMessage` includes these attributes:

    .. attribute:: envelope_sender

        The actual sending address of the inbound message, as determined by your ESP.
        This is a `str` "addr-spec"---just the email address portion without any display
        name (``"sender@example.com"``)---or `None` if the ESP didn't provide a value.

        The envelope sender often won't match the message's From header---for example,
        messages sent on someone's behalf (mailing lists, invitations) or when a spammer
        deliberately falsifies the From address.

    .. attribute:: envelope_recipient

        The actual destination address the inbound message was delivered to.
        This is a `str` "addr-spec"---just the email address portion without any display
        name (``"recipient@example.com"``)---or `None` if the ESP didn't provide a value.

        The envelope recipient may not appear in the To or Cc recipient lists---for example,
        if your inbound address is bcc'd on a message.

    .. attribute:: from_email

        The value of the message's From header. Anymail converts this to an
        :class:`~anymail.utils.EmailAddress` object, which makes it easier to access
        the parsed address fields:

        .. code-block:: pycon

            >>> str(message.from_email)  # the fully-formatted address
            '"Dr. Justin Customer, CPA" <jcustomer@example.com>'
            >>> message.from_email.addr_spec  # the "email" portion of the address
            'jcustomer@example.com'
            >>> message.from_email.display_name  # empty string if no display name
            'Dr. Justin Customer, CPA'
            >>> message.from_email.domain
            'example.com'
            >>> message.from_email.username
            'jcustomer'

        (This API is borrowed from Python 3.6's :class:`email.headerregistry.Address`.)

        If the message has an invalid or missing From header, this property will be `None`.
        Note that From headers can be misleading; see :attr:`envelope_sender`.

    .. attribute:: to

        A `list` of of parsed :class:`~anymail.utils.EmailAddress` objects from the To header,
        or an empty list if that header is missing or invalid. Each address in the list
        has the same properties as shown above for :attr:`from_email`.

        See :attr:`envelope_recipient` if you need to know the actual inbound address
        that received the inbound message.

    .. attribute:: cc

        A `list` of of parsed :class:`~anymail.utils.EmailAddress` objects, like :attr:`to`,
        but from the Cc headers.

    .. attribute:: subject

        The value of the message's Subject header, as a `str`, or `None` if there is no Subject
        header.

    .. attribute:: date

        The value of the message's Date header, as a `~datetime.datetime` object, or `None`
        if the Date header is missing or invalid. This attribute will almost always be an
        aware datetime (with a timezone); in rare cases it can be naive if the sending mailer
        indicated that it had no timezone information available.

        The Date header is the sender's claim about when it sent the message, which isn't
        necessarily accurate. (If you need to know when the message was received at your ESP,
        that might be available in :attr:`event.timestamp <anymail.signals.AnymailInboundEvent.timestamp>`.
        If not, you'd need to parse the messages's :mailheader:`Received` headers,
        which can be non-trivial.)

    .. attribute:: text

        The message's plaintext message body as a `str`, or `None` if the
        message doesn't include a plaintext body.

        For certain messages that are sent as plaintext with inline images
        (such as those sometimes composed by the Apple Mail app), this will
        include only the text before the first inline image.

    .. attribute:: html

        The message's HTML message body as a `str`, or `None` if the
        message doesn't include an HTML body.

    .. attribute:: attachments

        A `list` of all attachments to the message, or an empty list if there are
        no attachments. See :ref:`inbound-attachments` below a description of the values.

        If the inbound message includes an attached message, :attr:`!attachments`
        will include the attached message and all of *its* attachments, recursively.
        Consider Python's :meth:`~email.message.EmailMessage.iter_attachments` as an
        alternative that doesn't descend into attached messages.

    .. attribute:: inlines

        A `list` of all inline content parts in the message, or an empty list if none.
        See :ref:`inbound-attachments` below for a description of the values.

        Like :attr:`attachments`, this will recursively descend into any attached messages.

        .. versionadded:: 10.1

    .. attribute:: content_id_map

        A `dict` mapping inline Content-ID references to inline content. Each key is an
        "unquoted" cid without angle brackets. E.g., if the :attr:`html` body contains
        ``<img src="cid:abc123...">``, you could get that inline image using
        ``message.content_id_map["abc123..."]``.

        The value of each item is described in :ref:`inbound-attachments` below.

        .. versionadded:: 10.1

            This property was previously available as :attr:`!inline_attachments`.
            The old name still works, but is deprecated.

    .. attribute:: spam_score

        A `float` spam score (usually from SpamAssassin) if your ESP provides it; otherwise `None`.
        The range of values varies by ESP and spam-filtering configuration, so you may need to
        experiment to find a useful threshold.

    .. attribute:: spam_detected

        If your ESP provides a simple yes/no spam determination, a `bool` indicating whether the
        ESP thinks the inbound message is probably spam. Otherwise `None`. (Most ESPs just assign
        a :attr:`spam_score` and leave its interpretation up to you.)

    .. attribute:: stripped_text

        If provided by your ESP, a simplified version the inbound message's plaintext body;
        otherwise `None`.

        What exactly gets "stripped" varies by ESP, but it often omits quoted replies
        and sometimes signature blocks. (And ESPs who do offer stripped bodies
        usually consider the feature experimental.)

    .. attribute:: stripped_html

        Like :attr:`stripped_text`, but for the HTML body. (Very few ESPs support this.)

    .. rubric:: Other headers, complex messages, etc.

    You can use all of Python's :class:`email.message.EmailMessage` features with an
    AnymailInboundMessage. For example, you can access message headers using
    EmailMessage's :meth:`mapping interface <email.message.EmailMessage.__getitem__>`:

    .. code-block:: python

        message['reply-to']  # the Reply-To header (header keys are case-insensitive)
        message.getall('DKIM-Signature')  # list of all DKIM-Signature headers

    And you can use Message methods like :meth:`~email.message.EmailMessage.walk` and
    :meth:`~email.message.EmailMessage.get_content_type` to examine more-complex
    multipart MIME messages (digests, delivery reports, or whatever).


.. _inbound-attachments:

Attached and inline content
---------------------------

Anymail converts each inbound attachment and inline content to a specialized MIME object with
additional methods for handling attachments and integrating with Django.

The objects in an AnymailInboundMessage's
:attr:`~anymail.inbound.AnymailInboundMessage.attachments`,
:attr:`~anymail.inbound.AnymailInboundMessage.inlines`,
and :attr:`~anymail.inbound.AnymailInboundMessage.content_id_map`
have these methods:

.. class:: AnymailInboundMessage

    .. method:: as_uploaded_file()

        Returns the content converted to a Django :class:`~django.core.files.uploadedfile.UploadedFile`
        object. This is suitable for assigning to a model's :class:`~django.db.models.FileField`
        or :class:`~django.db.models.ImageField`:

        .. code-block:: python

            # allow users to mail in jpeg attachments to set their profile avatars...
            if attachment.get_content_type() == "image/jpeg":
                # for security, you must verify the content is really a jpeg
                # (you'll need to supply the is_valid_jpeg function)
                if is_valid_jpeg(attachment.get_content_bytes()):
                    user.profile.avatar_image = attachment.as_uploaded_file()

        See Django's docs on :doc:`django:topics/files` for more information
        on working with uploaded files.

    .. method:: get_content_type()
    .. method:: get_content_maintype()
    .. method:: get_content_subtype()

        The type of attachment content, as specified by the sender. (But remember
        attachments are essentially user-uploaded content, so you should
        :ref:`never trust the sender <inbound-security>`.)

        See the Python docs for more info on :meth:`email.message.EmailMessage.get_content_type`,
        :meth:`~email.message.EmailMessage.get_content_maintype`, and
        :meth:`~email.message.EmailMessage.get_content_subtype`.

        (Note that you *cannot* determine the attachment type using code like
        ``issubclass(attachment, email.mime.image.MIMEImage)``. You should instead use something
        like ``attachment.get_content_maintype() == 'image'``. The email package's specialized
        MIME subclasses are designed for constructing new messages, and aren't used
        for parsing existing, inbound email messages.)

    .. method:: get_filename()

        The original filename of the attachment, as specified by the sender.

        *Never* use this filename directly to write files---that would be a huge security hole.
        (What would your app do if the sender gave the filename "/etc/passwd" or "../settings.py"?)

    .. method:: is_attachment()

        Returns `True` for attachment content (with :mailheader:`Content-Disposition` "attachment"),
        `False` otherwise.

    .. method:: is_inline()

        Returns `True` for inline content (with :mailheader:`Content-Disposition` "inline"),
        `False` otherwise.

        .. versionchanged:: 10.1

            This method was previously named :meth:`!is_inline_attachment`;
            the old name still works, but is deprecated.

    .. method:: get_content_disposition()

        Returns the lowercased value (without parameters) of the attachment's
        :mailheader:`Content-Disposition` header. The return value should be either "inline"
        or "attachment", or `None` if the attachment is somehow missing that header.

    .. method:: get_content_text(charset=None, errors='replace')

        Returns the content of the attachment decoded to Unicode text.
        (This is generally only appropriate for text or message-type attachments.)

        If provided, charset will override the attachment's declared charset. (This can be useful
        if you know the attachment's :mailheader:`Content-Type` has a missing or incorrect charset.)

        The errors param is as in :meth:`~bytes.decode`. The default "replace" substitutes the
        Unicode "replacement character" for any illegal characters in the text.

    .. method:: get_content_bytes()

        Returns the raw content of the attachment as bytes. (This will automatically decode
        any base64-encoded attachment data.)

    .. rubric:: Complex attachments

    An Anymail inbound attachment is actually just an :class:`AnymailInboundMessage` instance,
    following the Python email package's usual recursive representation of MIME messages.
    All :class:`AnymailInboundMessage` and :class:`email.message.EmailMessage` functionality
    is available on attachment objects (though of course not all features are meaningful in all contexts).

    This can be helpful for, e.g., parsing email messages that are forwarded as attachments
    to an inbound message.


Anymail loads all attachment content into memory as it processes each inbound
message. This may limit the size of attachments your app can handle, beyond
any attachment size limits imposed by your ESP. Depending on how your ESP transmits
attachments, you may also need to adjust Django's :setting:`DATA_UPLOAD_MAX_MEMORY_SIZE`
setting to successfully receive larger attachments.


.. _inbound-signal-receivers:

Inbound signal receiver functions
---------------------------------

Your Anymail inbound signal receiver must be a function with this signature:

.. function:: def my_handler(sender, event, esp_name, **kwargs):

   (You can name it anything you want.)

   :param class sender: The source of the event. (One of the
                        :mod:`anymail.webhook.*` View classes, but you
                        generally won't examine this parameter; it's
                        required by Django's signal mechanism.)
   :param AnymailInboundEvent event: The normalized inbound event.
                                     Almost anything you'd be interested in
                                     will be in here---usually in the
                                     :class:`~anymail.inbound.AnymailInboundMessage`
                                     found in `event.message`.
   :param str esp_name: e.g., "SendMail" or "Postmark". If you are working
                        with multiple ESPs, you can use this to distinguish
                        ESP-specific handling in your shared event processing.
   :param \**kwargs: Required by Django's signal mechanism
                     (to support future extensions).

   :returns: nothing
   :raises: any exceptions in your signal receiver will result
            in a 400 HTTP error to the webhook. See discussion
            below.

.. TODO: this section is almost exactly duplicated from tracking. Combine somehow?

If (any of) your signal receivers raise an exception, Anymail
will discontinue processing the current batch of events and return
an HTTP 400 error to the ESP. Most ESPs respond to this by re-sending
the event(s) later, a limited number of times.

This is the desired behavior for transient problems (e.g., your
Django database being unavailable), but can cause confusion in other
error cases. You may want to catch some (or all) exceptions
in your signal receiver, log the problem for later follow up,
and allow Anymail to return the normal 200 success response
to your ESP.

Some ESPs impose strict time limits on webhooks, and will consider
them failed if they don't respond within (say) five seconds.
And they may then retry sending these "failed" events, which could
cause duplicate processing in your code.
If your signal receiver code might be slow, you should instead
queue the event for later, asynchronous processing (e.g., using
something like :pypi:`celery`).

If your signal receiver function is defined within some other
function or instance method, you *must* use the `weak=False`
option when connecting it. Otherwise, it might seem to work at first,
but will unpredictably stop being called at some point---typically
on your production server, in a hard-to-debug way. See Django's
docs on :doc:`signals <django:topics/signals>` for more information.
