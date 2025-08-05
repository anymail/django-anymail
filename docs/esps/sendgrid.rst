.. _sendgrid-backend:

SendGrid
========

Anymail integrates with the Twilio `SendGrid`_ email service, using their `Web API`_.

.. warning:: **Unsupported since June 2025**

    Anymail's SendGrid integration hasn't been tested against the live SendGrid API
    since June 2025. As a result, SendGrid is no longer officially supported in
    django-anymail. See `issue #432`_ for background and recommendations.

    Although it will *probably* keep working, future bugs will likely be discovered
    in production, by users like you, and we won't be able to verify proposed fixes.

    To alert users to the change in support status, django-anymail 13.0.1 and later
    will issue warnings when SendGrid features are used. If you are comfortable using
    code that is no longer fully tested, you can disable these warnings by adding this
    to your settings.py:

    .. code-block:: python

        SILENCED_SYSTEM_CHECKS = ["anymail.W003"]

        import warnings
        warnings.filterwarnings(
            "ignore",
            message="django-anymail has dropped official support for SendGrid",
        )


.. note::

    **Troubleshooting:**
    If your SendGrid messages aren't being delivered as expected, be sure to look for
    "drop" events in your SendGrid `activity feed`_.

    SendGrid detects certain types of errors only *after* the send API call appears
    to succeed, and reports these errors as drop events.

.. _SendGrid: https://sendgrid.com/
.. _Web API: https://www.twilio.com/docs/sendgrid/api-reference
.. _issue #432: https://github.com/anymail/django-anymail/issues/432
.. _activity feed: https://app.sendgrid.com/email_activity?events=drops


.. _sendgrid-installation:

Installation
------------

Anymail optionally uses the :pypi:`cryptography` package to validate SendGrid webhook
signatures. If you will use Anymail's :ref:`status tracking <event-tracking>` webhook
with SendGrid signature verification, be sure to include the ``[sendgrid]`` option
when you install Anymail:

    .. code-block:: console

        $ python -m pip install 'django-anymail[sendgrid]'

(Or separately run ``python -m pip install cryptography``.)

If you don't plan to use SendGrid signature verification, cryptography
is not required. To avoid installing it, omit the ``[sendgrid]`` option.
See :ref:`sendgrid-webhooks` below for details.

.. versionchanged:: vNext

    Added cryptography to the ``[sendgrid]`` extras.


Settings
--------


.. rubric:: EMAIL_BACKEND

To use Anymail's SendGrid backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_SENDGRID_API_KEY

.. rubric:: SENDGRID_API_KEY

A SendGrid API key with "Mail Send" permission.
(Manage API keys in your `SendGrid API key settings`_.)
Required.

  .. code-block:: python

      ANYMAIL = {
          ...
          "SENDGRID_API_KEY": "<your API key>",
      }

Anymail will also look for ``SENDGRID_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["SENDGRID_API_KEY"]``
nor ``ANYMAIL_SENDGRID_API_KEY`` is set.

.. _SendGrid API key settings: https://app.sendgrid.com/settings/api_keys


.. setting:: ANYMAIL_SENDGRID_TRACKING_WEBHOOK_VERIFICATION_KEY

.. rubric:: SENDGRID_TRACKING_WEBHOOK_VERIFICATION_KEY

Optional additional public-key verification when using status tracking
webhooks. See :ref:`sendgrid-webhooks` below.

This should be set to the verification key provided in the Event Webhook page
of SendGrid Mail Settings.

  .. code-block:: python

      ANYMAIL = {
          ...
          "SENDGRID_TRACKING_WEBHOOK_VERIFICATION_KEY": "A8f746...9fuVqQ==",
      }

(Note this works only with SendGrid's cryptographic signature verification,
*not* their OAuth 2.0 option.)


.. setting:: ANYMAIL_SENDGRID_GENERATE_MESSAGE_ID

.. rubric:: SENDGRID_GENERATE_MESSAGE_ID

Whether Anymail should generate a UUID for each message sent through SendGrid,
to facilitate status tracking. The UUID is attached to the message as a
SendGrid custom arg named "anymail_id" and made available as
:attr:`anymail_status.message_id <anymail.message.AnymailMessage.anymail_status>`
on the sent message.

Default ``True``. You can set to ``False`` to disable this behavior, in which
case sent messages will have a `message_id` of ``None``.
See :ref:`Message-ID quirks <sendgrid-message-id>` below.


.. setting:: ANYMAIL_SENDGRID_MERGE_FIELD_FORMAT

.. rubric:: SENDGRID_MERGE_FIELD_FORMAT

