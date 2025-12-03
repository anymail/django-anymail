.. _mailersend-backend:

MailerSend
==========

Anymail integrates Django with the `MailerSend`_ transactional
email service, using their `email API`_ endpoint.

.. _MailerSend: https://www.mailersend.com/
.. _email API: https://developers.mailersend.com/api/v1/email.html


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's MailerSend backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailersend.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILERSEND_API_TOKEN

.. rubric:: MAILERSEND_API_TOKEN

Required for sending. A MailerSend API token generated in your MailerSend
`Email domains settings`_. For the token permission level, "custom access"
is recommended, with full access to email and *no access* for all other features.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILERSEND_API_TOKEN": "<your API token>",
      }

Anymail will also look for ``MAILERSEND_API_TOKEN`` at the
root of the settings file if neither ``ANYMAIL["MAILERSEND_API_TOKEN"]``
nor ``ANYMAIL_MAILERSEND_API_TOKEN`` is set.

If your Django project sends email from multiple MailerSend domains,
you will need a separate API token for each domain. Use the token matching
your :setting:`DEFAULT_FROM_EMAIL` domain in settings.py, and then override
where necessary for individual emails by setting ``"api_token"`` in the
message's :ref:`esp_extra <mailersend-esp-extra>`. (You could centralize
this logic using Anymail's :ref:`pre-send-signal`.)


.. setting:: ANYMAIL_MAILERSEND_BATCH_SEND_MODE

.. rubric:: MAILERSEND_BATCH_SEND_MODE

If you are using Anymail's :attr:`~anymail.message.AnymailMessage.merge_data`
with multiple recipients (":ref:`batch sending <batch-send>`"), set this to
indicate how to handle the batch. See :ref:`mailersend-batch-send` below
for more information.

Choices are ``"use-bulk-email"`` or ``"expose-to-list"``. The default ``None``
will raise an error if :attr:`~!anymail.message.AnymailMessage.merge_data` is
used with more than one ``to`` recipient.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILERSEND_BATCH_SEND_MODE": "use-bulk-email",
      }


.. setting:: ANYMAIL_MAILERSEND_SIGNING_SECRET

.. rubric:: MAILERSEND_SIGNING_SECRET

