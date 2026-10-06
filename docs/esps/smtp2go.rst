.. _smtp2go-backend:

SMTP2GO
=======

Anymail integrates with `SMTP2GO`_ using its `v3 HTTP API`_.

.. _SMTP2GO: https://www.smtp2go.com/
.. _v3 HTTP API: https://developers.smtp2go.com/reference/send-standard-email


Installation
------------

To use Anymail's SMTP2GO backend, set::

    EMAIL_BACKEND = "anymail.backends.smtp2go.EmailBackend"

No additional dependencies are required. You must configure a verified sender
in your SMTP2GO account before sending email.

.. setting:: ANYMAIL_SMTP2GO_API_KEY

.. rubric:: SMTP2GO_API_KEY

Your SMTP2GO API key, with permission to send emails:

.. code-block:: python

    ANYMAIL = {
        "SMTP2GO_API_KEY": "<your API key>",
    }

Anymail also looks for ``SMTP2GO_API_KEY`` at the root of your settings file
if neither ``ANYMAIL["SMTP2GO_API_KEY"]`` nor ``ANYMAIL_SMTP2GO_API_KEY`` is set.

.. setting:: ANYMAIL_SMTP2GO_API_URL

.. rubric:: SMTP2GO_API_URL

The base API URL, defaulting to ``"https://api.smtp2go.com/v3/"``.
Do not include ``email/send``. Set this to SMTP2GO's regional API URL if required.


.. _smtp2go-esp-extra:

esp_extra support
-----------------

A message's :attr:`~anymail.message.AnymailMessage.esp_extra` is merged into
its SMTP2GO email object. For example, to wait for SMTP2GO to process the email
instead of accepting it for background processing:

.. code-block:: python

    message.esp_extra = {"fastaccept": False}

Anymail defaults to ``fastaccept=True``. In batch sends, ``esp_extra`` applies
to every email in the batch. For remote attachments, you can supply SMTP2GO's
``attachments`` or ``inlines`` arrays with ``url`` fields through ``esp_extra``.


Limitations and quirks
----------------------

**Sending status and identifiers**
  Successful API submissions have Anymail status ``queued``. All recipients of
  a single email share its ``email_id``. Scheduled messages use ``schedule_id``
  instead, which differs from the eventual email ID. HTTP errors and processing
  failures (including failures reported with HTTP 200) raise
  :exc:`~anymail.exceptions.AnymailAPIError`. SMTP2GO does not document enough
  information to reliably assign processing failures to individual recipients;
  a failed request may have accepted some of its recipients or batch items.
  Retrying such requests can send duplicate emails.

**Scheduled sending**
  :attr:`~anymail.message.AnymailMessage.send_at` maps to ``schedule``.
  SMTP2GO limits scheduling to the next three days. Anymail passes the requested
  time to SMTP2GO without enforcing that limit locally.

**Inline images**
  SMTP2GO uses the inline attachment's filename as its Content-ID. Anymail passes
  the attachment's Content-ID as that filename so ``cid:`` references work.

**Unsupported options**
  SMTP2GO's send API does not support Anymail's tags, metadata, merge metadata,
  envelope sender overrides, or per-message open and click tracking options.
  Configure tracking on your SMTP2GO API key. Unsupported options raise
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature`, unless you enable
  :ref:`ignore unsupported features <unsupported-features>`.


.. _smtp2go-templates:

Batch sending/merge and ESP templates
-------------------------------------

Set :attr:`~anymail.message.AnymailMessage.template_id` to your SMTP2GO template
ID and use :attr:`~anymail.message.AnymailMessage.merge_global_data` for template
variables. SMTP2GO ignores the message's subject and bodies when a template is
used; define those in the template instead.

Setting :attr:`~anymail.message.AnymailMessage.merge_data` or
:attr:`~anymail.message.AnymailMessage.merge_headers` uses SMTP2GO's
`batch endpoint`_ to send a separate email to each ``to`` recipient. Recipient
merge data overrides global template variables. Common ``cc`` and ``bcc``
recipients receive a copy of each email. SMTP2GO currently allows up to 1,000
emails per batch; Anymail does not split larger batches automatically.

.. _batch endpoint: https://developers.smtp2go.com/reference/send-email-batch


Status tracking and inbound webhooks
------------------------------------

SMTP2GO tracking webhooks and inbound email are not supported by this backend.


Live integration tests
----------------------

Set ``ANYMAIL_TEST_SMTP2GO_API_KEY`` and ``ANYMAIL_TEST_SMTP2GO_DOMAIN``
(a verified sending domain), then run::

    python runtests.py tests.test_smtp2go_integration

These tests send real email to Anymail's test mailboxes. Optionally set
``ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID`` to a template accepting a ``name`` variable.
