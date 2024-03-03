.. _unisender-go-backend:

Unisender Go
=============

Anymail supports sending email from Django through the `Unisender Go`_ email service,
using their `Web API`_ v1.

.. _Unisender Go: https://go.unisender.ru
.. _Web API: https://godocs.unisender.ru/web-api-ref

Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Unisender Go backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.unisender_go.EmailBackend"

in your settings.py.

.. rubric:: UNISENDER_GO_API_KEY, UNISENDER_GO_API_URL

.. setting:: ANYMAIL_UNISENDER_GO_API_KEY
.. setting:: ANYMAIL_UNISENDER_GO_API_URL

Required---the API key and API endpoint for your Unisender Go account or project:

  .. code-block:: python

      ANYMAIL = {
          "UNISENDER_GO_API_KEY": "<your API key>",
          # Pick ONE of these, depending on your account (go1 vs. go2):
          "UNISENDER_GO_API_URL": "https://go1.unisender.ru/ru/transactional/api/v1/",
          "UNISENDER_GO_API_URL": "https://go2.unisender.ru/ru/transactional/api/v1/",
      }

Get the API key from Unisender Go's dashboard under Account > Security > API key
(Учетная запись > Безопасность > API-ключ). Or for a project-level API key, under
Settings > Projects (Настройки > Проекты).

The correct API URL depends on which Unisender Go data center registered your account.
You must specify the full, versioned `Unisender Go API endpoint`_ as shown above
(not just the base uri).

