.. _mailjet-backend:

Mailjet
=======

Anymail integrates with the `Mailjet`_ email service, using their transactional `Send API v3.1`_.

.. versionchanged:: 8.0

    Earlier Anymail versions used Mailjet's older `Send API v3`_. The change to v3.1 fixes
    some limitations of the earlier API, and should only affect your code if you use Anymail's
    :ref:`esp_extra <mailjet-esp-extra>` feature to set API-specific options or if you are
    trying to send messages with :ref:`multiple reply-to addresses <mailjet-quirks>`.


.. _Mailjet: https://www.mailjet.com/
.. _Send API v3.1: https://dev.mailjet.com/guides/#send-api-v3-1
.. _Send API v3: https://dev.mailjet.com/guides/#send-api-v3


Settings
--------


.. rubric:: EMAIL_BACKEND

To use Anymail's Mailjet backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailjet.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILJET_API_KEY

.. rubric:: MAILJET_API_KEY and MAILJET_SECRET_KEY

Your Mailjet API key and secret key, from your Mailjet account REST API settings
under `API Key Management`_. (Mailjet's documentation also sometimes uses
"API private key" to mean the same thing as "secret key.")

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILJET_API_KEY": "<your API key>",
          "MAILJET_SECRET_KEY": "<your API secret>",
      }

You can use either the main account or a sub-account API key.

Anymail will also look for ``MAILJET_API_KEY`` and ``MAILJET_SECRET_KEY`` at the
root of the settings file if neither ``ANYMAIL["MAILJET_API_KEY"]``
nor ``ANYMAIL_MAILJET_API_KEY`` is set.

.. _API Key Management: https://app.mailjet.com/account/apikeys


.. setting:: ANYMAIL_MAILJET_API_URL

.. rubric:: MAILJET_API_URL

The base url for calling the Mailjet API.

