.. _postal-backend:

Postal
========

Anymail integrates with the `Postal`_ self-hosted transactional email platform,
using their `HTTP email API`_.

.. _Postal: https://postal.atech.media/
.. _HTTP email API: https://github.com/postalhq/postal/wiki/Using-the-API


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Postal backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.postal.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_POSTAL_API_KEY

.. rubric:: POSTAL_API_KEY

Required. A Postal API key.

  .. code-block:: python

      ANYMAIL = {
          ...
          "POSTAL_API_KEY": "<your api key>",
      }

Anymail will also look for ``POSTAL_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["POSTAL_API_KEY"]``
nor ``ANYMAIL_POSTAL_API_KEY`` is set.


.. setting:: ANYMAIL_POSTAL_API_URL

.. rubric:: POSTAL_API_URL

Required. The base url for calling the Postal API.


.. setting:: ANYMAIL_POSTAL_WEBHOOK_KEY

.. rubric:: POSTAL_WEBHOOK_KEY

Required when using status tracking or inbound webhooks.

This should be set to the public key of the Postal instance.
You can find it by running `postal default-dkim-record` on your
Postal instance.
Use the part that comes after `p=`, until the semicolon at the end.


.. _postal-esp-extra:

esp_extra support
-----------------

To use Postal features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` that will be merged into the json sent to Postal's
`email API`_.

Example:

    .. code-block:: python

        message.esp_extra = {
            'HypotheticalFuturePostalParam': '2022',  # merged into send params
        }


(You can also set `"esp_extra"` in Anymail's
:ref:`global send defaults <send-defaults>` to apply it to all
messages.)


.. _email API: https://krystal.github.io/postal-api/controllers/send/message


Limitations and quirks
----------------------

Postal does not support a few tracking and reporting additions offered by other ESPs.

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using features that Postal doesn't support
You can tell Anymail to suppress these errors and send the messages anyway --
see :ref:`unsupported-features`.

**Single tag**
  Postal allows a maximum of one tag per message. If your message has two or more
  :attr:`~anymail.message.AnymailMessage.tags`, you'll get an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error---or
  if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first tag.

**No delayed sending**
  Postal does not support :attr:`~anymail.message.AnymailMessage.send_at`.

**Toggle click-tracking and open-tracking**
  By default, Postal does not enable click-tracking and open-tracking.
  To enable it, `see their docs on click- & open-tracking`_.
  Anymail's :attr:`~anymail.message.AnymailMessage.track_clicks` and
  :attr:`~anymail.message.AnymailMessage.track_opens` settings are unsupported.

.. _see their docs on click- & open-tracking: https://github.com/postalhq/postal/wiki/Click-&-Open-Tracking

**Attachments must be named**
  Postal issues an `AttachmentMissingName` error when trying to send an attachment without name.

**No merge features**
  Because Postal does not support batch sending, Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_headers`,
  :attr:`~anymail.message.AnymailMessage.merge_metadata`,
  and :attr:`~anymail.message.AnymailMessage.merge_data`
  are not supported.


.. _postal-templates:

Batch sending/merge and ESP templates
-------------------------------------

Postal does not support batch sending or ESP templates.


.. _postal-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, set up
a webhook in your Postal mail server settings, under Webhooks. The webhook URL is:

   :samp:`https://{yoursite.example.com}/anymail/postal/tracking/`

   * *yoursite.example.com* is your Django site

Choose all the event types you want to receive.

Postal signs its webhook payloads. You need to set :setting:`ANYMAIL_POSTAL_WEBHOOK_KEY`.

If you use multiple Postal mail servers, you'll need to repeat entering the webhook
settings for each of them.

Postal will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
failed, bounced, deferred, queued, delivered, clicked.

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of Postal's `webhook <https://github.com/postalhq/postal/wiki/Webhook-Events-&-Payloads>`_ data.

.. _postal-inbound:

Inbound webhook
---------------

If you want to receive email from Postal through Anymail's normalized :ref:`inbound <inbound>`
handling, follow Postal's guide to for receiving emails (Help > Receiving Emails) to create an
incoming route. Then set up an `HTTP Endpoint`, pointing to Anymail's inbound webhook.

The url will be:

   :samp:`https://{yoursite.example.com}/anymail/postal/inbound/`

     * *yoursite.example.com* is your Django site

Set `Format` to `Delivered as the raw message`.

You also need to set :setting:`ANYMAIL_POSTAL_WEBHOOK_KEY` to enable signature validation.
