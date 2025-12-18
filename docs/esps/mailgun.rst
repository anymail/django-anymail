.. _mailgun-backend:

Mailgun
=======

Anymail integrates with the Sinch `Mailgun <https://mailgun.com>`_
transactional email service, using their `messages REST API`_.

.. note::

    By default, Anymail connects to Mailgun's US-based API servers.
    If you are using Mailgun's EU region, be sure to change the
    :setting:`MAILGUN_API_URL <ANYMAIL_MAILGUN_API_URL>` Anymail setting
    as shown below.

.. _messages REST API: https://documentation.mailgun.com/en/latest/api-sending.html#sending


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Mailgun backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILGUN_API_KEY

.. rubric:: MAILGUN_API_KEY

Required for sending:

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILGUN_API_KEY": "<your API key>",
      }

The key can be either:

* (recommended) a domain-level Mailgun "Sending API key," found in Mailgun's dashboard
  under "Sending" > "Domain settings" > "Sending API keys" (make sure the correct
  domain is selected in the popup at top right!)
* an account-level "Mailgun API key" from your Mailgun `API security settings`_.

The account-level API key permits sending from any verified domain,
but it also allows access to all other Mailgun APIs for your account
(which Anymail doesn't need).

The domain-level sending API key is preferred if you send from only
a single domain. With multiple domains, either use an account API key,
or supply the sending API key for a default domain in settings.py and
use Django's :func:`~django.core.mail.get_connection` to substitute
a different sending API key for other domains:

    .. code-block:: python

        from django.core.mail import EmailMessage, get_connection
        # By default, use the settings.py MAILGUN_API_KEY:
        message1 = EmailMessage(from_email="support@default-domain.example.com", ...)
        message1.send()

        # Use a different sending API key for this message:
        connection = get_connection(api_key=SENDING_API_KEY_FOR_OTHER_DOMAIN)
        message2 = EmailMessage(from_email="support@other-domain.example.com", ...,
                                connection=connection)
        message2.send()


Anymail will also look for ``MAILGUN_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["MAILGUN_API_KEY"]``
nor ``ANYMAIL_MAILGUN_API_KEY`` is set.


.. setting:: ANYMAIL_MAILGUN_API_URL

.. rubric:: MAILGUN_API_URL

The base url for calling the Mailgun API.

The default is ``MAILGUN_API_URL = "https://api.mailgun.net/v3"``, which connects
to Mailgun's US service. You must change this if you are using Mailgun's European
region:

  .. code-block:: python

      ANYMAIL = {
        "MAILGUN_API_KEY": "...",
        "MAILGUN_API_URL": "https://api.eu.mailgun.net/v3",
        # ...
      }

(Do not include your sender domain or "/messages" in the API URL. Anymail
:ref:`figures this out <mailgun-sender-domain>` for you.)


.. setting:: ANYMAIL_MAILGUN_SENDER_DOMAIN

.. rubric:: MAILGUN_SENDER_DOMAIN

If you are using a specific `Mailgun sender domain`_
that is *different* from your messages' `from_email` domains,
set this to the domain you've configured in your Mailgun account.

If your messages' `from_email` domains always match a configured
Mailgun sender domain, this setting is not needed.

See :ref:`mailgun-sender-domain` below for examples.


.. setting:: ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY

.. rubric:: MAILGUN_WEBHOOK_SIGNING_KEY

.. versionadded:: 6.1

Required for tracking or inbound webhooks. Your "HTTP webhook signing key" from the
Mailgun `API security settings`_:

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILGUN_WEBHOOK_SIGNING_KEY": "<your webhook signing key>",
      }

If not provided, Anymail will attempt to validate webhooks using the
:setting:`MAILGUN_API_KEY <ANYMAIL_MAILGUN_API_KEY>` setting instead. (These two keys have
the same values for new Mailgun users, but will diverge if you ever rotate either key.)


.. _API security settings: https://app.mailgun.com/app/account/security/api_keys


.. _mailgun-sender-domain:

Email sender domain
-------------------

Mailgun's API requires identifying the sender domain.
By default, Anymail uses the domain of each message's `from_email`
(e.g., "example.com" for "from\@example.com").

You will need to override this default if you are using
a dedicated `Mailgun sender domain`_ that is different from
a message's `from_email` domain.

