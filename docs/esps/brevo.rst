.. _brevo-backend:
.. _sendinblue-backend:

Brevo
=====

.. Docs note: esps/sendinblue is redirected to esps/brevo in ReadTheDocs config.
   Please preserve existing _sendinblue-* ref labels, so that redirected link
   anchors work properly (in old links from external sites). E.g.:
     an old link:   https://anymail.dev/en/stable/esps/sendinblue#sendinblue-templates
     redirects to:  https://anymail.dev/en/stable/esps/brevo#sendinblue-templates
     which is also: https://anymail.dev/en/stable/esps/brevo#brevo-templates
   (There's no need to create _sendinblue-* duplicates of any new _brevo-* labels.)

Anymail integrates with the `Brevo`_ email service (formerly Sendinblue), using their `API v3`_.
Brevo's transactional API does not support some basic email features, such as
inline images. Be sure to review the :ref:`limitations <brevo-limitations>` below.

.. versionchanged:: 10.3

   SendinBlue rebranded as Brevo in May, 2023. Anymail 10.3 uses the new
   name throughout its code; earlier versions used the old name. Code that
   refers to "SendinBlue" should continue to work, but is now deprecated.
   See :ref:`brevo-rename` for details.

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

      EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_BREVO_API_KEY

.. rubric:: BREVO_API_KEY

The API key can be retrieved from your Brevo `SMTP & API settings`_ on the
"API Keys" tab (don't try to use an SMTP key). Required.

Make sure the version column indicates "v3." (v2 keys don't work with
Anymail. If you don't see a v3 key listed, use "Create a New API Key".)

  .. code-block:: python

      ANYMAIL = {
          ...
          "BREVO_API_KEY": "<your v3 API key>",
      }

Anymail will also look for ``BREVO_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["BREVO_API_KEY"]``
nor ``ANYMAIL_BREVO_API_KEY`` is set.

.. _SMTP & API settings: https://app.brevo.com/settings/keys/api


.. setting:: ANYMAIL_BREVO_API_URL

.. rubric:: BREVO_API_URL

The base url for calling the Brevo API.

The default is ``BREVO_API_URL = "https://api.brevo.com/v3/"``
(It's unlikely you would need to change this.)

.. versionchanged:: 10.1

   Earlier Anymail releases used ``https://api.sendinblue.com/v3/``.


.. _brevo-esp-extra:
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


.. _brevo-limitations:
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

**Metadata exposed in message headers**
  Anymail passes :attr:`~anymail.message.AnymailMessage.metadata` to Brevo
  as a JSON-encoded string using their :mailheader:`X-Mailin-custom` email header.
  This header is included in the sent message, so **metadata will be visible to
  message recipients** if they view the raw message source.

**Metadata and extra_headers values must be ASCII**
  Brevo's API incorrectly handles non-ASCII Unicode characters in custom email
  headers, sending them as raw utf-8. Unencoded 8-bit values in an email header
  are usually invalid, and can cause bounces or silently undelivered messages.

  Anymail is not able to work around this problem, so will raise an
  :exc:`AnymailUnsupportedFeature` error for non-ASCII ``extra_headers`` or
  :attr:`~anymail.message.AnymailMessage.merge_headers` values.

  Because Anymail's metadata uses Brevo's :mailheader:`X-Mailin-custom` header,
  this also affects :attr:`~anymail.message.AnymailMessage.metadata` and
  :attr:`~anymail.message.AnymailMessage.merge_metadata`.

  .. versionchanged:: vNext

     Earlier releases did not detect this situation and could send
     undeliverable messages with non-ASCII headers or metadata.

**Avoid mixing non-ASCII characters and punctuation in Reply-To**
  Brevo's API incorrectly handles non-ASCII characters combined with commas and
  certain other punctuation in address header display names.

  Anymail is able to work around the problem in ``to``, ``cc`` and ``bcc`` names.
  It applies the same workaround to ``reply_to`` names, but this triggers another
  Brevo bug that may cause some recipients to see an RFC 2047 encoded-word
  (``=?utf-8?...``) in their email client .

  .. versionchanged:: vNext

     Earlier releases did not include the workaround, resulting in Brevo
     sending messages with potentially missing display names in ``to``, ``cc``
     and ``bcc`` and possibly undeliverable messages for ``reply_to``.

**Special headers**
  Brevo uses special email headers to control certain features.
  You can set these using Django's
  :class:`EmailMessage.headers <django.core.mail.EmailMessage>`:

    .. code-block:: python

        message = EmailMessage(
            ...,
            headers = {
                "sender.ip": "10.10.1.150",  # use a dedicated IP
                "idempotencyKey": "...uuid...",  # batch send deduplication
            }
        )

        # Note the constructor param is called `headers`, but the
        # corresponding attribute is named `extra_headers`:
        message.extra_headers = {
            "sender.ip": "10.10.1.222",
            "idempotencyKey": "...uuid...",
        }

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

**Non-ASCII mailboxes (EAI)**
  Brevo partially supports sending from or to Unicode mailboxes (the *user* part
  of *user\@domain*---see :ref:`EAI <eai>`). Messages are delivered correctly,
  but in the ``to`` field any display name with an EAI address will be missing
  from the delivered message. And if any EAI address appears in the ``cc`` field,
  the entire :mailheader:`Cc` header will be omitted, making it effectively a ``bcc``.

  Also, Brevo does not properly verify the receiving SMTP server supports EAI
  (smtputf8). For valid EAI recipient addresses, this generally shouldn't cause
  problems. For an EAI ``from_email`` or ``reply_to`` this could result in lost
  or undeliverable messages.


.. _brevo-templates:
.. _sendinblue-templates:

Batch sending/merge and ESP templates
-------------------------------------

.. versionchanged:: 10.3

    Added support for batch sending with :attr:`~anymail.message.AnymailMessage.merge_data`
    and :attr:`~anymail.message.AnymailMessage.merge_metadata`.

Brevo supports :ref:`ESP stored templates <esp-stored-templates>` and
:ref:`batch sending <batch-send>` with per-recipient merge data.

To use a Brevo template, set the message's
:attr:`~anymail.message.AnymailMessage.template_id` to the numeric
Brevo template ID, and supply substitution params using Anymail's normalized
:attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_global_data` message attributes:

  .. code-block:: python

      message = EmailMessage(
          # (subject and body come from the template, so don't include those)
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = 3   # use this Brevo template
      message.from_email = None  # to use the template's default sender
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
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

Brevo also supports batch-sending without using an ESP-stored template. In this
case, each recipient will receive the same content (Brevo doesn't support inline
templates) but will see only their own *To* email address. Setting either of
:attr:`~anymail.message.AnymailMessage.merge_data` or
:attr:`~anymail.message.AnymailMessage.merge_metadata`---even to an empty
dict---will cause Anymail to use Brevo's batch send option (``"messageVersions"``).

You can use Anymail's
:attr:`~anymail.message.AnymailMessage.merge_metadata` to supply custom tracking
data for each recipient:

  .. code-block:: python

      message = EmailMessage(
          to=["alice@example.com", "Bob <bob@example.com>"],
          from_email="...", subject="...", body="..."
      )
      message.merge_metadata = {
          'alice@example.com': {'user_id': "12345"},
          'bob@example.com': {'user_id': "54321"},
      }

To use Brevo's "`idempotencyKey`_" with a batch send, set it in the
message's headers: ``message.extra_headers = {"idempotencyKey": "...uuid..."}``.

.. caution::

    **"Old template language" not supported**

    Brevo once supported two different template styles: a "new" template
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

.. _idempotencyKey:
    https://developers.brevo.com/docs/heterogenous-versions-batch-emails

.. _convert each old template:
    https://help.brevo.com/hc/en-us/articles/360000991960


.. _brevo-webhooks:
.. _sendinblue-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, add
the url at Brevo's site under `Transactional > Email > Settings > Webhook`_.

The "URL to call" is:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/brevo/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Be sure to select the checkboxes for all the event types you want to receive. (Also make
sure you are in the "Transactional" section of their site; Brevo has a separate set
of "Campaign" webhooks, which don't apply to messages sent through Anymail.)

If you are interested in tracking opens, note that Brevo has four different
open event types:

* "First opening": the first time a message is opened by a particular recipient.
  (Brevo event type "opened")
* "Known open": the second and subsequent opens. (Brevo event type "unique_opened")
* "Loaded by proxy": a message's tracking pixel is loaded by a proxy service
  intended to protect users' IP addresses. See Brevo's article on
  `Apple's Mail Privacy Protection`_ for more details. As of July, 2024, Brevo
  seems to deliver this event only for the second and subsequent loads by the
  proxy service. (Brevo event type "proxy_open")
* "First open but loaded by proxy": the first time a message's tracking pixel
  is loaded by a proxy service for a particular recipient. As of July, 2024,
  this event has not yet been exposed in Brevo's webhook control panel, and
  you must contact Brevo support to enable it. (Brevo event type "unique_proxy_opened")

Anymail normalizes all of these to "opened." If you need to distinguish the
specific Brevo event types, examine the raw
:attr:`~anymail.signals.AnymailTrackingEvent.esp_event`, e.g.:
``if event.esp_event["event"] == "unique_opened": …``.

Brevo will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
queued, rejected, bounced, deferred, delivered, opened (see note above), clicked, complained,
failed, unsubscribed, subscribed (though subscribed should never occur for transactional email).

For events that occur in rapid succession, Brevo frequently delivers them out of order.
For example, it's not uncommon to receive a "delivered" event before the corresponding "queued."
Also, note that "queued" may be received even if Brevo will not actually send the message.
(E.g., if a recipient is on your blocked list due to a previous bounce, you may receive
"queued" followed by "rejected.")

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of raw webhook data received from Brevo.

.. versionchanged:: 10.3

    Older Anymail versions used a tracking webhook URL containing "sendinblue" rather
    than "brevo". The old URL will still work, but is deprecated. See :ref:`brevo-rename`
    below.

.. versionchanged:: 11.1

    Added support for Brevo's "Complaint," "Error" and "Loaded by proxy" events.


.. _Transactional > Email > Settings > Webhook: https://app-smtp.brevo.com/webhook
.. _Apple's Mail Privacy Protection:
    https://help.brevo.com/hc/en-us/articles/4406537065618-How-to-handle-changes-in-Apple-s-Mail-Privacy-Protection


.. _brevo-inbound:
.. _sendinblue-inbound:

Inbound webhook
---------------

.. versionadded:: 10.1

If you want to receive email from Brevo through Anymail's normalized
:ref:`inbound <inbound>` handling, follow Brevo's `Inbound parsing webhooks`_
guide to enable inbound service and add Anymail's inbound webhook.

At the "Creating the webhook" step, set the ``"url"`` param to:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/brevo/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Brevo does not currently seem to have a dashboard for managing or monitoring
inbound service. However, you can run API calls directly from their documentation
by entering your API key in "Header" field above the example, and then clicking
"Try It!". The `webhooks management APIs`_ and `inbound events list API`_ can
be helpful for diagnosing inbound issues.

.. versionchanged:: 10.3

    Older Anymail versions used an inbound webhook URL containing "sendinblue" rather
    than "brevo". The old URL will still work, but is deprecated. See :ref:`brevo-rename`
    below.


.. _Inbound parsing webhooks:
    https://developers.brevo.com/docs/inbound-parse-webhooks
.. _webhooks management APIs:
    https://developers.brevo.com/reference/getwebhooks-1
.. _inbound events list API:
    https://developers.brevo.com/reference/getinboundemailevents


.. _brevo-rename:

Updating code from SendinBlue to Brevo
--------------------------------------

SendinBlue rebranded as Brevo in May, 2023. Anymail 10.3 has switched
to the new name.

If your code refers to the old "sendinblue" name
(in :setting:`!EMAIL_BACKEND` and :setting:`!ANYMAIL` settings, :attr:`!esp_name`
checks, or elsewhere) you should update it to use "brevo" instead.
If you are using Anymail's tracking or inbound webhooks, you should
also update the webhook URLs you've configured at Brevo.

For compatibility, code and URLs using the old name are still functional in Anymail.
But they will generate deprecation warnings, and may be removed in a future release.

To update your code:

.. setting:: ANYMAIL_SENDINBLUE_API_KEY
.. setting:: ANYMAIL_SENDINBLUE_API_URL

1.  In your settings.py, update the :setting:`!EMAIL_BACKEND`
    and rename any ``"SENDINBLUE_..."`` settings to ``"BREVO_..."``:

    .. code-block:: diff

      - EMAIL_BACKEND = "anymail.backends.sendinblue.EmailBackend"  # old
      + EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"       # new

        ANYMAIL = {
            ...
      -     "SENDINBLUE_API_KEY": "<your v3 API key>",  # old
      +     "BREVO_API_KEY": "<your v3 API key>",       # new
            # (Also change "SENDINBLUE_API_URL" to "BREVO_API_URL" if present)

            # If you are using Brevo-specific global send defaults, change:
      -     "SENDINBLUE_SEND_DEFAULTS" = {...},  # old
      +     "BREVO_SEND_DEFAULTS" = {...},       # new
        }

2.  If you are using Anymail's status tracking webhook,
    go to Brevo's dashboard (under `Transactional > Email > Settings > Webhook`_),
    and change the end of the URL from ``.../anymail/sendinblue/tracking/``
    to ``.../anymail/brevo/tracking/``. (Or use the code below to automate this.)

    In your :ref:`tracking signal receiver function <signal-receivers>`,
    if you are examining the ``esp_name`` parameter, the name will change
    once you have updated the webhook URL. If you had been checking
    whether ``esp_name == "SendinBlue"``, change that to check if
    ``esp_name == "Brevo"``.

3.  If you are using Anymail's inbound handling, update the inbound webhook
    URL to change ``.../anymail/sendinblue/inbound/`` to ``.../anymail/brevo/inbound/``.
    You will need to use Brevo's webhooks API to make the change---see below.

    In your :ref:`inbound signal receiver function <inbound-signal-receivers>`,
    if you are examining the ``esp_name`` parameter, the name will change
    once you have updated the webhook URL. If you had been checking
    whether ``esp_name == "SendinBlue"``, change that to check if
    ``esp_name == "Brevo"``.

That should be everything, but to double check you may want to search your
code for any remaining references to "sendinblue" (case-insensitive).
(E.g., ``grep -r -i sendinblue``.)

To update both the tracking and inbound webhook URLs using Brevo's `webhooks API`_,
you could run something like this Python code:

.. code-block:: python

    # Update Brevo webhook URLs to replace "anymail/sendinblue" with "anymail/brevo".
    import requests
    BREVO_API_KEY = "<your API key>"

    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
    }

    response = requests.get("https://api.brevo.com/v3/webhooks", headers=headers)
    response.raise_for_status()
    webhooks = response.json()

    for webhook in webhooks:
        if "anymail/sendinblue" in webhook["url"]:
            response = requests.put(
                f"https://api.brevo.com/v3/webhooks/{webhook['id']}",
                headers=headers,
                json={
                    "url": webhook["url"].replace("anymail/sendinblue", "anymail/brevo")
                }
            )
            response.raise_for_status()

.. _webhooks API: https://developers.brevo.com/reference/updatewebhook-1
