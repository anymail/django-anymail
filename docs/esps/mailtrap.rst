.. _mailtrap-backend:

Mailtrap
========

.. versionadded:: vNext

Anymail integrates with `Mailtrap`_'s Email API/SMTP (transactional) and
Email Sandbox (test) email services, using the `Mailtrap API v2`_.
(Anymail uses Mailtrap's REST-oriented HTTP API, not the SMTP protocol.)

Anymail should also work correctly with Mailtrap's Bulk Sending service
(which uses an identical API), but this scenario is not tested separately.

.. note::

    **Troubleshooting:**
    If your Mailtrap transactional or bulk messages aren't being delivered
    as expected, check the `Email Logs`_ in Mailtrap's dashboard.
    The "Event History" tab for an individual message is often helpful.

.. _Mailtrap: https://mailtrap.io
.. _Mailtrap API v2: https://api-docs.mailtrap.io/docs/mailtrap-api-docs/
.. _Email Logs: https://mailtrap.io/sending/email_logs


Settings
--------

To use Anymail's Mailtrap backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailtrap.EmailBackend"
      ANYMAIL = {
          "MAILTRAP_API_TOKEN": "<your API token>",
          # Only to use the Email Sandbox service:
          "MAILTRAP_SANDBOX_ID": <your test inbox id>,
      }

in your settings.py.

When :setting:`MAILTRAP_SANDBOX_ID <ANYMAIL_MAILTRAP_SANDBOX_ID>` is set,
Anymail uses Mailtrap's Email Sandbox service. If it is not set, Anymail
uses Mailtrap's transactional Email API/SMTP service.


.. setting:: ANYMAIL_MAILTRAP_API_TOKEN

.. rubric:: MAILTRAP_API_TOKEN

Required for sending:

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILTRAP_API_TOKEN": "<your API token>",
      }

Anymail will also look for ``MAILTRAP_API_TOKEN`` at the
root of the settings file if neither ``ANYMAIL["MAILTRAP_API_TOKEN"]``
nor ``ANYMAIL_MAILTRAP_API_TOKEN`` is set.


.. setting:: ANYMAIL_MAILTRAP_SANDBOX_ID

.. rubric:: MAILTRAP_SANDBOX_ID

Required to use Mailtrap's Email Sandbox test inbox. (And must *not* be set
to use Mailtrap's Email API/SMTP transactional service.)

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILTRAP_SANDBOX_ID": 12345,
      }

The sandbox id can be found in Mailtrap's dashboard: click into the desired
sandbox and look for the number in the dashboard url. For example,
``https://mailtrap.io/inboxes/12345/messages`` would be sandbox id 12345.

The value can be a string or number. For convenience when using env files,
Anymail treats an empty string or ``None`` (or any falsy value) as "not set."

.. setting:: ANYMAIL_MAILTRAP_API_URL

.. rubric:: MAILTRAP_API_URL

The base url for calling the Mailtrap API.

The default is ``MAILTRAP_API_URL = "https://send.api.mailtrap.io/api/"``
(Mailtrap's Email API/SMTP transactional service)
if :setting:`MAILTRAP_SANDBOX_ID <ANYMAIL_MAILTRAP_SANDBOX_ID>` is not set,
or ``"https://sandbox.api.mailtrap.io/api/"`` (Mailbox's Email Sandbox testing
service) when a sandbox id is provided.

Most users should not need to change this setting. However, you could set it
to use Mailtrap's bulk send service:

  .. code-block:: python

      ANYMAIL = {
        ...
        "MAILTRAP_API_URL": "https://bulk.api.mailtrap.io/api/",
      }

(Note that Anymail is not specifically tested with Mailtrap's bulk API.)

The value must be only the API base URL: do not include the ``"/send"`` endpoint.
(When provided, this is used as the base URL *always*. If you are also setting
a sandbox id, the base URL must be compatible with Mailtrap's sandbox API.)


.. _mailtrap-esp-extra:

esp_extra support
-----------------

To use Mailtrap features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` of Mailtraps's `Send email API body parameters`_.
Your :attr:`esp_extra` dict will be deeply merged into the Mailtrap
API payload, with `esp_extra` having precedence in conflicts.
(For batch sends, the `esp_extra` values are merged into the ``"base"``
payload shared by all recipients.)

Example:

    .. code-block:: python

        message.esp_extra = {
            "future_mailtrap_feature": "value"
        }


(You can also set `"esp_extra"` in Anymail's :ref:`global send defaults <send-defaults>`
to apply it to all messages.)

.. _Send email API body parameters:
   https://api-docs.mailtrap.io/docs/mailtrap-api-docs/67f1d70aeb62c-send-email-including-templates#request-body


.. _mailtrap-quirks:

Limitations and quirks
----------------------

**Single tag**
  Anymail uses Mailtrap's ``"category"`` option for tags, and Mailtrap allows
  only a single category per message. If your message has two or more
  :attr:`~anymail.message.AnymailMessage.tags`, you'll get an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error---or
  if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first tag.

**Tag not compatible with template**
  Trying to send with both :attr:`~anymail.message.AnymailMessage.tags` and a
  :attr:`~anymail.message.AnymailMessage.template_id` will result in a Mailtrap
  API error that "'category' is not allowed with 'template_uuid'."

**No delayed sending**
  Mailtrap does not support :attr:`~anymail.message.AnymailMessage.send_at`.

**Attachments require filenames**
  Mailtrap requires that all attachments and inline images have filenames. If you
  don't supply a filename, Anymail will use ``"attachment"`` as the filename.

**Non-ASCII attachment filenames will be garbled**
  Mailtrap's API does not properly encode Unicode characters in attachment
  filenames. Some email clients will display those characters incorrectly.

**No click-tracking or open-tracking options**
  Mailtrap does not provide a way to control open or click tracking for individual
  messages. Anymail's :attr:`~anymail.message.AnymailMessage.track_clicks` and
  :attr:`~anymail.message.AnymailMessage.track_opens` settings are unsupported.
  (You *can* `exclude specific links from tracking`_ using Mailtrap-proprietary
  attributes in your HTML.)

**No envelope sender overrides**
  Mailtrap does not support overriding :attr:`~anymail.message.AnymailMessage.envelope_sender`.

**Non-ASCII mailboxes (EAI)**
  Mailtrap partially supports Unicode mailboxes (the *user* part of
  *user\@domain*---see :ref:`EAI <eai>`). EAI recipient addresses (to, cc, bcc)
  are delivered correctly, but Mailtrap generates invalid header fields that may
  display as empty or garbled, depending on the email app.

  Trying to use an EAI ``from_email`` results in a Mailtrap API error that the
  "'From' header does not match the sender's domain."

  EAI in ``reply_to`` is supported (though may generate an invalid header
  field) for a single address. Using EAI with multiple reply addresses will
  cause an :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error because
  Anymail cannot accurately communicate that to Mailtrap's API.

.. _exclude specific links from tracking:
   https://help.mailtrap.io/article/184-excluding-specific-links-from-tracking

.. _mailtrap-templates:

Batch sending/merge and ESP templates
-------------------------------------

Mailtrap offers both :ref:`ESP stored templates <esp-stored-templates>`
and :ref:`batch sending <batch-send>` with per-recipient merge data.

When you send a message with multiple ``to`` addresses, the
:attr:`~anymail.message.AnymailMessage.merge_data`,
:attr:`~anymail.message.AnymailMessage.merge_metadata`
and :attr:`~anymail.message.AnymailMessage.merge_headers` properties
determine how many distinct messages are sent:

* If the ``merge_...`` properties are *not* set (the default), Anymail
  will tell Mailtrap to send a single message, and all recipients will see
  the complete list of To addresses.
* If *any* of the ``merge_...`` properties are set---even to an empty `{}` dict,
  Anymail will tell Mailtrap to send a separate message for each ``to``
  address, and the recipients won't see the other To addresses.

You can use a Mailtrap stored template by setting a message's
:attr:`~anymail.message.AnymailMessage.template_id` to the template's
"Template UUID." Find the template UUID in the Templates section of Mailtrap's
dashboard, under the template's details. When a Mailtrap template is used,
your Django code must not provide a message subject or text or html body.

Supply the template merge data values with Anymail's
normalized :attr:`~anymail.message.AnymailMessage.merge_data`
and :attr:`~anymail.message.AnymailMessage.merge_global_data`
message attributes.

  .. code-block:: python

      message = EmailMessage(
          from_email="from@example.com",
          to=["alice@example.com", "Bob <bob@example.com>"],
          # omit subject and body (or set to None) to use template content
          ...
      )
      message.template_id = "11111111-abcd-1234-0000-0123456789ab"  # Template UUID
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
      }
      message.send()


.. _mailtrap-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`,
create a webhook in the Settings section of the Mailtrap dashboard under Webhooks.
See their `Webhooks help`_ article for more information.

(Note that Mailtrap's Email Sandbox service does not trigger webhook events.)

In Mailtrap's "Add new webhook" screen, enter:

* Webhook URL:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailtrap/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

* Payload format: JSON (*not* JSON Lines)

* Select area: Email Sending

  * Select stream: Transactional (unless you have overridden Anymail's
    :setting:`MAILTRAP_API_URL <ANYMAIL_MAILTRAP_API_URL>` to use Mailtrap's
    bulk sending API).
  * Select domain: the desired sending domain(s)
  * Select events to listen to: check all you want to receive

Mailtrap will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
rejected, bounced, deferred, delivered, opened, clicked, complained, unsubscribed.


.. _Webhooks help: https://help.mailtrap.io/article/102-webhooks


.. _mailtrap-inbound:

Inbound webhook
---------------

Mailtrap's inbound service is currently under development, and APIs are not
yet publicly available.