For example, if you are sending from "orders\@example.com", but your
Mailgun account is configured for "*mail1*.example.com", you should provide
:setting:`MAILGUN_SENDER_DOMAIN <ANYMAIL_MAILGUN_SENDER_DOMAIN>` in your settings.py:

    .. code-block:: python
        :emphasize-lines: 4

        ANYMAIL = {
            ...
            "MAILGUN_API_KEY": "<your API key>",
            "MAILGUN_SENDER_DOMAIN": "mail1.example.com"
        }


If you need to override the sender domain for an individual message,
use Anymail's :attr:`~anymail.message.AnymailMessage.envelope_sender`
(only the domain is used; anything before the @ is ignored):

    .. code-block:: python

        message = EmailMessage(from_email="marketing@example.com", ...)
        message.envelope_sender = "anything@mail2.example.com"  # the "anything@" is ignored


.. _Mailgun sender domain:
    https://help.mailgun.com/hc/en-us/articles/202256730-How-do-I-pick-a-domain-name-for-my-Mailgun-account-


.. _mailgun-esp-extra:

exp_extra support
-----------------

Anymail's Mailgun backend will pass all :attr:`~anymail.message.AnymailMessage.esp_extra`
values directly to Mailgun. You can use any of the (non-file) parameters listed in the
`Mailgun sending docs`_. Example:

  .. code-block:: python

      message = AnymailMessage(...)
      message.esp_extra = {
          'o:deliverytime-optimize-period': '24h',  # use Mailgun Send Time Optimization
          'o:time-zone-localize': '16:00',  # use Mailgun Timezone Optimization
          'o:testmode': 'yes',  # use Mailgun's test mode
      }

.. _Mailgun sending docs: https://documentation.mailgun.com/en/latest/api-sending.html#sending


.. _mailgun-quirks:

Limitations and quirks
----------------------

**Attachments require filenames**
  Mailgun has an `undocumented API requirement`_ that every attachment must have a
  filename. Attachments with missing filenames are silently dropped from the sent
  message.

  To avoid unexpected behavior, Anymail will use ``"attachment"`` as the filename
  if you don't supply a filename.

  .. versionchanged:: 14.0

     Earlier Anymail versions raised :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
     if you attempted to send an attachment through Mailgun without a filename.

**Display name problems with punctuation and non-ASCII characters**
  Mailgun does not correctly handle certain display names in :mailheader:`From`,
  :mailheader:`To`, and other email headers. If a display name includes *both* non-ASCII characters
  and certain punctuation (such as parentheses), the resulting email will
  use a non-standard encoding that causes some email clients to display
  additional `"` or `\\"` characters wrapping the display name. (Verified
  and reported to Mailgun engineering 3/2022. See `Anymail issue #270`_
  for examples and specific details.)

**Envelope sender uses only domain**
  Anymail's :attr:`~anymail.message.AnymailMessage.envelope_sender` is used to
  select your Mailgun :ref:`sender domain <mailgun-sender-domain>`. For
  obvious reasons, only the domain portion applies. You can use anything before
  the @, and it will be ignored.

**Using merge_metadata and merge_headers with merge_data**
  If you use both Anymail's :attr:`~anymail.message.AnymailMessage.merge_data`
  and :attr:`~anymail.message.AnymailMessage.merge_metadata` features, make sure your
  :attr:`~!anymail.message.AnymailMessage.merge_data` keys do not start with ``v:``.

  Similarly, if you use Anymail's :attr:`~anymail.message.AnymailMessage.merge_headers`
  together with :attr:`~anymail.message.AnymailMessage.merge_data`, make sure your
  :attr:`~!anymail.message.AnymailMessage.merge_data` keys do not start with ``h:``.

  (It's a good idea anyway to avoid colons and other special characters in merge data
  keys, as this isn't generally portable to other ESPs.)

  The same underlying Mailgun feature ("recipient-variables") is used to implement
  all three Anymail features. To avoid conflicts, Anymail prepends ``v:`` to recipient
  variables needed for merge metadata, and ``h:`` for merge headers recipient variables.
  (These prefixes are stripped as Mailgun prepares the message to send, so won't appear
  in your Mailgun API logs or the metadata that is sent to tracking webhooks.)

**Additional limitations on merge_data with template_id**
  If you are using Mailgun's stored handlebars templates (Anymail's
  :attr:`~anymail.message.AnymailMessage.template_id`), :attr:`~anymail.message.AnymailMessage.merge_data`
  cannot contain complex types or have any keys that conflict with
  :attr:`~anymail.message.AnymailMessage.metadata`. See :ref:`mailgun-template-limitations`
  below for more details.

