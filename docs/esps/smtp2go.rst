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


.. _smtp2go-webhooks:

Status tracking webhooks
------------------------

If you use Anymail's :ref:`status tracking <event-tracking>`, add a webhook
in SMTP2GO's **Settings > Webhooks > Manage Webhooks**:

* Set the URL to ``https://random:random@yoursite.example.com/anymail/smtp2go/tracking/``,
  where ``random:random`` matches your :setting:`ANYMAIL_WEBHOOK_SECRET` and the
  domain is your Django site. See :ref:`securing-webhooks`.
* Alternatively, configure the Authorization header as Basic with the same credentials.
* Select your application's API key under Users.
* Choose JSON or Form encoded output; Anymail supports both.
* Select the email events you want to receive. Enable open and click tracking
  on your API key for engagement events. Do not select SMS events.
* Save, then use **Test this webhook** to verify your configuration.

See SMTP2GO's `webhook setup guide`_ for details. Anymail uses standard Basic
authentication validation; SMTP2GO does not document webhook signatures.

Anymail normalizes the events as follows:

.. list-table::
   :header-rows: 1

   * - SMTP2GO event
     - Anymail event type
   * - processed
     - queued
   * - delivered
     - delivered
   * - open
     - opened
   * - click
     - clicked
   * - bounce (hard or soft)
     - bounced
   * - spam
     - complained
   * - unsubscribe
     - unsubscribed
   * - resubscribe
     - subscribed
   * - reject
     - rejected

The tracking event's ``message_id`` is SMTP2GO's ``email_id``, matching the send
response for unscheduled emails. Its ``event_id`` is the webhook's ``id``, and
``recipient`` is the event's ``rcpt`` (not the full list of email recipients).
Event timestamps are interpreted as UTC when no timezone offset is supplied.

SMTP2GO does not document a structured click URL or detailed rejection reason.
Anymail preserves ``context``, bounce classification, custom email headers, and
all other provider fields in ``esp_event``. ``click_url`` remains unset, and
reject events use reject reason ``other`` rather than guessing the cause.

For scheduled messages, the send response's ``schedule_id`` differs from the
webhook's ``email_id``. Request the ``X-Smtp2go-Schedule-Id`` email header in
your webhook settings and read it from ``esp_event`` to correlate them.

.. _webhook setup guide: https://developers.smtp2go.com/docs/setup-a-webhook


Inbound
-------

SMTP2GO inbound email is not supported by Anymail.


Live integration tests
----------------------

Set ``ANYMAIL_TEST_SMTP2GO_API_KEY`` and ``ANYMAIL_TEST_SMTP2GO_DOMAIN``
(a verified sending domain), then run::

    python runtests.py tests.test_smtp2go_integration

These tests send real email to Anymail's test mailboxes. Optionally set
``ANYMAIL_TEST_SMTP2GO_TEMPLATE_ID`` to a template accepting a ``name`` variable.
