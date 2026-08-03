.. _mailkite-backend:

MailKite
========

Anymail integrates Django with the `MailKite`_ developer email platform, using
their `send API`_ endpoint.

MailKite is *inbound-first*: as well as sending transactional mail via a single
API, it **receives** email and delivers the parsed body plus an authentication
verdict to your own endpoint as one signed webhook. This backend covers the send
side. (MailKite's inbound webhooks deliver received mail to a URL you control,
and are not wired through Anymail's :ref:`inbound <inbound>` signals -- see
:ref:`mailkite-inbound` below.)

.. _MailKite: https://mailkite.dev/
.. _send API: https://mailkite.dev/docs


.. _mailkite-installation:

Installation
------------

Anymail's MailKite backend uses only Anymail's regular ``requests``
dependency -- there is nothing extra to install::

    $ python -m pip install django-anymail

(There is no ``[mailkite]`` extra.)


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's MailKite backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailkite.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILKITE_API_KEY

.. rubric:: MAILKITE_API_KEY

Required for sending. An API key from your MailKite account
(``mk_live_...``). Create one in the MailKite dashboard.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILKITE_API_KEY": "mk_live_...",
      }

Anymail will also look for ``MAILKITE_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["MAILKITE_API_KEY"]``
nor ``ANYMAIL_MAILKITE_API_KEY`` is set.


.. setting:: ANYMAIL_MAILKITE_API_URL

.. rubric:: MAILKITE_API_URL

The base url for calling the MailKite API.

The default is ``MAILKITE_API_URL = "https://api.mailkite.dev/"``.
(It's unlikely you would need to change this.)


.. _mailkite-quirks:

Limitations and quirks
----------------------

MailKite supports most Anymail features, but there are a few things to know.

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using features MailKite doesn't support.
You can tell Anymail to suppress these errors and send the messages
anyway---see :ref:`unsupported-features`.

**Single reply-to address only**
  MailKite's send API takes a single ``replyTo`` address. If you set more than
  one ``reply_to`` address on a message, Anymail raises
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature`. (Most apps use at most
  one reply-to address.)

**No inline attachments (Content-ID)**
  MailKite's send API does not expose a Content-ID field, so it can't place
  inline images. Trying to send an inline attachment raises
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature`.

**Anymail tags and metadata are exposed to recipient**
  Anymail implements its normalized :attr:`~anymail.message.AnymailMessage.tags`
  and :attr:`~anymail.message.AnymailMessage.metadata` features for MailKite
  using custom email headers (``X-Tags`` and ``X-Metadata``). That means they
  can be visible to recipients via their email app's "show original message"
  (or similar) command. **Do not include sensitive data in tags or metadata.**

**No envelope sender**
  MailKite does not support specifying the
  :attr:`~anymail.message.AnymailMessage.envelope_sender`.

**No outbound status-tracking webhooks**
  MailKite does not currently emit outbound tracking events (delivered, opened,
  clicked, bounced) as webhooks, so Anymail's :ref:`status tracking
  <event-tracking>` signals are not available for MailKite. (You can still set
  per-message :attr:`~anymail.message.AnymailMessage.track_opens` and
  :attr:`~anymail.message.AnymailMessage.track_clicks`; MailKite records opens
  and clicks in its own dashboard.)


.. _mailkite-esp-extra:

esp_extra support
-----------------

Anymail's MailKite backend will pass
:attr:`~anymail.message.AnymailMessage.esp_extra` values directly into the
MailKite `send API`_ body. For example, to force a per-message tracking
override:

  .. code-block:: python

      message = AnymailMessage(...)
      message.esp_extra = {
          "trackOpens": True,
          "trackClicks": True,
      }


.. _mailkite-templates:

ESP templates and merge
-----------------------

MailKite renders **server-side templates** and fills ``{{merge_tags}}`` in the
subject, html, and text. Use Anymail's normalized
:attr:`~anymail.message.AnymailMessage.template_id` and
:attr:`~anymail.message.AnymailMessage.merge_global_data`:

  .. code-block:: python

      message = EmailMessage(
          to=["alice@example.com"],
          from_email="...",  # subject/body come from the template
      )
      message.template_id = "tpl_welcome"  # or a base template id
      message.merge_global_data = {"name": "Ann", "plan": "Pro"}


Batch sending
-------------

MailKite supports :ref:`batch sending <batch-send>` (where each *To* recipient
sees only their own email address). Set Anymail's normalized
:attr:`~anymail.message.AnymailMessage.merge_metadata` or
:attr:`~anymail.message.AnymailMessage.merge_headers`, or an empty
:attr:`~anymail.message.AnymailMessage.merge_data`, to use MailKite's batch
endpoint:

  .. code-block:: python

      message = EmailMessage(
          to=["alice@example.com", "Bob <bob@example.com>"],
          from_email="...", subject="...", body="..."
      )
      message.merge_metadata = {
          'alice@example.com': {'user_id': "12345"},
          'bob@example.com': {'user_id': "54321"},
      }

Each recipient gets their own message id, and MailKite reports per-recipient
success or failure (e.g. a suppressed recipient surfaces as ``rejected`` in the
recipient status).

MailKite's batch endpoint does not accept ``cc``/``bcc`` (each recipient gets a
message addressed only to them). Per-recipient template variables
(:attr:`~anymail.message.AnymailMessage.merge_data`) are not supported -- use a
template with :attr:`~anymail.message.AnymailMessage.merge_global_data`, or
:attr:`~anymail.message.AnymailMessage.merge_metadata` for per-recipient data.


.. _mailkite-inbound:

Inbound
-------

MailKite's headline feature is **inbound** email: point your domain's MX at
MailKite and it delivers each received message -- parsed body plus an SPF/DKIM/
DMARC authentication verdict -- to a webhook URL you control, signed with HMAC.

That inbound flow delivers to *your* endpoint, in MailKite's own payload format,
and is **not** wired through Anymail's :ref:`inbound <inbound>` signals. Handle
it directly in your own Django view. (See the MailKite `send API`_ docs index
for the inbound webhook reference.)


.. _mailkite-troubleshooting:

Troubleshooting
---------------

If Anymail's MailKite integration isn't behaving like you expect, the MailKite
dashboard shows every message (inbound and outbound), its provider response, and
the full webhook delivery history -- useful for isolating whether a send was
accepted, delivered, or suppressed.

See Anymail's :ref:`troubleshooting` docs for additional suggestions.