**merge_metadata values default to empty string**
  If you use Anymail's :attr:`~anymail.message.AnymailMessage.merge_metadata` feature,
  and you supply metadata keys for some recipients but not others, Anymail will first
  try to resolve the missing keys in :attr:`~anymail.message.AnymailMessage.metadata`,
  and if they are not found there will default them to an empty string value.

  Your tracking webhooks will receive metadata values (either that you provided or the
  default empty string) for *every* key used with *any* recipient in the send.

**AMP for Email**
  Mailgun supports sending AMPHTML email content. To include it, use
  ``message.attach_alternative("...AMPHTML content...", "text/x-amp-html")``
  (and be sure to also include regular HTML and/or text bodies, too).

  .. versionadded:: 8.2

**Non-ASCII mailboxes (EAI)**
  Mailgun partially supports Unicode mailboxes (the *user* part of
  *user\@domain*---see :ref:`EAI <eai>`). EAI recipient addresses (to, cc, bcc)
  are delivered correctly, but Mailgun generates invalid header fields that may
  display as empty or garbled, depending on the email app.

  For an EAI ``from_email``, the invalid :mailheader:`From` header Mailgun
  generates can prevent delivery and cause confusing bounce messages. To avoid
  this, Anymail raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
  error if you attempt to send *from* an EAI address using Mailgun.

.. _Anymail issue #270:
    https://github.com/anymail/django-anymail/issues/270
.. _undocumented API requirement:
    https://mailgun.uservoice.com/forums/156243-feature-requests/suggestions/35668606


.. _mailgun-templates:

Batch sending/merge and ESP templates
-------------------------------------

Mailgun supports :ref:`ESP stored templates <esp-stored-templates>`, on-the-fly
templating, and :ref:`batch sending <batch-send>` with per-recipient merge data.

.. versionchanged:: 7.0

  Added support for Mailgun's stored (handlebars) templates.

Mailgun has two different syntaxes for substituting data into templates:

* "Recipient variables" look like ``%recipient.name%``, and are used with on-the-fly
  templates. You can refer to a recipient variable inside a message's body, subject,
  or other message attributes defined in your Django code. See `Mailgun batch sending`_
  for more information. (Note that Mailgun's docs also sometimes refer to recipient
  variables as "template *variables*," and there are some additional predefined ones
  described in their docs.)

* "Template *substitutions*" look like ``{{ name }}``, and can *only* be used in
  handlebars templates that are defined and stored in your Mailgun account (via
  the Mailgun dashboard or API). You refer to a stored template using Anymail's
  :attr:`~anymail.message.AnymailMessage.template_id` in your Django code.
  See `Mailgun templates`_ for more information.