If you use :ref:`merge data <merge-data>` with SendGrid's legacy transactional templates,
set this to a :meth:`str.format` formatting string that indicates how merge fields are
delimited in your legacy templates. For example, if your templates use the ``-field-``
hyphen delimiters suggested in some SendGrid docs, you would set:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SENDGRID_MERGE_FIELD_FORMAT": "-{}-",
      }

The placeholder `{}` will become the merge field name. If you need to include
a literal brace character, double it up. (For example, Handlebars-style
``{{field}}`` delimiters would take the format string `"{{{{{}}}}}"`.)

The default `None` requires you include the delimiters directly in your
:attr:`~anymail.message.AnymailMessage.merge_data` keys.
You can also override this setting for individual messages.
See the notes on SendGrid :ref:`templates and merge <sendgrid-legacy-templates>`
below.

This setting is not used (or necessary) with SendGrid's newer dynamic transactional
templates, which always use Handlebars syntax.


.. setting:: ANYMAIL_SENDGRID_API_URL

.. rubric:: SENDGRID_API_URL

The base url for calling the SendGrid API.

The default is ``SENDGRID_API_URL = "https://api.sendgrid.com/v3/"``
(It's unlikely you would need to change this.)


.. _sendgrid-esp-extra:

esp_extra support
-----------------

To use SendGrid features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` of parameters for SendGrid's `v3 Mail Send API`_.
Your :attr:`esp_extra` dict will be deeply merged into the
parameters Anymail has constructed for the send, with `esp_extra`
having precedence in conflicts.

Anymail has special handling for `esp_extra["personalizations"]`. If that value
is a `dict`, Anymail will merge that personalizations dict into the personalizations
for each message recipient. (If you pass a `list`, that will override the
personalizations Anymail normally constructs from the message, and you will need to
specify each recipient in the personalizations list yourself.)

Example:

    .. code-block:: python

        message.open_tracking = True
        message.esp_extra = {
            "asm": {  # SendGrid subscription management
                "group_id": 1,
                "groups_to_display": [1, 2, 3],
            },
            "tracking_settings": {
                "open_tracking": {
                    # Anymail will automatically set `"enable": True` here,
                    # based on message.open_tracking.
                    "substitution_tag": "%%OPEN_TRACKING_PIXEL%%",
                },
            },
            # Because "personalizations" is a dict, Anymail will merge "future_feature"
            # into the SendGrid personalizations array for each message recipient
            "personalizations": {
                "future_feature": {"future": "data"},
            },
        }


(You can also set `"esp_extra"` in Anymail's
:ref:`global send defaults <send-defaults>` to apply it to all
messages.)


.. _v3 Mail Send API:
    https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send#request-body



Limitations and quirks
----------------------

.. _sendgrid-message-id:

**Message-ID**
  SendGrid does not return any sort of unique id from its send API call.
  Knowing a sent message's ID can be important for later queries about
  the message's status.

  To work around this, Anymail generates a UUID for each outgoing message,
  provides it to SendGrid as a custom arg named "anymail_id" and makes it
  available as the message's
  :attr:`anymail_status.message_id <anymail.message.AnymailMessage.anymail_status>`
  attribute after sending. The same UUID will be passed to Anymail's
  :ref:`tracking webhooks <sendgrid-webhooks>` as
  :attr:`event.message_id <anymail.signals.AnymailTrackingEvent.message_id>`.

  To disable attaching tracking UUIDs to sent messages, set
  :setting:`SENDGRID_GENERATE_MESSAGE_ID <ANYMAIL_SENDGRID_GENERATE_MESSAGE_ID>`
  to False in your Anymail settings.

  .. versionchanged:: 6.0

      In batch sends, Anymail generates a distinct anymail_id for *each* "to"
      recipient. (Previously, a single id was used for all batch recipients.) Check
      :attr:`anymail_status.recipients[to_email].message_id <anymail.message.AnymailStatus.recipients>`
      for individual batch-send tracking ids.

  .. versionchanged:: 3.0

      Previously, Anymail generated a custom :mailheader:`Message-ID`
      header for each sent message. But SendGrid's "smtp-id" event field does
      not reliably reflect this header, which complicates status tracking.
      (For compatibility with messages sent in earlier versions, Anymail's
      webhook :attr:`message_id` will fall back to "smtp-id" when "anymail_id"
      isn't present.)

**Invalid Addresses**
  SendGrid will accept *and send* just about anything as
  a message's :attr:`from_email`. (And email protocols are
  actually OK with that.)

  (Tested March, 2016)

**Wrong character set on text attachments**
  Under some conditions, SendGrid incorrectly identifies text attachments (text/plain,
  text/calendar, etc.) as using ISO-8859-1 encoding, and forces ``charset="iso-8859-1"``
  into the attachments' MIME headers. This generally causes any non-ASCII characters in
  the attachments to be replaced with incorrect or illegal characters in the recipient's
  email client.

  The behavior is unpredictable, and may vary by SendGrid account or change over time.
  There is no reliable, general workaround that Anymail could implement. You may be able
  to counteract the issue by enabling open and/or click tracking in your SendGrid
  account. The only way to completely avoid the problem is switching to a non-text
  attachment type (e.g., application/pdf) or limiting your text attachments to use only
  ASCII characters. See `issue 150 <https://github.com/anymail/django-anymail/issues/150>`_
  for more information and other possible workarounds.

  If this impacts your usage, it's helpful to report it to SendGrid support, so they can
  quantify customers affected and prioritize a fix.

  (Noted June, 2019 and December, 2019)

**Arbitrary alternative parts allowed**
  SendGrid is one of the few ESPs that *does* support sending arbitrary alternative
  message parts (beyond just a single text/plain and text/html part).

**AMP for Email**
  SendGrid supports sending AMPHTML email content. To include it, use
  ``message.attach_alternative("...AMPHTML content...", "text/x-amp-html")``
  (and be sure to also include regular HTML and text bodies, too).

**No envelope sender overrides**
  SendGrid does not support overriding :attr:`~anymail.message.AnymailMessage.envelope_sender`
  on individual messages.


.. _sendgrid-templates:

Batch sending/merge and ESP templates
-------------------------------------

SendGrid offers both :ref:`ESP stored templates <esp-stored-templates>`
and :ref:`batch sending <batch-send>` with per-recipient merge data.

SendGrid has two types of stored templates for transactional email:

* Dynamic transactional templates, which were introduced in July, 2018,
  use Handlebars template syntax and allow complex logic to be coded in
  the template itself.

* Legacy transactional templates, which allow only simple key-value substitution
  and don't specify a particular template syntax.

[Legacy templates were originally just called "transactional templates," and many older
references still use this terminology. But confusingly, SendGrid's dashboard and some
recent articles now use "transactional templates" to mean the newer, dynamic templates.]

.. versionchanged:: 4.1

    Added support for SendGrid dynamic transactional templates. (Earlier Anymail
    releases work only with SendGrid's legacy transactional templates.)

You can use either type of SendGrid stored template by setting a message's
:attr:`~anymail.message.AnymailMessage.template_id` to the template's unique id
(*not* its name). Supply the merge data values with Anymail's normalized
:attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_global_data` message attributes.

  .. code-block:: python

      message = EmailMessage(
          ...
          # omit subject and body (or set to None) to use template content
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = "d-5a963add2ec84305813ff860db277d7a"  # SendGrid dynamic id
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
      }

When you supply per-recipient :attr:`~anymail.message.AnymailMessage.merge_data`,
Anymail automatically changes how it communicates the "to" list to SendGrid, so that
each recipient sees only their own email address. (Anymail creates a separate
"personalization" for each recipient in the "to" list; any cc's or bcc's will be
duplicated for *every* to-recipient.)

See the `SendGrid's transactional template overview`_ for more information.

.. _SendGrid's transactional template overview:
    https://www.twilio.com/docs/sendgrid/ui/sending-email/how-to-send-an-email-with-dynamic-templates


.. _sendgrid-legacy-templates:

Legacy transactional templates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With *legacy* transactional templates (only), SendGrid doesn't have a pre-defined merge
field syntax, so you must tell Anymail how substitution fields are delimited in your
templates. There are three ways you can do this:

  * Set `'merge_field_format'` in the message's
    :attr:`~anymail.message.AnymailMessage.esp_extra` to a python :meth:`str.format`
    string, as shown in the example below. (This applies only to that particular
    EmailMessage.)
  * *Or* set :setting:`SENDGRID_MERGE_FIELD_FORMAT <ANYMAIL_SENDGRID_MERGE_FIELD_FORMAT>`
    in your Anymail settings. This is usually the best approach, and will apply to all
    legacy template messages sent through SendGrid. (You can still use esp_extra to
    override for individual messages.)
  * *Or* include the field delimiters directly in *all* your
    :attr:`~anymail.message.AnymailMessage.merge_data` and
    :attr:`~anymail.message.AnymailMessage.merge_global_data` keys.
    E.g.: ``{'-name-': "Alice", '-order_no-': "12345"}``.
    (This can be error-prone, and makes it difficult to transition to other ESPs or to
    SendGrid's dynamic templates.)

  .. code-block:: python

      # ...
      message.template_id = "5997fcf6-2b9f-484d-acd5-7e9a99f0dc1f"  # SendGrid legacy id
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.esp_extra = {
          # Tell Anymail this SendGrid legacy template uses "-field-" for merge fields.
          # (You could instead set SENDGRID_MERGE_FIELD_FORMAT in your ANYMAIL settings.)
          'merge_field_format': "-{}-"
      }

SendGrid legacy templates allow you to mix your EmailMessage's `subject` and `body`
with the template subject and body (by using `<%subject%>` and `<%body%>` in
your SendGrid template definition where you want the message-specific versions
to appear). If you don't want to supply any additional subject or body content
from your Django app, set those EmailMessage attributes to empty strings or `None`.


On-the-fly templates
~~~~~~~~~~~~~~~~~~~~

Rather than define a stored ESP template, you can refer to merge fields directly
in an EmailMessage's subject and body, and SendGrid will treat this as an on-the-fly,
legacy-style template definition. (The on-the-fly template can't contain any dynamic
template logic, and like any legacy template you must specify the merge field format
in either Anymail settings or esp_extra as described above.)

  .. code-block:: python

      # on-the-fly template using merge fields in subject and body:
      message = EmailMessage(
          subject="Your order {{order_no}} has shipped",
          body="Dear {{name}}:\nWe've shipped order {{order_no}}.",
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      # note: no template_id specified
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.esp_extra = {
          # here's how to get Handlebars-style {{merge}} fields with Python's str.format:
          'merge_field_format': "{{{{{}}}}}"  # "{{ {{ {} }} }}" without the spaces
      }


.. _sendgrid-webhooks:

Status tracking webhooks
------------------------

Anymail's normalized :ref:`status tracking <event-tracking>` works
with SendGrid's webhooks.

SendGrid optionally provides webhook signature verification. You have three
choices for securing the status tracking webhook:

* Use SendGrid's signature verification: follow their
  `Event Webhook Security Features`_ documentation and set
  :setting:`SENDGRID_TRACKING_WEBHOOK_VERIFICATION_KEY <ANYMAIL_SENDGRID_TRACKING_WEBHOOK_VERIFICATION_KEY>`
  (requires the :pypi:`cryptography` package---see :ref:`sendgrid-installation`)
* Use Anymail's shared secret validation, by setting
  :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`
  (does not require cryptography)
* Use both

Signature verification is recommended, unless you do not want to add
cryptography to your dependencies.

.. versionchanged:: vNext

    Added support for SendGrid webhook signature verification.
    (Earlier releases supported only shared secret validation.)

.. _Event Webhook Security Features:
    https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/getting-started-event-webhook-security-features#the-signed-event-webhook


To configure Anymail status tracking for SendGrid, enter one of these urls
in your `SendGrid mail settings`_ under "Event Notification" (substituting
your Django site for *yoursite.example.com*):

*   If you are *not* using Anymail's shared webhook secret:

        :samp:`https://{yoursite.example.com}/anymail/sendgrid/tracking/`

*   Or if you *are* using Anymail's :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`,
    include the *random:random* shared secret in the URL:

        :samp:`https://{random}:{random}@{yoursite.example.com}/sendgrid/tracking/`

Be sure to check the boxes in the SendGrid settings for the event types you want to receive.

SendGrid will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
queued, rejected, bounced, deferred, delivered, opened, clicked, complained, unsubscribed,
subscribed.

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of `SendGrid event`_ fields, for a single event. (Although SendGrid calls
webhooks with batches of events, Anymail will invoke your signal receiver separately
for each event in the batch.)

.. _SendGrid mail settings: https://app.sendgrid.com/settings/mail_settings
.. _SendGrid event: https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event#delivery-events


.. _sendgrid-inbound:

Inbound webhook
---------------

If you want to receive email from SendGrid through Anymail's normalized :ref:`inbound <inbound>`
handling, follow SendGrid's `Inbound Parse Webhook`_ guide to set up
Anymail's inbound webhook.

The Destination URL setting will be:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/sendgrid/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

(Anymail does not currently support signature verification for the inbound parse webhook.)

You should enable SendGrid's "POST the raw, full MIME message" checkbox (see note below).
And be sure the URL has a trailing slash. (SendGrid's inbound processing won't follow Django's
:setting:`APPEND_SLASH` redirect.)

If you want to use Anymail's normalized :attr:`~anymail.inbound.AnymailInboundMessage.spam_detected` and
:attr:`~anymail.inbound.AnymailInboundMessage.spam_score` attributes, be sure to enable the "Check
incoming emails for spam" checkbox.

.. note::

    Anymail supports either option for SendGrid's "POST the raw, full MIME message" checkbox, but
    enabling this setting is preferred to get the most accurate representation of any received email.
    Using raw MIME also avoids a limitation in Django's :mimetype:`multipart/form-data` handling
    that can strip attachments with certain filenames.

    .. versionchanged:: 8.6
       Leaving SendGrid's "full MIME" checkbox disabled is no longer recommended.


.. _Inbound Parse Webhook:
   https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook
