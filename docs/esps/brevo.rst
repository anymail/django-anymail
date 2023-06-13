.. _brevo-backend:
.. _sendinblue-backend:

Brevo
=====

Anymail integrates with the `Brevo`_ email service (formerly Sendinblue), using their `API v3`_.
Brevo's transactional API does not support some basic email features, such as
inline images. Be sure to review the :ref:`limitations <sendinblue-limitations>` below.

.. versionchanged:: 10.1

   Brevo was called "Sendinblue" until May, 2023. To avoid unnecessary code changes,
   Anymail still uses the old name in code (settings, backend, webhook urls, etc.).

.. important::

    **Troubleshooting:**
    If your Brevo messages aren't being delivered as expected, be sure to look for
    events in your Brevo `logs`_.

    Brevo detects certain types of errors only *after* the send API call reports
    the message as "queued." These errors appear in the logging dashboard.

.. _Brevo: https://www.brevo.com/
.. _API v3: https://developers.brevo.com/docs
.. _logs: https://app-smtp.brevo.com/log


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Brevo backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.sendinblue.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_SENDINBLUE_API_KEY

.. rubric:: SENDINBLUE_API_KEY

The API key can be retrieved from your Brevo `SMTP & API settings`_ on the
"API Keys" tab (don't try to use an SMTP key). Required.

Make sure the version column indicates "v3." (v2 keys don't work with
Anymail. If you don't see a v3 key listed, use "Create a New API Key".)

  .. code-block:: python

      ANYMAIL = {
          ...
          "SENDINBLUE_API_KEY": "<your v3 API key>",
      }

Anymail will also look for ``SENDINBLUE_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["SENDINBLUE_API_KEY"]``
nor ``ANYMAIL_SENDINBLUE_API_KEY`` is set.

.. _SMTP & API settings: https://app.brevo.com/settings/keys/api


.. setting:: ANYMAIL_SENDINBLUE_API_URL

.. rubric:: SENDINBLUE_API_URL

The base url for calling the Brevo API.

The default is ``SENDINBLUE_API_URL = "https://api.brevo.com/v3/"``
(It's unlikely you would need to change this.)

.. versionchanged:: 10.1

   Earlier Anymail releases used ``https://api.sendinblue.com/v3/``.


.. _sendinblue-esp-extra:

esp_extra support
-----------------

To use Brevo features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` that will be merged into the json sent to Brevo's
`smtp/email API`_.

For example, you could set Brevo's *batchId* for use with
their `batched scheduled sending`_:

    .. code-block:: python

        message.esp_extra = {
            'batchId': '275d3289-d5cb-4768-9460-a990054b6c81',  # merged into send params
        }


(You can also set `"esp_extra"` in Anymail's :ref:`global send defaults <send-defaults>`
to apply it to all messages.)

.. _batched scheduled sending: https://developers.brevo.com/docs/schedule-batch-sendings
.. _smtp/email API: https://developers.brevo.com/reference/sendtransacemail


.. _sendinblue-limitations:

Limitations and quirks
----------------------

Brevo's v3 API has several limitations. In most cases below,
Anymail will raise an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error if you try to send a message using missing features. You can
override this by enabling the :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`
setting, and Anymail will try to limit the API request to features
Brevo can handle.

**HTML body required**
  Brevo's API returns an error if you attempt to send a message with
  only a plain-text body. Be sure to :ref:`include HTML <sending-html>`
  content for your messages if you are not using a template.

  (Brevo *does* allow HTML without a plain-text body. This is generally
  not recommended, though, as some email systems treat HTML-only content as a
  spam signal.)

**Inline images**
  Brevo's v3 API doesn't support inline images, at all.
  (Confirmed with Brevo support Feb 2018.)

  If you are ignoring unsupported features, Anymail will try to send
  inline images as ordinary image attachments.

**Attachment names must be filenames with recognized extensions**
  Brevo determines attachment content type by assuming the attachment's
  name is a filename, and examining that filename's extension (e.g., ".jpg").

  Trying to send an attachment without a name, or where the name does not end
  in a supported filename extension, will result in a Brevo API error.
  Anymail has no way to communicate an attachment's desired content-type
  to the Brevo API if the name is not set correctly.

**Single Reply-To**
  Brevo's v3 API only supports a single Reply-To address.

  If you are ignoring unsupported features and have multiple reply addresses,
  Anymail will use only the first one.

**Metadata**
  Anymail passes :attr:`~anymail.message.AnymailMessage.metadata` to Brevo
  as a JSON-encoded string using their :mailheader:`X-Mailin-custom` email header.
  The metadata is available in tracking webhooks.

**Delayed sending**
  .. versionadded:: 9.0
     Earlier versions of Anymail did not support :attr:`~anymail.message.AnymailMessage.send_at`
     with Brevo.

**No click-tracking or open-tracking options**
  Brevo does not provide a way to control open or click tracking for individual
  messages. Anymail's :attr:`~anymail.message.AnymailMessage.track_clicks` and
  :attr:`~anymail.message.AnymailMessage.track_opens` settings are unsupported.

**No envelope sender overrides**
  Brevo does not support overriding :attr:`~anymail.message.AnymailMessage.envelope_sender`
  on individual messages.


.. _sendinblue-templates:

Batch sending/merge and ESP templates
-------------------------------------

Brevo supports :ref:`ESP stored templates <esp-stored-templates>` populated with
global merge data for all recipients, but does not offer :ref:`batch sending <batch-send>`
with per-recipient merge data. Anymail's :attr:`~anymail.message.AnymailMessage.merge_data`
and :attr:`~anymail.message.AnymailMessage.merge_metadata` message attributes are not
supported with the Brevo backend, but you can use Anymail's
:attr:`~anymail.message.AnymailMessage.merge_global_data` with Brevo templates.

To use a Brevo template, set the message's
:attr:`~anymail.message.AnymailMessage.template_id` to the numeric
Brevo template ID, and supply substitution attributes using
the message's :attr:`~anymail.message.AnymailMessage.merge_global_data`:

  .. code-block:: python

      message = EmailMessage(
          to=["alice@example.com"]  # single recipient...
          # ...multiple to emails would all get the same message
          # (and would all see each other's emails in the "to" header)
      )
      message.template_id = 3   # use this Brevo template
      message.from_email = None  # to use the template's default sender
      message.merge_global_data = {
          'name': "Alice",
          'order_no': "12345",
          'ship_date': "May 15",
      }

Within your Brevo template body and subject, you can refer to merge
variables using Django-like template syntax, like ``{{ params.order_no }}`` or
``{{ params.ship_date }}`` for the example above. See Brevo's guide to the
`Brevo Template Language`_.

The message's :class:`from_email <django.core.mail.EmailMessage>` (which defaults to
your :setting:`DEFAULT_FROM_EMAIL` setting) will override the template's default sender.
If you want to use the template's sender, be sure to set ``from_email`` to ``None``
*after* creating the message, as shown in the example above.

You can also override the template's subject and reply-to address (but not body)
using standard :class:`~django.core.mail.EmailMessage` attributes.

.. caution::

    **Sendinblue "old template language" not supported**

    Sendinblue once supported two different template styles: a "new" template
    language that uses Django-like template syntax (with ``{{ param.NAME }}``
    substitutions), and an "old" template language that used percent-delimited
    ``%NAME%`` substitutions.

    Anymail 7.0 and later work *only* with new style templates, now known as the
    "Brevo Template Language."

    Although unconverted old templates may appear to work with Anymail, there can be
    subtle bugs. In particular, ``reply_to`` overrides and recipient display names
    are silently ignored when *old* style templates are sent with Anymail 7.0 or later.
    If you still have old style templates, follow Brevo's instructions to
    `convert each old template`_ to the new language.

    .. versionchanged:: 7.0

        Dropped support for Sendinblue old template language



.. _Brevo Template Language:
    https://help.brevo.com/hc/en-us/articles/360000946299

.. _convert each old template:
    https://help.brevo.com/hc/en-us/articles/360000991960


.. _sendinblue-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, add
the url at Brevo's site under  `Transactional > Email > Settings > Webhook`_.

The "URL to call" is:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/sendinblue/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Be sure to select the checkboxes for all the event types you want to receive. (Also make
sure you are in the "Transactional" section of their site; Brevo has a separate set
of "Campaign" webhooks, which don't apply to messages sent through Anymail.)

If you are interested in tracking opens, note that Brevo has both a "First opening"
and an "Opened" event type, and will generate both the first time a message is opened.
Anymail normalizes both of these events to "opened." To avoid double counting, you should
only enable one of the two.

Brevo will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
queued, rejected, bounced, deferred, delivered, opened (see note above), clicked, complained,
unsubscribed, subscribed (though this should never occur for transactional email).

For events that occur in rapid succession, Brevo frequently delivers them out of order.
For example, it's not uncommon to receive a "delivered" event before the corresponding "queued."

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of raw webhook data received from Brevo.


.. _Transactional > Email > Settings > Webhook: https://app-smtp.brevo.com/webhook


.. _sendinblue-inbound:

Inbound webhook
---------------

Anymail does not currently support `Brevo's inbound parsing`_.

.. _Brevo's inbound parsing:
    https://developers.brevo.com/docs/inbound-parse-webhooks
