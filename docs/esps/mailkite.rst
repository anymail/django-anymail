.. _mailkite-backend:

MailKite
========

Anymail integrates Django with the `MailKite`_ developer email platform, using
their `send API`_.

MailKite is *inbound-first*: as well as sending transactional mail over a single
JSON API, it also *receives* email — a parsed message body and an authentication
verdict, delivered together as one signed webhook. That makes it a good fit for
support inboxes, reply-to-thread flows, and agent mailboxes without wiring a
second inbound vendor. This backend implements the transactional send API.

.. note::

    This integration covers transactional **sending** and the
    :ref:`inbound webhook <mailkite-inbound>`. Delivery-status (tracking)
    webhook support is planned as a follow-up — please open an issue if you
    need it sooner.

.. _MailKite: https://mailkite.dev/
.. _send API: https://mailkite.dev/docs
.. _MailKite inbound webhook: https://mailkite.dev/docs


Installation
------------

MailKite's send API is a plain JSON-over-HTTPS API, so the MailKite backend has no
ESP-specific dependencies beyond what Anymail already requires. Just install Anymail:

.. code-block:: console

    $ python -m pip install django-anymail

(In other words, there is no ``[mailkite]`` extra to install.)


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's MailKite backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailkite.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILKITE_API_KEY

.. rubric:: MAILKITE_API_KEY

Required. A MailKite API key (an ``mk_live_…`` token), which you can create in the
`MailKite dashboard`_. The sender address (``from``) must be on a domain whose
ownership you've verified in MailKite.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILKITE_API_KEY": "<your MailKite API key>",
      }

Anymail will also look for ``MAILKITE_API_KEY`` at the root of the settings file
if neither ``ANYMAIL["MAILKITE_API_KEY"]`` nor ``ANYMAIL_MAILKITE_API_KEY`` is set.

You can override the API key for an individual message in its
:ref:`esp_extra <mailkite-esp-extra>`.

.. _MailKite dashboard: https://mailkite.dev/docs


.. setting:: ANYMAIL_MAILKITE_API_URL

.. rubric:: MAILKITE_API_URL

The base url for calling the MailKite API.

The default is ``MAILKITE_API_URL = "https://api.mailkite.dev/"``
(It's unlikely you would need to change this.)


.. _mailkite-esp-extra:

esp_extra support
-----------------

To use MailKite features not directly supported by Anymail, you can set a message's
:attr:`~anymail.message.AnymailMessage.esp_extra` to a `dict` that will be merged
into the JSON body sent to MailKite's `send API`_.

Example:

    .. code-block:: python

        message.esp_extra = {
            # thread a reply under a previous Message-Id
            'inReplyTo': '<a1b2c3@mail.example.com>',
        }

(You can also set ``"esp_extra"`` in Anymail's
:ref:`global send defaults <send-defaults>` to apply it to all messages.)


Limitations and quirks
----------------------

MailKite does not (yet) support a few Anymail additions through the send endpoint.
Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using a feature MailKite can't express. You
can tell Anymail to suppress these errors and send anyway — see
:ref:`unsupported-features`.

**Scheduled sending**
  :attr:`~anymail.message.AnymailMessage.send_at` is supported: a future time
  parks the message with MailKite's scheduler (the API responds with an
  ``ssnd_…`` id and Anymail reports a ``queued`` status); a past or omitted
  time sends immediately.

**No inline attachments**
  The send API has no Content-ID field, so inline images
  (:func:`~anymail.message.attach_inline_image`) are not supported through Anymail.
  Attach them as regular attachments instead.

**Batch sending / per-recipient merge**
  Setting :attr:`~anymail.message.AnymailMessage.merge_data`,
  :attr:`~anymail.message.AnymailMessage.merge_metadata` or
  :attr:`~anymail.message.AnymailMessage.merge_headers` switches to MailKite's
  batch-send endpoint: each ``to`` recipient gets an **individual message**
  showing only their own address, personalized with their merge values
  (per-recipient values win over
  :attr:`~anymail.message.AnymailMessage.merge_global_data`, metadata and
  extra headers, key by key). Each recipient gets their own
  ``message_id`` in :attr:`~anymail.message.AnymailMessage.anymail_status`,
  and a batch can partially succeed — a suppressed address reports status
  ``rejected`` and other failures ``failed``, without raising an error.
  Two restrictions: MailKite allows at most **50 recipients per batch
  message**, and ``cc``/``bcc`` can't be combined with a batch send (each
  message goes to exactly one recipient).

**Single reply-to field**
  MailKite's ``replyTo`` is a single string. If you supply multiple reply-to
  addresses, Anymail joins them into that one string (a header can hold several
  addresses).

**Metadata and tags use headers**
  MailKite has no dedicated metadata or tags field, so Anymail carries
  :attr:`~anymail.message.AnymailMessage.metadata` and
  :attr:`~anymail.message.AnymailMessage.tags` as JSON in custom ``X-Metadata`` and
  ``X-Tags`` headers, respectively.


.. _mailkite-inbound:

Inbound webhook
---------------

MailKite is inbound-first: mail sent to any address on a verified domain is
parsed and delivered to your webhook as JSON — decoded subject and bodies,
attachments, and the SPF/DKIM/DMARC/spam verdicts computed at MailKite's
receiving edge — so there is no raw MIME to parse on your end.

To use Anymail's normalized :ref:`inbound <inbound>` handling, set your
MailKite domain's webhook URL (in the `MailKite dashboard`_, or via the
``setWebhook`` API) to:

    :samp:`https://{yoursite.example.com}/anymail/mailkite/inbound/`

MailKite signs every delivery with an ``X-MailKite-Signature`` header
(HMAC-SHA256). Anymail requires the signing secret to verify it:

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILKITE_WEBHOOK_SECRET": "<your webhook signing secret>",
      }

You can read the secret from your domain's webhook settings in the MailKite
dashboard (or the ``getWebhookSecret`` API). Requests with a missing, invalid,
or expired signature are rejected with HTTP 400; MailKite's automatic retries
re-sign each attempt.

Anymail exposes MailKite's parsed fields on the
:class:`~anymail.inbound.AnymailInboundMessage`: envelope sender and
recipient, from/to (with display names), subject, text and html bodies, and
attachments (fetched from MailKite's signed attachment URLs, or decoded
inline on zero-retention and at-rest-encrypted domains).
:attr:`~anymail.inbound.AnymailInboundMessage.spam_detected` reflects
MailKite's spam verdict. The complete event — including the ``auth`` block
(SPF/DKIM/DMARC results) and ``threadId`` (pass it back as ``esp_extra
inReplyTo`` to reply in-thread) — is available in the event's
:attr:`~anymail.signals.AnymailInboundEvent.esp_event`.

**Open tracking, but no click tracking**
  :attr:`~anymail.message.AnymailMessage.track_opens` is supported as a
  per-message override of the sending domain's open-tracking default
  (HTML messages only). MailKite has no click tracking, so
  :attr:`~anymail.message.AnymailMessage.track_clicks` is not supported.

.. _MailKite template: https://mailkite.dev/docs