With either type of template, you supply the substitution data using Anymail's
normalized :attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_global_data` message attributes. Anymail
will figure out the correct Mailgun API parameters to use.

Here's an example defining an on-the-fly template that uses Mailgun recipient variables:

  .. code-block:: python

      message = EmailMessage(
          from_email="shipping@example.com",
          # Use %recipient.___% syntax in subject and body:
          subject="Your order %recipient.order_no% has shipped",
          body="""Hi %recipient.name%,
                  We shipped your order %recipient.order_no%
                  on %recipient.ship_date%.""",
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      # (you'd probably also set a similar html body with %recipient.___% variables)
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15"  # Anymail maps globals to all recipients
      }

And here's an example that uses the same data with a stored template, which could refer
to ``{{ name }}``, ``{{ order_no }}``, and ``{{ ship_date }}`` in its definition:

  .. code-block:: python

      message = EmailMessage(
          from_email="shipping@example.com",
          # The message body and html_body come from from the stored template.
          # (You can still use %recipient.___% fields in the subject:)
          subject="Your order %recipient.order_no% has shipped",
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = 'shipping-notification'  # name of template in our account
      # The substitution data is exactly the same as in the previous example:
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15"  # Anymail maps globals to all recipients
      }

When you supply per-recipient :attr:`~anymail.message.AnymailMessage.merge_data`,
Anymail supplies Mailgun's ``recipient-variables`` parameter, which puts Mailgun
in batch sending mode so that each "to" recipient sees only their own email address.
(Any cc's or bcc's will be duplicated for *every* to-recipient.)

If you want to use batch sending with a regular message (without a template), set
merge data to an empty dict: `message.merge_data = {}`.

Mailgun does not natively support global merge data. Anymail emulates
the capability by copying any :attr:`~anymail.message.AnymailMessage.merge_global_data`
values to every recipient.

.. _mailgun-template-limitations:

Limitations with stored handlebars templates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Although Anymail tries to insulate you from Mailgun's relatively complicated API
parameters for template substitutions in batch sends, there are two cases it can't
handle. These *only* apply to stored handlebars templates (when you've set Anymail's
:attr:`~anymail.message.AnymailMessage.template_id` attribute).

First, metadata and template merge data substitutions use the same underlying
"custom data" API parameters when a handlebars template is used. If you have any
duplicate keys between your tracking metadata
(:attr:`~anymail.message.AnymailMessage.metadata`/:attr:`~anymail.message.AnymailMessage.merge_metadata`)
and your template merge data
(:attr:`~anymail.message.AnymailMessage.merge_data`/:attr:`~anymail.message.AnymailMessage.merge_global_data`),
Anymail will raise an :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error.

Second, Mailgun's API does not allow complex data types like lists or dicts to be
passed as template substitutions for a batch send (confirmed with Mailgun support
8/2019). Your Anymail :attr:`~anymail.message.AnymailMessage.merge_data` and
:attr:`~anymail.message.AnymailMessage.merge_global_data` should only use simple
types like string or number. This means you cannot use the handlebars ``{{#each item}}``
block helper or dotted field notation like ``{{object.field}}`` with data passed
through Anymail's normalized merge data attributes.

Most ESPs do not support complex merge data types, so trying to do that is not recommended
anyway, for portability reasons. But if you *do* want to pass complex types to Mailgun
handlebars templates, and you're only sending to one recipient at a time, here's a
(non-portable!) workaround:

  .. code-block:: python

      # Using complex substitutions with Mailgun handlebars templates.
      # This works only for a single recipient, and is not at all portable between ESPs.
      message = EmailMessage(
          from_email="shipping@example.com",
          to=["alice@example.com"],  # single recipient *only* (no batch send)
          subject="Your order has shipped",  # recipient variables *not* available
      )
      message.template_id = 'shipping-notification'  # name of template in our account
      substitutions = {
          'items': [  # complex substitution data
              {'product': "Anvil", 'quantity': 1},
              {'product': "Tacks", 'quantity': 100},
          ],
          'ship_date': "May 15",
      }
      # Do *not* set Anymail's message.merge_data, merge_global_data, or merge_metadata.
      # Instead add Mailgun custom variables directly:
      message.extra_headers['X-Mailgun-Variables'] = json.dumps(substitutions)


.. _Mailgun batch sending:
    https://documentation.mailgun.com/en/latest/user_manual.html#batch-sending
.. _Mailgun templates:
    https://documentation.mailgun.com/en/latest/user_manual.html#templates

.. _mailgun-webhooks:

Status tracking webhooks
------------------------

.. versionchanged:: 4.0

    Added support for Mailgun's June, 2018 (non-"legacy") webhook format.

.. versionchanged:: 6.1

    Added support for a new :setting:`MAILGUN_WEBHOOK_SIGNING_KEY <ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY>`
    setting, separate from your MAILGUN_API_KEY.

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, enter
the url in the Mailgun webhooks config for your domain. (Be sure to select the correct
sending domain---Mailgun's sandbox and production domains have separate webhook settings.)

Mailgun allows you to enter a different URL for each event type: just enter this same
Anymail tracking URL for all events you want to receive:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailgun/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Mailgun implements a limited form of webhook signing, and Anymail will verify
these signatures against your
:setting:`MAILGUN_WEBHOOK_SIGNING_KEY <ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY>`
Anymail setting. By default, Mailgun's webhook signature provides similar security
to Anymail's shared webhook secret, so it's acceptable to omit the
:setting:`ANYMAIL_WEBHOOK_SECRET` setting (and "{random}:{random}@" portion of the
webhook url) with Mailgun webhooks.

Mailgun will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
delivered, rejected, bounced, complained, unsubscribed, opened, clicked.

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
the parsed `Mailgun webhook payload`_ as a Python `dict` with ``"signature"`` and
``"event-data"`` keys.

Anymail uses Mailgun's webhook ``token`` as its normalized
:attr:`~anymail.signals.AnymailTrackingEvent.event_id`, rather than Mailgun's
event-data ``id`` (which is only guaranteed to be unique during a single day).
If you need the event-data id, it can be accessed in your webhook handler as
``event.esp_event["event-data"]["id"]``. (This can be helpful for working with
Mailgun's other event APIs.)

.. note:: **Mailgun legacy webhooks**

    In late June, 2018, Mailgun introduced a new set of webhooks with an improved
    payload design, and at the same time renamed their original webhooks to "Legacy
    Webhooks."

    Anymail v4.0 and later supports both new and legacy Mailgun webhooks, and the same
    Anymail webhook url works as either. Earlier Anymail versions can only be used
    as legacy webhook urls.

    The new (non-legacy) webhooks are preferred, particularly with Anymail's
    :attr:`~anymail.message.AnymailMessage.metadata` and
    :attr:`~anymail.message.AnymailMessage.tags` features. But if you have already
    configured the legacy webhooks, there is no need to change.

    If you are using Mailgun's legacy webhooks:

    * The :attr:`event.esp_event <anymail.signals.AnymailTrackingEvent.esp_event>` field
      will be a Django :class:`~django.http.QueryDict` of Mailgun event fields (the
      raw POST data provided by legacy webhooks).

    * You should avoid using "body-plain," "h," "message-headers," "message-id" or "tag"
      as :attr:`~anymail.message.AnymailMessage.metadata` keys. A design limitation in
      Mailgun's legacy webhooks prevents Anymail from reliably retrieving this metadata
      from opened, clicked, and unsubscribed events. (This is not an issue with the
      newer, non-legacy webhooks.)


.. _Mailgun webhook payload: https://documentation.mailgun.com/en/latest/user_manual.html#webhooks


.. _mailgun-inbound:

Inbound webhook
---------------

If you want to receive email from Mailgun through Anymail's normalized :ref:`inbound <inbound>`
handling, follow Mailgun's `Receiving, Forwarding and Storing Messages`_ guide to set up
an inbound route that forwards to Anymail's inbound webhook. Create an inbound route
in Mailgun's dashboard on the `Email Receiving panel`_, or use Mailgun's API.

Use this url as the route's "forward" destination:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailgun/inbound_mime/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site
     * :samp:`mime` at the end tells Mailgun to supply the entire message in "raw MIME" format
       (see note below)

You must use Mailgun's "forward" route action; Anymail does not currently support "store and notify."
(For debugging, you might find it helpful to *also* enable the "store" route action to keep a copy
of inbound messages on Mailgun's servers, but Anymail's inbound webhook won't work as a store-notify url.)

If you want to use Anymail's normalized :attr:`~anymail.inbound.AnymailInboundMessage.spam_detected` and
:attr:`~anymail.inbound.AnymailInboundMessage.spam_score` attributes, you'll need to set your Mailgun
domain's inbound spam filter to "Deliver spam, but add X-Mailgun-SFlag and X-Mailgun-SScore headers"
(in the `Mailgun domains config`_).

Anymail will verify Mailgun inbound message events using your
:setting:`MAILGUN_WEBHOOK_SIGNING_KEY <ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY>`
Anymail setting. By default, Mailgun's webhook signature provides similar security
to Anymail's shared webhook secret, so it's acceptable to omit the
:setting:`ANYMAIL_WEBHOOK_SECRET` setting (and :samp:`{random:random}@` portion of the
forwarding url) with Mailgun inbound routing.

.. note::

    Anymail supports both of Mailgun's "fully-parsed" and "raw MIME" inbound
    message formats. The raw MIME version is preferred to get the most accurate
    representation of any received email. Using raw MIME also avoids a limitation
    in Django's :mimetype:`multipart/form-data` handling that can strip attachments
    with certain filenames (and inline images without filenames).

    * To use raw MIME (recommended), the route forwarding url should end with
      :samp:`…/inbound_mime/` as shown above.
    * To use fully-parsed format (not recommended), omit the :samp:`_mime` so
      the route forwarding url ends with just :samp:`…/inbound/`.

    .. versionchanged:: 8.6
       Using Mailgun's fully-parsed inbound message format is no longer recommended.


.. _Receiving, Forwarding and Storing Messages:
   https://documentation.mailgun.com/en/latest/user_manual.html#receiving-forwarding-and-storing-messages
.. _Email Receiving panel: https://app.mailgun.com/app/receiving/routes
.. _Mailgun domains config: https://app.mailgun.com/app/sending/domains
