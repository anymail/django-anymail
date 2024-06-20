.. module:: anymail.message

.. _anymail-send-features:

Anymail additions
=================

Anymail normalizes several common ESP features, like adding
metadata or tags to a message. It also normalizes the response
from the ESP's send API.

There are three ways you can use Anymail's ESP features with
your Django email:

* Just use Anymail's added attributes directly on *any* Django
  :class:`~django.core.mail.EmailMessage` object (or any subclass).

* Create your email message using the :class:`AnymailMessage` class,
  which exposes extra attributes for the ESP features.

* Use the :class:`AnymailMessageMixin` to add the Anymail extras
  to some other EmailMessage-derived class (your own or from
  another Django package).

The first approach is usually the simplest. The other two can be
helpful if you are working with Python development tools that
offer type checking or other static code analysis.


.. _anymail-send-options:

ESP send options (AnymailMessage)
---------------------------------

Availability of each of these features varies by ESP, and there may be additional
limitations even when an ESP does support a particular feature. Be sure
to check Anymail's docs for your :ref:`specific ESP <supported-esps>`.
If you try to use a feature your ESP does not offer, Anymail will raise
an :ref:`unsupported feature <unsupported-features>` error.

.. class:: AnymailMessage

    A subclass of Django's :class:`~django.core.mail.EmailMultiAlternatives`
    that exposes additional ESP functionality.

    The constructor accepts any of the attributes below, or you can set
    them directly on the message at any time before sending:

    .. code-block:: python

        from anymail.message import AnymailMessage

        message = AnymailMessage(
            subject="Welcome",
            body="Welcome to our site",
            to=["New User <user1@example.com>"],
            tags=["Onboarding"],  # Anymail extra in constructor
        )
        # Anymail extra attributes:
        message.metadata = {"onboarding_experiment": "variation 1"}
        message.track_clicks = True

        message.send()
        status = message.anymail_status  # available after sending
        status.message_id  # e.g., '<12345.67890@example.com>'
        status.recipients["user1@example.com"].status  # e.g., 'queued'


    .. rubric:: Attributes you can add to messages

    .. note::

        Anymail looks for these attributes on **any**
        :class:`~django.core.mail.EmailMessage` you send.
        (You don't have to use :class:`AnymailMessage`.)

    .. attribute:: envelope_sender

        Set this to a `str` email address that should be used as the message's
        envelope sender. If supported by your ESP, this will become the Return-Path
        in the recipient's mailbox.

        (Envelope sender is also known as bounce address, MAIL FROM, envelope from,
        unixfrom, SMTP FROM command, return path, and `several other terms`_. Confused?
        Here's some good info on `how envelope sender relates to return path`_.)

        ESP support for envelope sender varies widely. Be sure to check Anymail's
        docs for your :ref:`specific ESP <supported-esps>` before attempting to use it.
        And note that those ESPs who do support it will often use only the domain
        portion of the envelope sender address, overriding the part before the @ with
        their own encoded bounce mailbox.

        [The :attr:`!envelope_sender` attribute is unique to Anymail. If you also use Django's
        SMTP EmailBackend, you can portably control envelope sender by *instead* setting
        ``message.extra_headers["From"]`` to the desired email *header* :mailheader:`From`,
        and ``message.from_email`` to the *envelope sender*. Anymail also allows this approach,
        for compatibility with the SMTP EmailBackend. See the notes `in Django's bug tracker`_.]

        .. _several other terms: https://en.wikipedia.org/wiki/Bounce_address
        .. _in Django's bug tracker: https://code.djangoproject.com/ticket/9214
        .. _how envelope sender relates to return path:
            https://www.postmastery.com/blog/about-the-return-path-header/

    .. attribute:: merge_headers

        .. versionadded:: 11.0

        On a message with multiple recipients, if your ESP supports it,
        you can set this to a `dict` of *per-recipient* extra email headers.
        Each key in the dict is a recipient email (address portion only),
        and its value is a dict of header fields and values for that recipient:

        .. code-block:: python

            message.to = ["wile@example.com", "R. Runner <rr@example.com>"]
            message.extra_headers = {
                # Headers for all recipients
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
            message.merge_headers = {
                # Per-recipient headers
                "wile@example.com": {
                    "List-Unsubscribe": "<https://example.com/unsubscribe/12345>",
                },
                "rr@example.com": {
                    "List-Unsubscribe": "<https://example.com/unsubscribe/98765>",
                },
            }

        When :attr:`!merge_headers` is set, Anymail will use the ESP's
        :ref:`batch sending <batch-send>` option, so that each :attr:`to` recipient gets
        an individual message (and doesn't see the other emails on the :attr:`to` list).

        Many ESPs restrict which headers are allowed. Be sure to check Anymail's
        :ref:`ESP-specific docs <supported-esps>` for your ESP.
        (Also, :ref:`special handling <message-headers>` for :mailheader:`From`,
        :mailheader:`To` and :mailheader:`Reply-To` headers does *not* apply
        to :attr:`!merge_headers`.)

        If :attr:`!merge_headers` defines a particular header for only some
        recipients, the default for other recipients comes from the message's
        :ref:`extra_headers <message-headers>`. If not defined there, behavior
        varies by ESP: some will include the header field only for recipients
        where you have provided it; other ESPs will send an empty header field
        to the other recipients.

    .. attribute:: metadata

        If your ESP supports tracking arbitrary metadata, you can set this to
        a `dict` of metadata values the ESP should store with the message, for
        later search and retrieval. This can be useful with Anymail's
        :ref:`status tracking <event-tracking>` webhooks.

        .. code-block:: python

            message.metadata = {"customer": customer.id,
                                "order": order.reference_number}

        ESPs have differing restrictions on metadata content.
        For portability, it's best to stick to alphanumeric keys, and values
        that are numbers or strings.

        You should format any non-string data into a string before setting it
        as metadata. See :ref:`formatting-merge-data`.

        Depending on the ESP, this metadata **could be exposed to the recipients**
        in the message headers, so don't include sensitive data.


    .. attribute:: merge_metadata

        On a message with multiple recipients, if your ESP supports it, you can
        set this to a `dict` of *per-recipient* metadata values the ESP should store
        with the message, for later search and retrieval. Each key in the dict is a
        recipient email (address portion only), and its value is a dict of metadata
        for that recipient:

        .. code-block:: python

            message.to = ["wile@example.com", "Mr. Runner <rr@example.com>"]
            message.merge_metadata = {
                "wile@example.com": {"customer": 123, "order": "acme-zxyw"},
                "rr@example.com": {"customer": 45678, "order": "acme-wblt"},
            }

        When :attr:`!merge_metadata` is set, Anymail will use the ESP's
        :ref:`batch sending <batch-send>` option, so that each `to` recipient gets an
        individual message (and doesn't see the other emails on the `to` list).

        All of the notes on :attr:`metadata` keys and value formatting also apply
        to :attr:`!merge_metadata`. If there are conflicting keys, the
        :attr:`!merge_metadata` values will take precedence over :attr:`!metadata`
        for that recipient.

        Depending on the ESP, this metadata **could be exposed to the recipients**
        in the message headers, so don't include sensitive data.


    .. attribute:: tags

        If your ESP supports it, you can set this to a `list` of `str` tags to apply
        to the message. This can be useful for segmenting your ESP's reports, and is
        also often used with Anymail's :ref:`status tracking <event-tracking>` webhooks.

        .. code-block:: python

            message.tags = ["Order Confirmation", "Test Variant A"]

        ESPs have differing restrictions on tags. For portability,
        it's best to stick with strings that start with an alphanumeric
        character. (Also, a few ESPs allow only a single tag per message.)


    .. caution::

        Some ESPs put :attr:`metadata` (and a recipient's :attr:`merge_metadata`)
        and :attr:`tags` in email headers,
        which are included with the email when it is delivered. Anything you
        put in them **could be exposed to the recipients,** so don't
        include sensitive data.


    .. attribute:: track_opens

        If your ESP supports open tracking, you can set this to `True` or `False`
        to override your ESP's default for this particular message. (Most ESPs let you
        configure open tracking defaults at the account or sending domain level.)

        For example, if you have configured your ESP to *not* insert open tracking
        pixels by default, this will attempt to enable that for this one message:

        .. code-block:: python

            message.track_opens = True


    .. attribute:: track_clicks

        If your ESP supports click tracking, you can set this to `True` or `False`
        to override your ESP's default for this particular message. (Most ESPs let you
        configure click tracking defaults at the account or sending domain level.)

        For example, if you have configured your ESP to normally rewrite links to add
        click tracking, this will attempt to disable that for this one message:

        .. code-block:: python

            message.track_clicks = False


    .. attribute:: send_at

        If your ESP supports scheduled transactional sending, you can set this to a
        `~datetime.datetime` to have the ESP delay sending the message until the
        specified time. (You can also use a `float` or `int`, which will be treated
        as a POSIX timestamp as in :func:`time.time`.)

        .. code-block:: python

            from datetime import datetime, timedelta, timezone

            message.send_at = datetime.now(timezone.utc) + timedelta(hours=1)

        To avoid confusion, it's best to provide either an *aware*
        `~datetime.datetime` (one that has its tzinfo set), or an
        `int` or `float` seconds-since-the-epoch timestamp.

        If you set :attr:`!send_at` to a `~datetime.date` or a *naive*
        `~datetime.datetime` (without a timezone), Anymail will interpret it in
        Django's :ref:`current timezone <django:default-current-time-zone>`.
        (Careful: :meth:`datetime.now() <datetime.datetime.now>` returns a *naive*
        datetime, unless you call it with a timezone like in the example above.)

        The sent message will be held for delivery by your ESP -- not locally by Anymail.


    .. attribute:: esp_extra

      Although Anymail normalizes common ESP features, many ESPs offer additional
      functionality that doesn't map neatly to Anymail's standard options. You can
      use :attr:`!esp_extra` as an "escape hatch" to access ESP functionality that
      Anymail doesn't (or doesn't yet) support.

      Set it to a `dict` of additional, ESP-specific settings for the message.
      See the notes for each :ref:`specific ESP <supported-esps>` for information
      on its :attr:`!esp_extra` handling.

      Using this attribute is inherently non-portable between ESPs, so it's best to
      avoid it unless absolutely necessary. If you ever want to switch ESPs, you will
      need to update or remove all uses of :attr:`!esp_extra` to avoid unexpected behavior.


    .. rubric:: Status response from the ESP

    .. attribute:: anymail_status

        Normalized response from the ESP API's send call. Anymail adds this
        to each :class:`~django.core.mail.EmailMessage` as it is sent.

        The value is an :class:`AnymailStatus`.
        See :ref:`esp-send-status` below for details.


    .. rubric:: Convenience methods

    (These methods are only available on :class:`AnymailMessage` or
    :class:`AnymailMessageMixin` objects. Unlike the attributes above,
    they can't be used on an arbitrary :class:`~django.core.mail.EmailMessage`.)

    .. method:: attach_inline_image_file(path, subtype=None, idstring="img", domain=None)

        Attach an inline (embedded) image to the message and return its :mailheader:`Content-ID`.

        This calls :func:`attach_inline_image_file` on the message. See :ref:`inline-images`
        for details and an example.


    .. method:: attach_inline_image(content, filename=None, subtype=None, idstring="img", domain=None)

        Attach an inline (embedded) image to the message and return its :mailheader:`Content-ID`.

        This calls :func:`attach_inline_image` on the message. See :ref:`inline-images`
        for details and an example.


.. _esp-send-status:

ESP send status
---------------

.. class:: AnymailStatus

    When you send a message through an Anymail backend, Anymail adds
    an :attr:`~AnymailMessage.anymail_status` attribute to the
    :class:`~django.core.mail.EmailMessage`, with a normalized version
    of the ESP's response.

    Anymail backends create this attribute *as they process each message.*
    Before that, anymail_status won't be present on an ordinary Django
    EmailMessage or EmailMultiAlternatives---you'll get an :exc:`AttributeError`
    if you try to access it.

    This might cause problems in your test cases, because Django
    :ref:`substitutes its own locmem EmailBackend <django:topics-testing-email>`
    during testing (so anymail_status never gets attached to the EmailMessage).
    If you run into this, you can: change your code to guard against
    a missing anymail_status attribute; switch from using EmailMessage to
    :class:`AnymailMessage` (or the :class:`AnymailMessageMixin`) to ensure the
    anymail_status attribute is always there; or substitute
    :ref:`Anymail's test backend <test-backend>` in any affected test cases.

    After sending through an Anymail backend,
    :attr:`~AnymailMessage.anymail_status` will be an object with these attributes:

    .. attribute:: message_id

        The message id assigned by the ESP, or `None` if the send call failed.

        The exact format varies by ESP. Some use a UUID or similar;
        some use an :rfc:`2822` :mailheader:`Message-ID` as the id:

        .. code-block:: python

            message.anymail_status.message_id
            # '<20160306015544.116301.25145@example.org>'

        Some ESPs assign a unique message ID for *each recipient* (to, cc, bcc)
        of a single message. In that case, :attr:`!message_id` will be a
        `set` of all the message IDs across all recipients:

        .. code-block:: python

            message.anymail_status.message_id
            # set(['16fd2706-8baf-433b-82eb-8c7fada847da',
            #      '886313e1-3b8a-5372-9b90-0c9aee199e5d'])


    .. attribute:: status

        A `set` of send statuses, across all recipients (to, cc, bcc) of the
        message, or `None` if the send call failed.

        .. code-block:: python

            message1.anymail_status.status
            # set(['queued'])  # all recipients were queued
            message2.anymail_status.status
            # set(['rejected', 'sent'])  # at least one recipient was sent,
                                         # and at least one rejected

            # This is an easy way to check there weren't any problems:
            if message3.anymail_status.status.issubset({'queued', 'sent'}):
                print("ok!")

        Anymail normalizes ESP sent status to one of these values:

          * `'sent'` the ESP has sent the message
            (though it may or may not end up delivered)
          * `'queued'` the ESP has accepted the message
            and will try to send it asynchronously
          * `'invalid'` the ESP considers the sender or recipient email invalid
          * `'rejected'` the recipient is on an ESP suppression list
            (unsubscribe, previous bounces, etc.)
          * `'failed'` the attempt to send failed for some other reason
          * `'unknown'` anything else

        Not all ESPs check recipient emails during the send API call -- some
        simply queue the message, and report problems later. In that case,
        you can use Anymail's :ref:`event-tracking` features to be notified
        of delivery status events.


    .. attribute:: recipients

        A `dict` of per-recipient message ID and status values.

        The dict is keyed by each recipient's base email address
        (ignoring any display name). Each value in the dict is
        an object with `status` and `message_id` properties:

        .. code-block:: python

            message = EmailMultiAlternatives(
                to=["you@example.com", "Me <me@example.com>"],
                subject="Re: The apocalypse")
            message.send()

            message.anymail_status.recipients["you@example.com"].status
            # 'sent'
            message.anymail_status.recipients["me@example.com"].status
            # 'queued'
            message.anymail_status.recipients["me@example.com"].message_id
            # '886313e1-3b8a-5372-9b90-0c9aee199e5d'

        Will be an empty dict if the send call failed.


    .. attribute:: esp_response

        The raw response from the ESP API call. The exact type varies by
        backend. Accessing this is inherently non-portable.

        .. code-block:: python

            # This will work with a requests-based backend,
            # for an ESP whose send API provides a JSON response:
            message.anymail_status.esp_response.json()


.. _inline-images:

Inline images
-------------

Anymail includes convenience functions to simplify attaching inline images to email.

These functions work with *any* Django :class:`~django.core.mail.EmailMessage` --
they're not specific to Anymail email backends. You can use them with messages sent
through Django's SMTP backend or any other that properly supports MIME attachments.

(Both functions are also available as convenience methods on Anymail's
:class:`~anymail.message.AnymailMessage` and :class:`~anymail.message.AnymailMessageMixin`
classes.)

.. function:: attach_inline_image_file(message, path, subtype=None, idstring="img", domain=None)

    Attach an inline (embedded) image to the message and return its :mailheader:`Content-ID`.

    In your HTML message body, prefix the returned id with `cid:` to make an
    `<img>` src attribute:

    .. code-block:: python

        from django.core.mail import EmailMultiAlternatives
        from anymail.message import attach_inline_image_file

        message = EmailMultiAlternatives( ... )
        cid = attach_inline_image_file(message, 'path/to/picture.jpg')
        html = '... <img alt="Picture" src="cid:%s"> ...' % cid
        message.attach_alternative(html, 'text/html')

        message.send()


    `message` must be an :class:`~django.core.mail.EmailMessage` (or subclass) object.

    `path` must be the pathname to an image file. (Its basename will also be used as the
    attachment's filename, which may be visible in some email clients.)

    `subtype` is an optional MIME :mimetype:`image` subtype, e.g., `"png"` or `"jpg"`.
    By default, this is determined automatically from the content.

    `idstring` and `domain` are optional, and are passed to Python's
    :func:`~email.utils.make_msgid` to generate the :mailheader:`Content-ID`.
    Generally the defaults should be fine.

    .. versionchanged:: 4.0

        If you don't supply a `domain`, Anymail will use the simple string "inline"
        rather than :func:`~email.utils.make_msgid`'s default local hostname. This
        avoids a problem with ESPs that confuse :mailheader:`Content-ID` and attachment
        filename: if your local server's hostname ends in ".com", Gmail could block
        messages with inline attachments generated by earlier Anymail versions and sent
        through these ESPs.

.. function:: attach_inline_image(message, content, filename=None, subtype=None, idstring="img", domain=None)

    This is a version of :func:`attach_inline_image_file` that accepts raw
    image data, rather than reading it from a file.

    `message` must be an :class:`~django.core.mail.EmailMessage` (or subclass) object.

    `content` must be the binary image data

    `filename` is an optional `str` that will be used as as the attachment's
    filename -- e.g., `"picture.jpg"`. This may be visible in email clients that
    choose to display the image as an attachment as well as making it available
    for inline use (this is up to the email client). It should be a base filename,
    without any path info.

    `subtype`, `idstring` and `domain` are as described in :func:`attach_inline_image_file`


.. _send-defaults:

Global send defaults
--------------------

.. setting:: ANYMAIL_SEND_DEFAULTS

In your :file:`settings.py`, you can set :setting:`!ANYMAIL_SEND_DEFAULTS`
to a `dict` of default options that will apply to all messages sent through Anymail:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SEND_DEFAULTS": {
              "metadata": {"district": "North", "source": "unknown"},
              "tags": ["myapp", "version3"],
              "track_clicks": True,
              "track_opens": True,
          },
      }

At send time, the attributes on each :class:`~django.core.mail.EmailMessage`
get merged with the global send defaults. For example, with the
settings above:

  .. code-block:: python

      message = AnymailMessage(...)
      message.tags = ["welcome"]
      message.metadata = {"source": "Ads", "user_id": 12345}
      message.track_clicks = False

      message.send()
      # will send with:
      #   tags: ["myapp", "version3", "welcome"] (merged with defaults)
      #   metadata: {"district": "North", "source": "Ads", "user_id": 12345} (merged)
      #   track_clicks: False (message overrides defaults)
      #   track_opens: True (from the defaults)

To prevent a message from using a particular global default, set that attribute
to `None`. (E.g., ``message.tags = None`` will send the message with no tags,
ignoring the global default.)

Anymail's send defaults actually work for all :class:`!django.core.mail.EmailMessage`
attributes. So you could set ``"bcc": ["always-copy@example.com"]`` to add a bcc
to every message. (You could even attach a file to every message -- though
your recipients would probably find that annoying!)

You can also set ESP-specific global defaults. If there are conflicts,
the ESP-specific value will override the main `SEND_DEFAULTS`:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SEND_DEFAULTS": {
              "tags": ["myapp", "version3"],
          },
          "POSTMARK_SEND_DEFAULTS": {
              # Postmark only supports a single tag
              "tags": ["version3"],  # overrides SEND_DEFAULTS['tags'] (not merged!)
          },
          "MAILGUN_SEND_DEFAULTS": {
              "esp_extra": {"o:dkim": "no"},  # Disable Mailgun DKIM signatures
          },
      }


AnymailMessageMixin
-------------------

.. class:: AnymailMessageMixin

    Mixin class that adds Anymail's ESP extra attributes and convenience methods
    to other :class:`~django.core.mail.EmailMessage` subclasses.

    For example, with the :pypi:`django-mail-templated` package's custom EmailMessage:

    .. code-block:: python

        from anymail.message import AnymailMessageMixin
        from mail_templated import EmailMessage

        class TemplatedAnymailMessage(AnymailMessageMixin, EmailMessage):
            """
            An EmailMessage that supports both Mail-Templated
            and Anymail features
            """
            pass

        msg = TemplatedAnymailMessage(
            template_name="order_confirmation.tpl",  # Mail-Templated arg
            track_opens=True,  # Anymail arg
            ...
        )
        msg.context = {"order_num": "12345"}  # Mail-Templated attribute
        msg.tags = ["templated"]  # Anymail attribute
