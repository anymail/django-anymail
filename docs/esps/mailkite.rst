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

    This backend covers transactional **sending**.
    `MailKite inbound webhook`_ and delivery-status tracking support are planned
    as a follow-up — please open an issue if you need them sooner.

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

**No per-recipient merge**
  MailKite sends a single message to all recipients (there is no one-per-recipient
  batch send), so :attr:`~anymail.message.AnymailMessage.merge_data`,
  :attr:`~anymail.message.AnymailMessage.merge_metadata` and
  :attr:`~anymail.message.AnymailMessage.merge_headers` are not supported. Use
  :attr:`~anymail.message.AnymailMessage.template_id` with
  :attr:`~anymail.message.AnymailMessage.merge_global_data` to render a single
  message from a `MailKite template`_.

**Single reply-to field**
  MailKite's ``replyTo`` is a single string. If you supply multiple reply-to
  addresses, Anymail joins them into that one string (a header can hold several
  addresses).

**Metadata and tags use headers**
  MailKite has no dedicated metadata or tags field, so Anymail carries
  :attr:`~anymail.message.AnymailMessage.metadata` and
  :attr:`~anymail.message.AnymailMessage.tags` as JSON in custom ``X-Metadata`` and
  ``X-Tags`` headers, respectively.

**No per-message tracking toggles**
  The send API doesn't expose click/open tracking per message, so
  :attr:`~anymail.message.AnymailMessage.track_clicks` and ``track_opens`` are not
  supported. Configure those at the MailKite account/domain level.

.. _MailKite template: https://mailkite.dev/docs