The MailerSend webhook signing secret needed to verify webhook posts.
Required if you are using activity tracking, otherwise not necessary.
(This is separate from Anymail's
:setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>` setting.)

Find this in your MailerSend `Email domains settings`_: after adding
a webhook, look for the "signing secret" on the webhook's management page.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILERSEND_SIGNING_SECRET": "<secret from webhook management page>",
      }

MailerSend generates a unique secret for each webhook; if you edit
your webhook you will need to update this setting with the new signing secret.
(Also, inbound routes use a *different* secret, with a different setting---see
below.)


.. setting:: ANYMAIL_MAILERSEND_INBOUND_SECRET

.. rubric:: MAILERSEND_INBOUND_SECRET

The MailerSend inbound route secret needed to verify inbound notifications.
Required if you are using inbound routing, otherwise not necessary.

Find this in your MailerSend `Email domains settings`_: after you have
added an inbound route, look for the "secret" immediately below the route url
on the management page for that inbound route.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILERSEND_INBOUND_SECRET": "<secret from inbound management page>",
      }

MailerSend generates a unique secret for each inbound route url; if you edit
your route you will need to update this setting with the new secret.
(Also, activity tracking webhooks use a *different* secret, with a different
setting---see above.)


.. setting:: ANYMAIL_MAILERSEND_API_URL

.. rubric:: MAILERSEND_API_URL

The base url for calling the MailerSend API.

The default is ``MAILERSEND_API_URL = "https://api.mailersend.com/v1/"``.
(It's unlikely you would need to change this.)


.. _Email domains settings: https://app.mailersend.com/domains


.. _mailersend-esp-extra:

exp_extra support
-----------------

Anymail's MailerSend backend will pass :attr:`~anymail.message.AnymailMessage.esp_extra`
values directly to MailerSend's `email API`_.

In addition, you can override the
:setting:`MAILERSEND_API_TOKEN <ANYMAIL_MAILERSEND_API_TOKEN>` for an individual
message by providing ``"api-token"``, and
:setting:`MAILERSEND_BATCH_SEND_MODE <ANYMAIL_MAILERSEND_BATCH_SEND_MODE>`
by providing ``"batch-send-mode"`` in the
:attr:`~!anymail.message.AnymailMessage.esp_extra` dict.

Example:

  .. code-block:: python

      message = AnymailMessage(...)
      message.esp_extra = {
          # override your MailerSend domain's content tracking default:
          "settings": {"track_content": False},

          # use a different MAILERSEND_API_TOKEN for this message:
          "api_token": MAILERSEND_API_TOKEN_FOR_MARKETING_DOMAIN,

          # override the MAILERSEND_BATCH_SEND_MODE setting
          # just for this message:
          "batch_send_mode": "use-bulk-email",
      }

Nested values are merged deeply. When sending using MailerSend's bulk-email API
endpoint, the :attr:`~!anymail.message.AnymailMessage.esp_extra` params are merged
into the payload for every individual message in the batch.


.. _mailersend-quirks:

Limitations and quirks
----------------------

MailerSend does not support a few features offered by some other ESPs.

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using features that MailerSend doesn't support
You can tell Anymail to suppress these errors and send the messages anyway --
see :ref:`unsupported-features`.

**Attachments require filenames, ignore content type**
  MailerSend requires every attachment (even inline ones) to have a filename.
  And it determines the content type of the attachment from the filename extension.

  If you try to send an attachment without a filename, Anymail will substitute
  "attachment*.ext*" using an appropriate *.ext* for the content type.

  If you try to send an attachment whose content type doesn't match its filename
  extension, MailerSend will change the content type to match the extension.
  (E.g., the filename "data.txt" will always be sent as "text/plain",
  even if you specified a "text/csv" content type.)

**Single Reply-To**
  MailerSend only supports a single Reply-To address.

  If your message has multiple reply addresses, you'll get an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error---or
  if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first one.

**Limited extra headers**
  MailerSend allows extra email headers for "Enterprise accounts only."
  If you try to send :ref:`extra headers <message-headers>` with a non-enterprise
  account, you may receive an API error.

  However, MailerSend has special handling for two headers,
  and *any* MailerSend account can send messages with them:

  * You can include :mailheader:`In-Reply-To` in extra headers, set to
    a message-id (without the angle brackets).

  * You can include :mailheader:`Precedence` in extra headers to override
    the "Add precedence bulk header" option from your MailerSend domain
    advanced settings (look under "More settings").
    Anymail will set MailerSend's ``precedence_bulk`` param to ``true``
    if your extra headers have :mailheader:`Precedence` set to ``"bulk"`` or
    ``"list"`` or ``"junk"``, or ``false`` for any other value.

  .. versionchanged:: 11.0

      In earlier releases, attempting to send other headers
      (even with an enterprise account) would raise an
      :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error.

**No merge headers support**
  MailerSend's API does not provide a way to support Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_headers`.

**No metadata support**
  MailerSend does not support Anymail's
  :attr:`~anymail.message.AnymailMessage.metadata` or
  :attr:`~anymail.message.AnymailMessage.merge_metadata` features.

**No envelope sender overrides**
  MailerSend does not support overriding
  :attr:`~anymail.message.AnymailMessage.envelope_sender` on individual messages.
  (To use a `MailerSend sender identity`_, set the verified identity's
  email address as the message's
  :attr:`~!django.core.email.message.EmailMessage.from_email`.)

.. _MailerSend sender identity:
   https://www.mailersend.com/help/send-email-on-behalf-of-clients

**API rate limits**
  MailerSend provides `rate limit headers`_ with each API call response.
  To access them after a successful send, use (e.g.,)
  ``message.anymail_status.esp_response.headers["x-ratelimit-remaining"]``.

  If you exceed a rate limit, you'll get an :exc:`~anymail.exceptions.AnymailAPIError`
  with ``error.status_code == 429``, and can determine how many seconds to wait
  from ``error.response.headers["retry-after"]``.

.. _rate limit headers:
   https://developers.mailersend.com/general.html#rate-limits

**No non-ASCII mailboxes (EAI)**
  Mailersend does not support sending from or to Unicode mailboxes (the *user* part
  of *user\@domain*---see :ref:`EAI <eai>`). Trying to use one will cause an API error.


.. _mailersend-templates:

Batch sending/merge and ESP templates
-------------------------------------

MailerSend supports :ref:`ESP stored templates <esp-stored-templates>`, on-the-fly
templating, and :ref:`batch sending <batch-send>` with per-recipient merge data.
MailerSend's approaches to batch sending don't align perfectly with Anymail's;
be sure to read :ref:`mailersend-batch-send` below to understand the options.

MailerSend offers two different syntaxes for substituting data into templates:
"`simple personalization`_" and "`advanced personalization`_." Anymail supports
*only* the more flexible advanced personalization syntax. If you have MailerSend
templates using the "simple" syntax (``{$variable_name}``), you'll need to convert
them to the "advanced" syntax (``{{ variable_name }}``) for use with Anymail's
:attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_global_data`.

Here's an example defining an on-the-fly template that uses MailerSend advanced
personalization variables:

  .. code-block:: python

      message = EmailMessage(
          from_email="shipping@example.com",
          subject="Your order {{ order_no }} has shipped",
          body="""Hi {{ name }},
                  We shipped your order {{ order_no }}
                  on {{ ship_date }}.""",
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      # (you'd probably also set a similar html body with variables)
      message.merge_data = {
          "alice@example.com": {"name": "Alice", "order_no": "12345"},
          "bob@example.com": {"name": "Bob", "order_no": "54321"},
      }
      message.merge_global_data = {
          "ship_date": "May 15"  # Anymail maps globals to all recipients
      }
      # (see discussion of batch-send-mode below)
      message.esp_extra = {
          "batch-send-mode": "use-bulk-email"
      }

To send the same message with a `MailerSend stored template`_ from your account,
set :attr:`~anymail.message.AnymailMessage.template_id`, and omit any plain-text
or html `~!django.core.mail.EmailMessage.body`. If you've set a subject in your
MailerSend template's default settings, you can omit
`~!django.core.mail.EmailMessage.subject` (otherwise you must include it).
And if your template default settings specify the *From* email, that will override
`~!django.core.mail.EmailMessage.from_email`. Example:

  .. code-block:: python

      message = EmailMessage(
          from_email="shipping@example.com",
          # (subject and body from template)
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = "vzq12345678"  # id of template in our account
      # ... set merge_data and merge_global_data as above

MailerSend does not natively support global merge data. Anymail emulates
the capability by copying any :attr:`~anymail.message.AnymailMessage.merge_global_data`
values to every recipient.

.. _simple personalization:
   https://www.mailersend.com/help/how-to-use-variables#simple-personalization
.. _advanced personalization:
   https://www.mailersend.com/help/how-to-use-variables#advanced-personalization
.. _MailerSend stored template:
   https://www.mailersend.com/help/how-to-create-a-template


.. _mailersend-batch-send:

Batch send mode
~~~~~~~~~~~~~~~

Anymail's model for :ref:`batch sending <batch-send>` is that each recipient
receives a separate email personalized for them, and that each recipient sees
*only their own email address* in the message's :mailheader:`To` header.

MailerSend has a `bulk-email API`_ that matches Anymail's batch sending model,
but operates completely asynchronously, which can complicate status tracking
and error handling.

MailerSend also supports batch sending personalized emails through
its regular `email API`_, which avoids the bulk-email limitations but
exposes the entire :mailheader:`To` list to all recipients.

If you want to use Anymail's :attr:`~anymail.message.AnymailMessage.merge_data`
for batch sending to multiple `~!django.core.mail.EmailMessage.to` recipients,
you must select one of these two approaches by specifying either ``"use-bulk-email"``
or ``"expose-to-list"`` in your Anymail
:setting:`MAILERSEND_BATCH_SEND_MODE <ANYMAIL_MAILERSEND_BATCH_SEND_MODE>` setting---or
as ``"batch-send-mode"`` in the message's :ref:`esp_extra <mailersend-esp-extra>`.

.. caution::

    Using the ``"expose-to-list"`` MailerSend batch send mode will reveal
    *all* of the message's :mailheader:`To` email addresses to *every*
    recipient of the message.

If you use the ``"use-bulk-email"`` MailerSend batch send mode:

* The
  :attr:`message.anymail_status.status <anymail.message.AnymailStatus.status>`
  will be ``{"unknown"}``, because MailerSend detects errors and rejected
  recipients at a later time.

* The
  :attr:`message.anymail_status.message_id <anymail.message.AnymailStatus.message_id>`
  will be a MailerSend ``bulk_email_id``, prefixed with ``"bulk:"`` to
  distinguish it from a regular ``message_id``.

* You will need to poll MailerSend's `bulk-email status API`_ to determine
  whether the send was successful, partially successful, or failed,
  and to determine the
  :attr:`event.message_id <anymail.signals.AnymailTrackingEvent.message_id>`
  that will be sent to status tracking webhooks.

* Be aware that rate limits for the bulk-email API are significantly lower
  than MailerSend's regular email API.

Rather than one of these batch sending options, an often-simpler approach is
to loop over your recipient list and send a separate message for each.
You can still use templates and :attr:`~!anymail.message.AnymailMessage.merge_data`:

.. code-block:: python

    # How to "manually" send a batch of emails to one recipient at a time.
    # (There's no need to specify a MailerSend "batch-send-mode".)
    to_list = ["alice@example.com", "bob@example.com"]
    merge_data = {
        "alice@example.com": {"name": "Alice", "order_no": "12345"},
        "bob@example.com": {"name": "Bob", "order_no": "54321"},
    }
    merge_global_data = {
        "ship_date": "May 15",
    }
    for to_email in to_list:
        message = AnymailMessage(
            # just one recipient per message:
            to=[to_email],
            # provide template variables for this one recipient:
            merge_global_data = merge_global_data | merge_data[to_email],
            # any other attributes you want:
            template_id = "vzq12345678",
            from_email="shipping@example.com",
        )
        try:
            message.send()
        except AnymailAPIError:
            # Handle error -- e.g., schedule for retry later.
        else:
            # Either successful send or to_email is rejected.
            # message.anymail_status will be {"queued"} or {"rejected"}.
            # message.anymail_status.message_id can be stored to match
            # with event.message_id in a status tracking signal receiver.


.. _bulk-email API:
   https://developers.mailersend.com/api/v1/email.html#send-bulk-emails
.. _bulk-email status API:
   https://developers.mailersend.com/api/v1/email.html#get-bulk-email-status


.. _mailersend-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`,
follow MailerSend's instructions to `add a webhook to your domain`_.

*   Enter this Anymail tracking URL as the webhook's "Endpoint URL"
    (where *yoursite.example.com* is your Django site):

    :samp:`https://{yoursite.example.com}/anymail/mailersend/tracking/`

    Because MailerSend implements webhook signing, it's not necessary to use Anymail's
    shared webhook secret for security with MailerSend webhooks. However, it doesn't
    hurt to use both. If you *have* set an Anymail
    :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`, include that *random:random*
    shared secret in the webhook endpoint URL:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailersend/tracking/`

*   For "Events to send", select any or all events you want to track.

*   After you have saved the webhook, go back into MailerSend's webhook
    management page, and reveal and copy the MailerSend "webhook signing secret".
    Provide that in your settings.py ``ANYMAIL`` settings as
    :setting:`MAILERSEND_SIGNING_SECRET <ANYMAIL_MAILERSEND_SIGNING_SECRET>`
    so that Anymail can verify calls to the webhook:

    .. code-block:: python

        ANYMAIL = {
            # ...
            "MAILERSEND_SIGNING_SECRET": "<secret you copied>"
        }

For troubleshooting, MailerSend provides a helpful log of calls to the webhook.
See "`About webhook attempts`_" in their documentation for more details.

.. note::

    MailerSend has a relatively short three second timeout for webhook calls.
    Be sure to avoid any lengthy operations in your Anymail tracking signal
    receiver function, or MailerSend will consider the notification failed
    at retry it. The event's :attr:`~anymail.signals.AnymailTrackingEvent.event_id`
    field can help identify duplicate notifications.

    MailerSend retries webhook notifications only twice, with delays of 10
    and then 100 seconds. If your webhook is ever offline for more than
    a couple minutes, you many miss some tracking events. You can use
    MailerSend's activity API to query for events that may have been missed.

MailerSend will report these Anymail
:attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
sent, delivered, bounced, complained, unsubscribed, opened, and clicked.

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
the *complete* parsed MailerSend webhook payload, including an additional wrapper
object not shown in their documentation. The activity data in MailerSend's
`webhook payload example`_ is available as ``event.esp_event["data"]``.

.. _add a webhook to your domain:
   https://www.mailersend.com/help/webhooks#adding-webhooks
.. _About webhook attempts:
   https://www.mailersend.com/help/webhooks#webhook-attempts
.. _webhook payload example:
   https://developers.mailersend.com/api/v1/webhooks.html#payload-example


.. _mailersend-inbound:

Inbound routing
---------------

If you want to receive email from MailerSend through Anymail's normalized
:ref:`inbound <inbound>` handling, follow MailerSend's guide to
`How to set up an inbound route`_.

*   For "Route to" (in their step 8), enter this Anymail inbound route endpoint URL
    (where *yoursite.example.com* is your Django site):

    :samp:`https://{yoursite.example.com}/anymail/mailersend/inbound/`

    Because MailerSend signs its inbound notifications, it's not necessary to use Anymail's
    shared webhook secret for security with MailerSend inbound routing. However, it doesn't
    hurt to use both. If you *have* set an Anymail
    :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`, include that *random:random*
    shared secret in the inbound route endpoint URL:

    :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailersend/inbound/`

*   After you have saved the inbound route, go back into MailerSend's inbound route
    management page, and copy the "Secret" displayed immediately below the "Route to" URL.
    Provide that in your settings.py ``ANYMAIL`` settings as
    :setting:`MAILERSEND_INBOUND_SECRET <ANYMAIL_MAILERSEND_INBOUND_SECRET>`
    so that Anymail can verify calls to the inbound endpoint:

    .. code-block:: python

        ANYMAIL = {
            # ...
            "MAILERSEND_INBOUND_SECRET": "<secret you copied>"
        }

    Note that this is a *different* secret from the
    :setting:`MAILERSEND_SIGNING_SECRET <ANYMAIL_MAILERSEND_SIGNING_SECRET>`
    used to verify activity tracking webhooks. If you are using both features,
    be sure to include both settings.

For troubleshooting, MailerSend provides a helpful inbound activity log
near the end of the route management page. See `Where to find inbound emails`_
in their docs for more details.

.. note::

    MailerSend imposes a three second limit on all notifications.
    If your inbound signal receiver function takes too long,
    MailerSend may think the notification failed. To avoid problems,
    it's essential you offload any lengthy operations to a background task.

    MailerSend does not retry failed inbound notifications.
    If your Django app is ever unreachable for any reason,
    **you will miss inbound mail** that arrives during that time.

.. _How to set up an inbound route:
   https://www.mailersend.com/help/inbound-route
.. _Where to find inbound emails:
   https://www.mailersend.com/help/inbound-route#where