The default is ``MAILJET_API_URL = "https://api.mailjet.com/v3.1/"``
(It's unlikely you would need to change this.)


.. _mailjet-esp-extra:

esp_extra support
-----------------

To use Mailjet features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` of Mailjet's `Send API body parameters`_.
Your :attr:`esp_extra` dict will be deeply merged into the Mailjet
API payload, with `esp_extra` having precedence in conflicts.

(Note that it's *not* possible to merge into the ``"Messages"`` key;
any value you supply would override ``"Messages"`` completely. Use ``"Globals"``
for options to apply to all messages.)

Example:

    .. code-block:: python

        message.esp_extra = {
            # Most "Messages" options can be included under Globals:
            "Globals": {
              "Priority": 3,  # Use Mailjet critically-high priority queue
              "TemplateErrorReporting": {"Email": "dev+mailtemplatebug@example.com"},
            },
            # A few options must be at the root:
            "SandboxMode": True,
            "AdvanceErrorHandling": True,
            # *Don't* try to set Messages:
            # "Messages": [... this would override *all* recipients, not be merged ...]
        }


(You can also set `"esp_extra"` in Anymail's :ref:`global send defaults <send-defaults>`
to apply it to all messages.)

.. _Send API body parameters:
   https://dev.mailjet.com/email/reference/send-emails#v3_1_post_send


.. _mailjet-quirks:

Limitations and quirks
----------------------

**Single reply_to**
  Mailjet's API only supports a single Reply-To email address. If your message
  has two or more, you'll get an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
  error---or if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first `reply_to` address.

**Single tag**
  Anymail uses Mailjet's `campaign`_ option for tags, and Mailjet allows
  only a single campaign per message. If your message has two or more
  :attr:`~anymail.message.AnymailMessage.tags`, you'll get an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error---or
  if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first tag.

.. _campaign: https://dev.mailjet.com/guides/#grouping-into-a-campaign

**No delayed sending**
  Mailjet does not support :attr:`~anymail.message.AnymailMessage.send_at`.

**Envelope sender may require approval**
  Anymail passes :attr:`~anymail.message.AnymailMessage.envelope_sender` to
  Mailjet, but this may result in an API error if you have not received
  special approval from Mailjet support to use custom senders.

**message_id is MessageID (not MessageUUID)**
  Mailjet's Send API v3.1 returns both a "legacy" MessageID and a newer
  MessageUUID for each successfully sent message. Anymail uses the MessageID
  as the :attr:`~anymail.message.AnymailStatus.message_id` when reporting
  :ref:`esp-send-status`, because Mailjet's other (statistics, event tracking)
  APIs don't yet support MessageUUID.

**Older limitations**

.. versionchanged:: 6.0

    Earlier versions of Anymail were unable to mix ``cc`` or ``bcc`` fields
    and :attr:`~anymail.message.AnymailMessage.merge_data` in the same Mailjet message.
    This limitation was removed in Anymail 6.0.

.. versionchanged:: 8.0

    Earlier Anymail versions had special handling to work around a Mailjet v3 API bug
    with commas in recipient display names. Anymail 8.0 uses Mailjet's v3.1 API, which
    does not have the bug.


.. _mailjet-templates:

Batch sending/merge and ESP templates
-------------------------------------

Mailjet offers both :ref:`ESP stored templates <esp-stored-templates>`
and :ref:`batch sending <batch-send>` with per-recipient merge data.

When you send a message with multiple ``to`` addresses, the
:attr:`~anymail.message.AnymailMessage.merge_data` determines how many
distinct messages are sent:

* If :attr:`~anymail.message.AnymailMessage.merge_data` is *not* set (the default),
  Anymail will tell Mailjet to send a single message, and all recipients will see
  the complete list of To addresses.
* If :attr:`~anymail.message.AnymailMessage.merge_data` *is* set---even to an empty
  `{}` dict, Anymail will tell Mailjet to send a separate message for each ``to``
  address, and the recipients won't see the other To addresses.

You can use a Mailjet stored transactional template by setting a message's
:attr:`~anymail.message.AnymailMessage.template_id` to the
template's *numeric* template ID. (*Not* the template's name. To get the
numeric template id, click on the name in your Mailjet `transactional templates`_,
then look for "Template ID" above the preview that appears.)

Supply the template merge data values with Anymail's
normalized :attr:`~anymail.message.AnymailMessage.merge_data`
and :attr:`~anymail.message.AnymailMessage.merge_global_data`
message attributes.

  .. code-block:: python

      message = EmailMessage(
          ...
          # omit subject and body (or set to None) to use template content
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = "176375"  # Mailjet numeric template id
      message.from_email = None  # Use the From address stored with the template
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
      }

Any ``from_email`` in your EmailMessage will override the template's default sender
address. To use the template's sender, you must explicitly set ``from_email = None``
after creating the EmailMessage, as shown above. (If you omit this, Django's default
:setting:`DEFAULT_FROM_EMAIL` will be used.)

Instead of creating a stored template at Mailjet, you can also refer to merge fields
directly in an EmailMessage's body---the message itself is used as an on-the-fly template:

  .. code-block:: python

      message = EmailMessage(
          from_email="orders@example.com",
          to=["alice@example.com", "Bob <bob@example.com>"],
          subject="Your order has shipped",  # subject doesn't support on-the-fly merge fields
          # Use [[var:FIELD]] to for on-the-fly merge into plaintext or html body:
          body="Dear [[var:name]]: Your order [[var:order_no]] shipped on [[var:ship_date]]."
      )
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
      }

(Note that on-the-fly templates use square brackets to indicate `"personalization"`_ merge fields,
rather than the curly brackets used with stored templates in Mailjet's template language.)

See Mailjet's `template documentation`_ and `template language`_ docs
for more information.

.. _transactional templates: https://app.mailjet.com/templates/transactional
.. _"personalization": https://dev.mailjet.com/guides/#personalisation
.. _template documentation: https://www.mailjet.com/docs/template_builder_transactional
.. _template language: https://dev.mailjet.com/template-language/


.. _mailjet-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, enter
the url in your Mailjet account REST API settings under `Event tracking (triggers)`_:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailjet/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Be sure to enter the URL in the Mailjet settings for all the event types you want to receive.
It's also recommended to select the "group events" checkbox for each trigger, to minimize your
server load.

Mailjet will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
rejected, bounced, deferred, delivered, opened, clicked, complained, unsubscribed.

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of `Mailjet event`_ fields, for a single event. (Although Mailjet calls
webhooks with batches of events, Anymail will invoke your signal receiver separately
for each event in the batch.)

.. _Event tracking (triggers): https://app.mailjet.com/account/triggers
.. _Mailjet event: https://dev.mailjet.com/guides/#events


.. _mailjet-inbound:

Inbound webhook
---------------

If you want to receive email from Mailjet through Anymail's normalized :ref:`inbound <inbound>`
handling, follow Mailjet's `Parse API inbound emails`_ guide to set up Anymail's inbound webhook.

The parseroute Url parameter will be:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailjet/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Once you've done Mailjet's "basic setup" to configure the Parse API webhook, you can skip
ahead to the "use your own domain" section of their guide. (Anymail normalizes the inbound
event for you, so you won't need to worry about Mailjet's event and attachment formats.)

.. _Parse API inbound emails:
    https://dev.mailjet.com/guides/#parse-api-inbound-emails
