.. _sparkpost-backend:

SparkPost
=========

Anymail integrates with the `SparkPost`_ email service, using their
`Transmissions API`_.

.. versionchanged:: 8.0

    Earlier Anymail versions used the official Python :pypi:`sparkpost` API client.
    That library is no longer maintained, and Anymail now calls SparkPost's HTTP API
    directly. This change should not affect most users, but you should make sure you
    provide :setting:`SPARKPOST_API_KEY <ANYMAIL_SPARKPOST_API_KEY>` in your
    Anymail settings (Anymail doesn't check environment variables), and if you are
    using Anymail's :ref:`esp_extra <sparkpost-esp-extra>` you will need to update that
    to use Transmissions API parameters.

.. _SparkPost: https://www.sparkpost.com/
.. _Transmissions API: https://developers.sparkpost.com/api/transmissions/


Settings
--------


.. rubric:: EMAIL_BACKEND

To use Anymail's SparkPost backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.sparkpost.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_SPARKPOST_API_KEY

.. rubric:: SPARKPOST_API_KEY

A SparkPost API key with at least the "Transmissions: Read/Write" permission.
(Manage API keys in your `SparkPost account API keys`_.)

  .. code-block:: python

      ANYMAIL = {
          ...
          "SPARKPOST_API_KEY": "<your API key>",
      }

Anymail will also look for ``SPARKPOST_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["SPARKPOST_API_KEY"]``
nor ``ANYMAIL_SPARKPOST_API_KEY`` is set.

.. versionchanged:: 8.0

    This setting is required. If you store your API key in an environment variable, load
    it into your Anymail settings: ``"SPARKPOST_API_KEY": os.environ["SPARKPOST_API_KEY"]``.
    (Earlier Anymail releases used the SparkPost Python library, which would look for
    the environment variable.)

.. _SparkPost account API keys: https://app.sparkpost.com/account/credentials


.. setting:: ANYMAIL_SPARKPOST_SUBACCOUNT

.. rubric:: SPARKPOST_SUBACCOUNT

.. versionadded:: 8.0

An optional `SparkPost subaccount`_ numeric id. This can be used, along with the API key
for the master account, to send mail on behalf of a subaccount. (Do not set this when
using a subaccount's own API key.)

Like all Anymail settings, you can include this in the global settings.py ANYMAIL dict
to apply to all sends, or supply it as a :func:`~django.core.mail.get_connection`
keyword parameter (``connection = get_connection(subaccount=123)``) to send a particular
message with a subaccount. See :ref:`multiple-backends` for more information on using
connections.

.. _SparkPost subaccount: https://www.sparkpost.com/docs/user-guide/subaccounts/


.. setting:: ANYMAIL_SPARKPOST_API_URL

.. rubric:: SPARKPOST_API_URL

The `SparkPost API Endpoint`_ to use. The default is ``"https://api.sparkpost.com/api/v1"``.

Set this to use a SparkPost EU account, or to work with any other API endpoint including
SparkPost Enterprise API and SparkPost Labs.

  .. code-block:: python

      ANYMAIL = {
          ...
          "SPARKPOST_API_URL": "https://api.eu.sparkpost.com/api/v1",  # use SparkPost EU
      }

You must specify the full, versioned API endpoint as shown above (not just the base_uri).

.. _SparkPost API Endpoint: https://developers.sparkpost.com/api/index.html#header-api-endpoints


.. setting:: ANYMAIL_SPARKPOST_TRACK_INITIAL_OPEN_AS_OPENED

.. rubric:: SPARKPOST_TRACK_INITIAL_OPEN_AS_OPENED

.. versionadded:: 8.1

Boolean, default ``False``. When using Anymail's tracking webhooks, whether to report
SparkPost's "Initial Open" event as an Anymail normalized "opened" event.
(SparkPost's "Open" event is always normalized to Anymail's "opened" event.
See :ref:`sparkpost-webhooks` below.)

.. _sparkpost-esp-extra:

esp_extra support
-----------------

To use SparkPost features not directly supported by Anymail, you can set
a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to a `dict`
of `transmissions API request body`_ data. Anymail will deeply merge your overrides
into the normal API payload it has constructed, with esp_extra taking precedence
in conflicts.

Example (you probably wouldn't combine all of these options at once):

    .. code-block:: python

        message.esp_extra = {
            "options": {
                # Treat as transactional for unsubscribe and suppression:
                "transactional": True,
                # Override your default dedicated IP pool:
                "ip_pool": "transactional_pool",
            },
            # Add a description:
            "description": "Test-run for new templates",
            "content": {
                # Use draft rather than published template:
                "use_draft_template": True,
                # Use an A/B test:
                "ab_test_id": "highlight_support_links",
            },
            # Use a stored recipients list (overrides message to/cc/bcc):
            "recipients": {
                "list_id": "design_team"
            },
        }

Note that including ``"recipients"`` in esp_extra will *completely* override the
recipients list Anymail generates from your message's to/cc/bcc fields, along with any
per-recipient :attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_metadata`.

(You can also set `"esp_extra"` in Anymail's :ref:`global send defaults <send-defaults>`
to apply it to all messages.)

.. _transmissions API request body:
    https://developers.sparkpost.com/api/transmissions/#header-request-body



Limitations and quirks
----------------------

.. _sparkpost-message-id:

**Anymail's `message_id` is SparkPost's `transmission_id`**
  The :attr:`~anymail.message.AnymailStatus.message_id` Anymail sets
  on a message's :attr:`~anymail.message.AnymailMessage.anymail_status`
  and in normalized webhook :class:`~anymail.signals.AnymailTrackingEvent`
  data is actually what SparkPost calls "transmission_id".

  Like Anymail's message_id for other ESPs, SparkPost's transmission_id
  (together with the recipient email address), uniquely identifies a
  particular message instance in tracking events.

  (The transmission_id is the only unique identifier available when you
  send your message. SparkPost also has something called "message_id", but
  that doesn't get assigned until after the send API call has completed.)

  If you are working exclusively with Anymail's normalized message status
  and webhook events, the distinction won't matter: you can consistently
  use Anymail's `message_id`. But if you are also working with raw webhook
  esp_event data or SparkPost's events API, be sure to think "transmission_id"
  wherever you're speaking to SparkPost.

**Single tag**
  Anymail uses SparkPost's "campaign_id" to implement message tagging.
  SparkPost only allows a single campaign_id per message. If your message has
  two or more :attr:`~anymail.message.AnymailMessage.tags`, you'll get an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error---or
  if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first tag.

  (SparkPost's "recipient tags" are not available for tagging *messages*.
  They're associated with individual *addresses* in stored recipient lists.)

**AMP for Email**
  SparkPost supports sending AMPHTML email content. To include it, use
  ``message.attach_alternative("...AMPHTML content...", "text/x-amp-html")``
  (and be sure to also include regular HTML and/or text bodies, too).

  .. versionadded:: 8.0

**Envelope sender may use domain only**
  Anymail's :attr:`~anymail.message.AnymailMessage.envelope_sender` is used to
  populate SparkPost's `'return_path'` parameter. Anymail supplies the full
  email address, but depending on your SparkPost configuration, SparkPost may
  use only the domain portion and substitute its own encoded mailbox before
  the @.

**Multiple from_email addresses**
  Prior to November, 2020, SparkPost supporting sending messages with multiple
  *From* addresses. (This is technically allowed by email specs, but many
  ISPs bounce such messages.) Anymail v8.1 and earlier will pass multiple
  ``from_email`` addresses to SparkPost's API.

  SparkPost has since dropped support for more than one from address, and now issues
  error code 7001 "No sending domain specified". To avoid confusion, Anymail v8.2
  treats multiple from addresses as an unsupported feature in the SparkPost backend.

  .. versionchanged:: 8.2


.. _sparkpost-templates:

Batch sending/merge and ESP templates
-------------------------------------

SparkPost offers both :ref:`ESP stored templates <esp-stored-templates>`
and :ref:`batch sending <batch-send>` with per-recipient merge data.

You can use a SparkPost stored template by setting a message's
:attr:`~anymail.message.AnymailMessage.template_id` to the
template's unique id. (When using a stored template, SparkPost prohibits
setting the EmailMessage's subject, text body, or html body.)

Alternatively, you can refer to merge fields directly in an EmailMessage's
subject, body, and other fields---the message itself is used as an
on-the-fly template.

In either case, supply the merge data values with Anymail's
normalized :attr:`~anymail.message.AnymailMessage.merge_data`
and :attr:`~anymail.message.AnymailMessage.merge_global_data`
message attributes.

  .. code-block:: python

      message = EmailMessage(
          ...
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = "11806290401558530"  # SparkPost id
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
          # Can use SparkPost's special "dynamic" keys for nested substitutions (see notes):
          'dynamic_html': {
              'status_html': "<a href='https://example.com/order/{{order_no}}'>Status</a>",
          },
          'dynamic_plain': {
              'status_plain': "Status: https://example.com/order/{{order_no}}",
          },
      }


See `SparkPost's substitutions reference`_ for more information on templates and
batch send with SparkPost. If you need the special `"dynamic" keys for nested substitutions`_,
provide them in Anymail's :attr:`~anymail.message.AnymailMessage.merge_global_data`
as shown in the example above. And if you want `use_draft_template` behavior, specify that
in :ref:`esp_extra <sparkpost-esp-extra>`.


.. _SparkPost's substitutions reference:
    https://developers.sparkpost.com/api/substitutions-reference

.. _"dynamic" keys for nested substitutions:
    https://developers.sparkpost.com/api/substitutions-reference#header-links-and-substitution-expressions-within-substitution-values


.. _sparkpost-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, set up the
webhook in your `SparkPost configuration under "Webhooks"`_:

* Target URL: :samp:`https://{yoursite.example.com}/anymail/sparkpost/tracking/`
* Authentication: choose "Basic Auth." For username and password enter the two halves of the
  *random:random* shared secret you created for your :setting:`ANYMAIL_WEBHOOK_SECRET`
  Django setting. (Anymail doesn't support OAuth webhook auth.)
* Events: you can leave "All events" selected, or choose "Select individual events"
  to pick the specific events you're interested in tracking.

SparkPost will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
queued, rejected, bounced, deferred, delivered, opened, clicked, complained, unsubscribed,
subscribed.

By default, Anymail reports SparkPost's "Open"---but *not* its "Initial Open"---event
as Anymail's normalized "opened" :attr:`~anymail.signals.AnymailTrackingEvent.event_type`.
This avoids duplicate "opened" events when both SparkPost types are enabled.

.. versionadded:: 8.1

    To receive SparkPost "Initial Open" events as Anymail's "opened", set
    :setting:`"SPARKPOST_TRACK_INITIAL_OPEN_AS_OPENED": True <ANYMAIL_SPARKPOST_TRACK_INITIAL_OPEN_AS_OPENED>`
    in your ANYMAIL settings dict. You will probably want to disable SparkPost "Open"
    events when using this setting.

.. versionchanged:: 8.1

    SparkPost's "AMP Click" and "AMP Open" are reported as Anymail's "clicked" and
    "opened" events. If you enable the SPARKPOST_TRACK_INITIAL_OPEN_AS_OPENED setting,
    "AMP Initial Open" will also map to "opened." (Earlier Anymail releases reported
    all AMP events as "unknown".)


The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a single, raw `SparkPost event`_. (Although SparkPost calls webhooks with batches of events,
Anymail will invoke your signal receiver separately for each event in the batch.)
The esp_event is the raw, wrapped json event structure as provided by SparkPost:
`{'msys': {'<event_category>': {...<actual event data>...}}}`.


.. _SparkPost configuration under "Webhooks":
    https://app.sparkpost.com/webhooks
.. _SparkPost event:
    https://developers.sparkpost.com/api/webhooks/#header-webhook-event-types


.. _sparkpost-inbound:

Inbound webhook
---------------

If you want to receive email from SparkPost through Anymail's normalized :ref:`inbound <inbound>`
handling, follow SparkPost's `Enabling Inbound Email Relaying`_ guide to set up
Anymail's inbound webhook.

The target parameter for the Relay Webhook will be:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/sparkpost/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

.. _Enabling Inbound Email Relaying:
   https://www.sparkpost.com/docs/tech-resources/inbound-email-relay-webhook/