If trying to send mail raises an API Error "User with id ... not found" (code 114),
the likely cause is using the wrong API URL for your account. (To find which server
handles your account, log into Unisender Go's dashboard and then check hostname
in your browser's URL.)

Anymail will also look for ``UNISENDER_GO_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["UNISENDER_GO_API_KEY"]``
nor ``ANYMAIL_UNISENDER_GO_API_KEY`` is set.

.. _Unisender Go API endpoint: https://godocs.unisender.ru/web-api-ref#web-api


.. setting:: ANYMAIL_UNISENDER_GO_GENERATE_MESSAGE_ID

.. rubric:: UNISENDER_GO_GENERATE_MESSAGE_ID

Whether Anymail should generate a separate UUID for each recipient when sending
messages through Unisender Go, to facilitate status tracking. The UUIDs are attached
to the message as recipient metadata named "anymail_id" and available in
:attr:`anymail_status.recipients[recipient_email].message_id <anymail.message.AnymailStatus.recipients>`
on the message after it is sent.

Default ``True``. You can set to ``False`` to disable generating UUIDs:

  .. code-block:: python

      ANYMAIL = {
          ...
          "UNISENDER_GO_GENERATE_MESSAGE_ID": False
      }

When disabled, each sent message will use Unisender Go's "job_id" as the (single)
:attr:`~anymail.message.AnymailStatus.message_id` for all recipients.
(The job_id alone may be sufficient for your tracking needs, particularly
if you only send to one recipient per message.)


.. _unisender-go-esp-extra:

Additional sending options and esp_extra
----------------------------------------

Unisender Go offers a number of additional options you may want to use
when sending a message. You can set these for individual messages using
Anymail's :attr:`~anymail.message.AnymailMessage.esp_extra`. See the full
list of options in Unisender Go's `email/send.json`_ API documentation.

For example:

.. code-block:: python

    message = EmailMessage(...)
    message.esp_extra = {
        "global_language": "en",  # Use English text for unsubscribe link
        "bypass_global": 1,  # Ignore system level blocked address list
        "bypass_unavailable": 1,  # Ignore account level blocked address list
        "options": {
            # Custom unsubscribe link (can use merge_data {{substitutions}}):
            "unsubscribe_url": "https://example.com/unsub?u={{subscription_id}}",
            "custom_backend_id": 22,  # ID of dedicated IP address
        }
    }

(Note that you do *not* include the API's root level ``"message"`` key in
:attr:`~!anymail.message.AnymailMessage.esp_extra`, but you must include
any nested keys---like ``"options"`` in the example above---to match
Unisender Go's API structure.)

To set default :attr:`esp_extra` options for all messages, use Anymail's
:ref:`global send defaults <send-defaults>` in your settings.py. Example:

.. code-block:: python

    ANYMAIL = {
        ...,
        "UNISENDER_GO_SEND_DEFAULTS": {
            "esp_extra": {
                # Omit the unsubscribe link for all sent messages:
                "skip_unsubscribe": 1
            }
        }
    }

Any options set in an individual message's
:attr:`~anymail.message.AnymailMessage.esp_extra` take precedence
over the global send defaults.

For many of these additional options, you will need to contact Unisender Go
tech support for approval before being able to use them.

.. _email/send.json: https://godocs.unisender.ru/web-api-ref#email-send


.. _unisender-go-quirks:

Limitations and quirks
----------------------

**Attachment filename restrictions**
  Unisender Go does not permit the slash character (``/``) in attachment filenames.
  Trying to send one will result in an :exc:`~anymail.exceptions.AnymailAPIError`.

**Restrictions on to, cc and bcc**
  For non-batch sends, Unisender Go has a limit of 10 recipients each
  for :attr:`to`, :attr:`cc` and :attr:`bcc`. Unisender Go does not support
  cc-only or bcc-only messages. All bcc recipients must be in a domain
  you have verified with Unisender Go.

  For :ref:`batch sending <batch-send>` (with Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_data` or
  :attr:`~anymail.message.AnymailMessage.merge_metadata`), Unisender Go has
  a limit of 500 :attr:`to` recipients in a single message.

  Unisender Go's API does not support :attr:`cc` with batch sending.
  Trying to include cc recipients in a batch send will raise an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error.
  (If you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will handle :attr:`cc` in a Unisender Go batch send as
  additional :attr:`to` recipients.)

  With batch sending, Unisender Go effectively treats :attr:`bcc` recipients
  as additional :attr:`to` recipients, which may not behave as you'd expect.
  Each bcc in a batch send will be sent a *single* copy of the message,
  with the bcc's email in the :mailheader:`To` header, and personalized using
  :attr:`merge_data` for their own email address, if any. (Unlike some other
  ESPs, bcc recipients in a batch send *won't* receive a separate copy of the
  message personalized for each :attr:`to` email.)

**AMP for Email**
  Unisender Go supports sending AMPHTML email content. To include it, use
  ``message.attach_alternative("...AMPHTML content...", "text/x-amp-html")``
  (and be sure to also include regular HTML and text bodies, too).

**Use metadata for campaign_id**
  If you want to use Unisender Go's ``campaign_id``, set it in Anymail's
  :attr:`~anymail.message.AnymailMessage.metadata`.

**Duplicate emails ignored**
  Unisender Go only allows an email address to be included once in a message's
  combined :attr:`to`, :attr:`cc` and :attr:`bcc` lists. If the same email
  appears multiple times, the additional instances are ignored. (Unisender Go
  reports them as duplicates, but Anymail does not treat this as an error.)

  Note that email addresses are case-insensitive.

**Anymail's message_id is passed in recipient metadata**
  By default, Anymail generates a unique identifier for each
  :attr:`to` recipient in a message, and (effectively) adds this to the
  recipients' :attr:`~anymail.message.AnymailMessage.merge_metadata`
  with the key ``"anymail_id"``.

  This feature consumes one of Unisender Go's 10 available metadata slots.
  To disable it, see the
  :setting:`UNISENDER_GO_GENERATE_MESSAGE_ID <ANYMAIL_UNISENDER_GO_GENERATE_MESSAGE_ID>`
  setting.

**Recipient display names are set in merge_data**
  To include a display name ("friendly name") with a :attr:`to` email address,
  Unisender Go's Web API uses an entry in their per-recipient template
  "substitutions," which are also used for Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_data`.

  To avoid conflicts, do not use ``"to_name"`` as a key in
  :attr:`~anymail.message.AnymailMessage.merge_data` or
  :attr:`~anymail.message.AnymailMessage.merge_global_data`.

**No envelope sender overrides**
  Unisender Go does not support overriding a message's
  :attr:`~anymail.message.AnymailMessage.envelope_sender`.


.. _unisender-go-templates:

Batch sending/merge and ESP templates
-------------------------------------

Unisender Go supports :ref:`ESP stored templates <esp-stored-templates>`,
on-the-fly templating, and :ref:`batch sending <batch-send>` with
per-recipient merge data substitutions.

To send using a template you have created in your Unisender Go account,
set the message's :attr:`~anymail.message.AnymailMessage.template_id`
to the template's ID. (This is a UUID found at the top of the template's
"Properties" page---*not* the template name.)

To supply template substitution data, use Anymail's
normalized :attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_global_data` message attributes.
You can also use
:attr:`~anymail.message.AnymailMessage.merge_metadata` to supply custom tracking
data for each recipient.

Here is an example using a template that has slots for ``{{name}}``,
``{{order_no}}``, and ``{{ship_date}}`` substitution data:

  .. code-block:: python

      message = EmailMessage(
          to=["alice@example.com", "Bob <bob@example.com>"],
      )
      message.from_email = None  # Use template From email and name
      message.template_id = "0000aaaa-1111-2222-3333-4444bbbbcccc"
      message.merge_data = {
          "alice@example.com": {"name": "Alice", "order_no": "12345"},
          "bob@example.com": {"name": "Bob", "order_no": "54321"},
      }
      message.merge_global_data = {
          "ship_date": "15-May",
      }
      message.send()

Any :attr:`subject` provided will override the one defined in the template.
The message's :class:`from_email <django.core.mail.EmailMessage>` (which defaults to
your :setting:`DEFAULT_FROM_EMAIL` setting) will override the template's default sender.
If you want to use the :mailheader:`From` email and name defined with the template,
be sure to set :attr:`from_email` to ``None`` *after* creating the message, as shown above.

Unisender Go also supports inline, on-the-fly templates. Here is the same example
using inline templates:

  .. code-block:: python

      message = EmailMessage(
          from_email="shipping@example.com",
          to=["alice@example.com", "Bob <bob@example.com>"],
          # Use {{substitution}} variables in subject and body:
          subject="Your order {{order_no}} has shipped",
          body="""Hi {{name}},
                  We shipped your order {{order_no}}
                  on {{ship_date}}.""",
      )
      # (You'd probably also want to add an HTML body here.)
      # The substitution data is exactly the same as in the previous example:
      message.merge_data = {
          "alice@example.com": {"name": "Alice", "order_no": "12345"},
          "bob@example.com": {"name": "Bob", "order_no": "54321"},
      }
      message.merge_global_data = {
          "ship_date": "May 15",
      }
      message.send()

Note that Unisender Go doesn't allow whitespace in the substitution braces:
``{{order_no}}`` works, but ``{{ order_no }}`` causes an error.

There are two available `Unisender Go template engines`_: "simple" and "velocity."
For templates stored in your account, you select the engine in the template's
properties. Inline templates use the simple engine by default; you can select
"velocity" using :ref:`esp_extra <unisender-go-esp-extra>`:

  .. code-block:: python

      message.esp_extra = {
          "template_engine": "velocity",
      }
      message.subject = "Your order $order_no has shipped"  # Velocity syntax

When you set per-recipient :attr:`~anymail.message.AnymailMessage.merge_data`
or :attr:`~anymail.message.AnymailMessage.merge_metadata`, Anymail will use
:ref:`batch sending <batch-send>` mode so that each :attr:`to` recipient sees
only their own email address. You can set either of these attributes to an empty
dict (``message.merge_data = {}``) to force batch sending for a message that
wouldn't otherwise use it.

Be sure to review the :ref:`restrictions above <unisender-go-quirks>`
before trying to use :attr:`cc` or :attr:`bcc` with Unisender Go batch sending.

.. _Unisender Go template engines: https://godocs.unisender.ru/template-engines


.. _unisender-go-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, add
the url in Unisender Go's dashboard. Where to set the webhook depends on where
you got your :setting:`UNISENDER_GO_API_KEY <ANYMAIL_UNISENDER_GO_API_KEY>`:

* If you are using an account-level API key, configure the webhook
  under Settings > Webhooks (Настройки > Вебхуки).
* If you are using a project-level API key, configure the webhook
  under Settings > Projects (Настройки > Проекты).

(If you try to mix account-level and project-level API keys and webhooks,
webhook signature validation will fail, and you'll get
:exc:`~anymail.exceptions.AnymailWebhookValidationFailure` errors.)

Enter these settings for the webhook:

*  **Notification Url:**

       :samp:`https://{yoursite.example.com}/anymail/unisender_go/tracking/`

   where *yoursite.example.com* is your Django site.

*  **Status:** set to "Active" if you have already deployed your Django project
   with Anymail installed. Otherwise set to "Inactive" and update after you deploy.

   (Unisender Go performs a GET request to verify the webhook URL
   when it is marked active.)

*  **Event format:** "json_post"

   (If your gateway handles decompressing incoming request bodies---e.g., Apache
   with a mod_deflate *input* filter---you could also use "json_post_compressed."
   Most web servers do not handle compressed input by default.)

*  **Events:** your choice. Anymail supports any combination of ``sent, delivered,
   soft_bounced, hard_bounced, opened, clicked, unsubscribed, subscribed, spam``.

   Anymail does not support Unisender Go's ``spam_block`` events (but will ignore
   them if you accidentally include it).

*  **Number of simultaneous requests:** depends on your web server's
   capacity

   Most deployments should be able to handle the default 10.
   But you may need to use a smaller number if your tracking signal
   receiver uses a lot of resources (or monopolizes your database),
   or if your web server isn't configured to handle that many
   simultaneous requests (including requests from your site users).

*  **Use single event:** the default "No" is recommended

   Anymail can process multiple events in a single webhook call.
   It invokes your signal receiver separately for each event.
   But all of the events in the call (up to 100 when set to "No")
   must be handled within 3 seconds total, or Unisender Go will
   think the request failed and resend it.

   If your tracking signal receiver takes a long time to process
   each event, you may need to change "Use single event" to "Yes"
   (one event per webhook call).

*  **Additional information about delivery:** "Yes" is recommended

   (If you set this to "No", your tracking events won't include
   :attr:`~anymail.signals.AnymailTrackingEvent.mta_response`,
   :attr:`~anymail.signals.AnymailTrackingEvent.user_agent` or
   :attr:`~anymail.signals.AnymailTrackingEvent.click_url`.)

Note that Unisender Go does not deliver tracking events for recipient
addresses that are blocked at send time. You must check the message's
:attr:`anymail_status.recipients[recipient_email].message_id <anymail.message.AnymailStatus.recipients>`
immediately after sending to detect rejected recipients.

Unisender Go implements webhook signing on the entire event payload,
and Anymail verifies this signature using your
:setting:`UNISENDER_GO_API_KEY <ANYMAIL_UNISENDER_GO_API_KEY>`.
It is not necessary to use an :setting:`ANYMAIL_WEBHOOK_SECRET`
with Unisender Go, but if you have set one, you must include
the *random:random* shared secret in the Notification URL like this:

     :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/unisender_go/tracking/`

In your tracking signal receiver, the event's
:attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
the ``"event_data"`` object from a single, raw `"transactional_email_status" event`_.
For example, you could get the IP address that opened a message using
``event.esp_event["delivery_info"]["ip"]``.

(Anymail does not handle Unisender Go's "transactional_spam_block" events,
and will filter these without calling your tracking signal handler.)

.. _"transactional_email_status" event:
    https://godocs.unisender.ru/web-api-ref#callback-format


.. _unisender-go-inbound:

Inbound webhook
---------------

Unisender Go does not currently offer inbound email.

(If this changes in the future, please open an issue
so we can add support in Anymail.)
