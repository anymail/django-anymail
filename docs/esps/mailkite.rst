.. _mailkite-backend:

MailKite
========

Anymail integrates with the `MailKite`_ email platform, using its
`send API`_ endpoint. MailKite is an *inbound-first* email service: it
receives email as a webhook and sends transactional mail through a single
API — useful if you want one vendor for both sending and (separately, planned)
inbound handling.

.. _MailKite: https://mailkite.dev/
.. _send API: https://mailkite.dev/docs
.. _MailKite API keys: https://app.mailkite.dev


.. _mailkite-installation:

Installation
------------

MailKite's send API is a standard JSON-over-HTTPS API, so Anymail's MailKite
backend has no additional dependencies beyond Anymail's usual ``requests``
package. Just install Anymail:

.. code-block:: console

    $ python -m pip install django-anymail


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's MailKite backend, set:

.. code-block:: python

    EMAIL_BACKEND = "anymail.backends.mailkite.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILKITE_API_KEY

.. rubric:: MAILKITE_API_KEY

Required for sending. A MailKite API key (`mk_live_…`) from your
`MailKite API keys`_ page.

.. code-block:: python

    ANYMAIL = {
        ...
        "MAILKITE_API_KEY": "mk_live_...",
    }

Anymail will also look for ``MAILKITE_API_KEY`` at the root of the settings
file if neither ``ANYMAIL["MAILKITE_API_KEY"]`` nor
``ANYMAIL_MAILKITE_API_KEY`` is set.


.. setting:: ANYMAIL_MAILKITE_API_URL

.. rubric:: MAILKITE_API_URL

The base url for calling the MailKite API.

The default is ``MAILKITE_API_URL = "https://api.mailkite.dev/"``.
(It's unlikely you would need to change this.)


.. _mailkite-quirks:

Limitations and quirks
----------------------

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using features the backend doesn't (yet)
support. You can tell Anymail to suppress these errors and send the messages
anyway — see :ref:`unsupported-features`.

**No inline attachments**
  MailKite's send API does not currently expose a content-id / inline field on
  attachments, so Anymail can't express inline (``cid:``-referenced) images.
  Trying to send one raises an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error. Regular
  (non-inline) attachments are fully supported.

**No tags or metadata**
  MailKite's send API has no dedicated ``tags`` or ``metadata`` fields, so
  Anymail's normalized :attr:`~anymail.message.AnymailMessage.tags` and
  :attr:`~anymail.message.AnymailMessage.metadata` attributes are unsupported.
  (If you need to pass arbitrary key/value data on a send, you can attach it
  as a custom header via :attr:`~anymail.message.AnymailMessage.extra_headers`
  or :ref:`esp_extra <mailkite-esp-extra>` — but note custom headers may be
  visible to recipients via "show original".)

**No batch sending / per-recipient merge data**
  MailKite has a single send endpoint (no batch variant) and no per-recipient
  merge, so Anymail's :attr:`~anymail.message.AnymailMessage.merge_data`,
  :attr:`~anymail.message.AnymailMessage.merge_metadata`, and
  :attr:`~anymail.message.AnymailMessage.merge_headers` are unsupported.
  (Setting ``merge_data`` to an empty dict is allowed as a no-op — it just
  sends one message to all recipients, without hiding the *To* list.)

**reply_to is a single address**
  MailKite's ``replyTo`` is a single address. If you supply multiple reply-to
  addresses, Anymail joins them into a single comma-separated ``Reply-To``
  value.

**No envelope sender**
  MailKite does not support specifying the
  :attr:`~anymail.message.AnymailMessage.envelope_sender`.

**Status tracking and inbound webhooks**
  MailKite itself supports both delivery tracking and inbound email (received
  messages delivered as signed webhooks). Wiring those into Anymail's
  :ref:`status tracking <event-tracking>` and :ref:`inbound <inbound>` signals
  is not part of this initial send backend — it's the planned next step.


.. _mailkite-esp-extra:

esp_extra support
-----------------

Anymail's MailKite backend passes
:attr:`~anymail.message.AnymailMessage.esp_extra` values directly into the
MailKite `send API`_ JSON body. This is the way to reach MailKite-specific
fields that don't map to a normalized Anymail attribute — for example
``inReplyTo`` (to thread a reply under an existing Message-ID) or
``trackOpens``:

.. code-block:: python

    message = AnymailMessage(...)
    message.esp_extra = {
        # Thread this message under an earlier one (sets In-Reply-To/References):
        "inReplyTo": "<original.message@example.com>",
    }


.. _mailkite-templates:

Templates
---------

MailKite supports server-rendered templates: a saved template
(``tpl_…``) or a built-in base template (``base_…``) supplies the subject,
html and/or text, and ``templateData`` fills its ``{{merge_tags}}``.

Use Anymail's normalized :attr:`~anymail.message.AnymailMessage.template_id`
and :attr:`~anymail.message.AnymailMessage.merge_global_data` attributes:

.. code-block:: python

    message = AnymailMessage(
        from_email="orders@example.com",
        to="customer@example.com",
        template_id="tpl_receipt",
        merge_global_data={"name": "Sam", "order_no": "1024"},
    )
    message.send()
