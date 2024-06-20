.. _mandrill-backend:

Mandrill
========

Anymail integrates with the `Mandrill`_ transactional email service from MailChimp,
using their `/messages/send`_ HTTP API.

.. note:: **Limited Mandrill Testing**

    Anymail is developed to the public Mandrill documentation, but unlike
    other supported ESPs, we are unable to regularly test against the live
    Mandrill APIs. (MailChimp doesn't offer ongoing testing access for open source
    packages like Anymail. We *do* have a limited use trial account, but we try to
    save that for debugging specific issues reported by Anymail users.)

    If you are using only Mandrill, and unlikely to ever need a different ESP,
    you might prefer using MailChimp's official `mailchimp-transactional-python`_
    package instead of Anymail.

.. _Mandrill:
    https://mandrill.com/
.. _/messages/send:
    https://mailchimp.com/developer/transactional/api/messages/send-new-message/
.. _mailchimp-transactional-python:
    https://github.com/mailchimp/mailchimp-transactional-python/


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Mandrill backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mandrill.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MANDRILL_API_KEY

.. rubric:: MANDRILL_API_KEY

Required. Your Mandrill API key:

  .. code-block:: python

      ANYMAIL = {
          ...
          "MANDRILL_API_KEY": "<your API key>",
      }

Anymail will also look for ``MANDRILL_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["MANDRILL_API_KEY"]``
nor ``ANYMAIL_MANDRILL_API_KEY`` is set.


.. setting:: ANYMAIL_MANDRILL_WEBHOOK_KEY

.. rubric:: MANDRILL_WEBHOOK_KEY

Required if using Anymail's webhooks. The "webhook authentication key"
issued by Mandrill. See `Authenticating webhook requests`_ in the Mandrill docs.

.. _Authenticating webhook requests:
    https://mailchimp.com/developer/transactional/guides/track-respond-activity-webhooks/#authenticating-webhook-requests

.. setting:: ANYMAIL_MANDRILL_WEBHOOK_URL

.. rubric:: MANDRILL_WEBHOOK_URL

Required only if using Anymail's webhooks *and* the hostname your
Django server sees is different from the public webhook URL
you provided Mandrill. (E.g., if you have a proxy in front
of your Django server that forwards
"https\://yoursite.example.com" to "http\://localhost:8000/").

If you are seeing :exc:`AnymailWebhookValidationFailure` errors
from your webhooks, set this to the exact webhook URL you entered
in Mandrill's settings.


.. setting:: ANYMAIL_MANDRILL_API_URL

.. rubric:: MANDRILL_API_URL

The base url for calling the Mandrill API. The default is
``MANDRILL_API_URL = "https://mandrillapp.com/api/1.0"``,
which is the secure, production version of Mandrill's 1.0 API.

(It's unlikely you would need to change this.)


.. _mandrill-esp-extra:

esp_extra support
-----------------

To use Mandrill features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` of parameters to merge into Mandrill's `/messages/send`_ API call.
Note that a few parameters go at the top level, but Mandrill expects
most options within a `'message'` sub-dict---be sure to check their
API docs:

  .. code-block:: python

      message.esp_extra = {
          # Mandrill expects 'ip_pool' at top level...
          'ip_pool': 'Bulk Pool',
          # ... but 'subaccount' must be within a 'message' dict:
          'message': {
              'subaccount': 'Marketing Dept.'
          }
      }

Anymail has special handling that lets you specify Mandrill's
`'recipient_metadata'` as a simple, pythonic `dict` (similar in form
to Anymail's :attr:`~anymail.message.AnymailMessage.merge_data`),
rather than Mandrill's more complex list of rcpt/values dicts.
You can use whichever style you prefer (but either way,
recipient_metadata must be in `esp_extra['message']`).

Similarly, Anymail allows Mandrill's `'template_content'` in esp_extra
(top level) either as a pythonic `dict` (similar to Anymail's
:attr:`~anymail.message.AnymailMessage.merge_global_data`) or
as Mandrill's more complex list of name/content dicts.


.. _mandrill-quirks:

Limitations and quirks
----------------------

**Non-ASCII attachment filenames will be garbled**
  Mandrill's /messages/send API does not properly handle non-ASCII characters
  in attachment filenames. As a result, some email clients will display
  those characters incorrectly. The only workaround is to limit
  attachment filenames to ASCII when sending through Mandrill.
  (Verified and reported to MailChimp support 4/2022;
  see `Anymail discussion #257`_ for more details.)

**No merge headers support**
  Mandrill's API does not provide a way to support Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_headers`.

**Envelope sender uses only domain**
  Anymail's :attr:`~anymail.message.AnymailMessage.envelope_sender` is used to
  populate Mandrill's `'return_path_domain'`---but only the domain portion.
  (Mandrill always generates its own encoded mailbox for the envelope sender.)

.. _Anymail discussion #257:
     https://github.com/anymail/django-anymail/discussions/257


.. _mandrill-templates:

Batch sending/merge and ESP templates
-------------------------------------

Mandrill offers both :ref:`ESP stored templates <esp-stored-templates>`
and :ref:`batch sending <batch-send>` with per-recipient merge data.

You can use a Mandrill stored template by setting a message's
:attr:`~anymail.message.AnymailMessage.template_id` to the
template's name. Alternatively, you can refer to merge fields
directly in an EmailMessage's subject and body---the message itself
is used as an on-the-fly template.

In either case, supply the merge data values with Anymail's
normalized :attr:`~anymail.message.AnymailMessage.merge_data`
and :attr:`~anymail.message.AnymailMessage.merge_global_data`
message attributes.

  .. code-block:: python

      # This example defines the template inline, using Mandrill's
      # default MailChimp merge *|field|* syntax.
      # You could use a stored template, instead, with:
      #   message.template_id = "template name"
      message = EmailMessage(
          ...
          subject="Your order *|order_no|* has shipped",
          body="""Hi *|name|*,
                  We shipped your order *|order_no|*
                  on *|ship_date|*.""",
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      # (you'd probably also set a similar html body with merge fields)
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
      }

When you supply per-recipient :attr:`~anymail.message.AnymailMessage.merge_data`,
Anymail automatically forces Mandrill's `preserve_recipients` option to false,
so that each person in the message's "to" list sees only their own email address.

To use the subject or from address defined with a Mandrill template, set the message's
`subject` or `from_email` attribute to `None`.

See the `Mandrill's template docs`_ for more information.

.. _Mandrill's template docs:
    https://mailchimp.com/developer/transactional/docs/templates-dynamic-content/


.. _mandrill-webhooks:
.. _mandrill-inbound:

Status tracking and inbound webhooks
------------------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`
and/or :ref:`inbound <inbound>` handling, setting up Anymail's webhook URL
requires deploying your Django project twice:

1. First, follow the instructions to
   :ref:`configure Anymail's webhooks <webhooks-configuration>`. You *must deploy*
   before adding the webhook URL to Mandrill, because Mandrill will attempt
   to verify the URL against your production server.

   Once you've deployed, then set Anymail's webhook URL in Mandrill, following their
   instructions for `tracking event webhooks`_ (be sure to check the boxes for the
   events you want to receive) and/or `inbound route webhooks`_.
   In either case, the webhook url is:

      :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mandrill/`

        * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
        * *yoursite.example.com* is your Django site
        * (Note: Unlike Anymail's other supported ESPs, the Mandrill webhook uses this
          single url for both tracking and inbound events.)

2. Mandrill will provide you a "webhook authentication key" once it verifies the URL
   is working. Add this to your Django project's Anymail settings under
   :setting:`MANDRILL_WEBHOOK_KEY <ANYMAIL_MANDRILL_WEBHOOK_KEY>`.
   (You may also need to set :setting:`MANDRILL_WEBHOOK_URL <ANYMAIL_MANDRILL_WEBHOOK_URL>`
   depending on your server config.) Then deploy your project again.

Mandrill implements webhook signing on the entire event payload, and Anymail verifies this
signature. Until the correct webhook key is set, Anymail will raise
an exception for any webhook calls from Mandrill (other than the initial validation request).

Mandrill's webhook signature also covers the exact posting URL. Anymail can usually
figure out the correct (public) URL where Mandrill called your webhook. But if you're
getting an :exc:`AnymailWebhookValidationFailure` with a different URL than you
provided Mandrill, you may need to examine your Django :setting:`SECURE_PROXY_SSL_HEADER`,
:setting:`USE_X_FORWARDED_HOST`, and/or :setting:`USE_X_FORWARDED_PORT` settings. If all
else fails, you can set Anymail's :setting:`MANDRILL_WEBHOOK_URL <ANYMAIL_MANDRILL_WEBHOOK_URL>`
to the same public webhook URL you gave Mandrill.

Mandrill will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
sent, rejected, deferred, bounced, opened, clicked, complained, unsubscribed, inbound. Mandrill does
not support delivered events. Mandrill "whitelist" and "blacklist" change events will show up
as Anymail's unknown event_type.

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of Mandrill event fields, for a single event. (Although Mandrill calls
webhooks with batches of events, Anymail will invoke your signal receiver separately
for each event in the batch.)

.. _tracking event webhooks:
    https://mailchimp.com/developer/transactional/docs/webhooks/#add-a-new-webhook
.. _inbound route webhooks:
    https://mailchimp.com/developer/transactional/guides/set-up-inbound-email-processing/


.. _migrating-from-djrill:

Migrating from Djrill
---------------------

Anymail has its origins as a fork of the `Djrill`_
package, which supported only Mandrill. If you are migrating
from Djrill to Anymail -- e.g., because you are thinking
of switching ESPs -- you'll need to make a few changes
to your code.

.. _Djrill: https://github.com/brack3t/Djrill

Changes to settings
~~~~~~~~~~~~~~~~~~~

``MANDRILL_API_KEY``
  Will still work, but consider moving it into the :setting:`ANYMAIL`
  settings dict, or changing it to :setting:`ANYMAIL_MANDRILL_API_KEY`.

``MANDRILL_SETTINGS``
  Use :setting:`ANYMAIL_SEND_DEFAULTS` and/or :setting:`ANYMAIL_MANDRILL_SEND_DEFAULTS`
  (see :ref:`send-defaults`).

  There is one slight behavioral difference between :setting:`ANYMAIL_SEND_DEFAULTS`
  and Djrill's ``MANDRILL_SETTINGS``: in Djrill, setting :attr:`tags` or
  :attr:`merge_vars` on a message would completely override any global
  settings defaults. In Anymail, those message attributes are merged with
  the values from :setting:`ANYMAIL_SEND_DEFAULTS`.

``MANDRILL_SUBACCOUNT``
  Set :ref:`esp_extra <mandrill-esp-extra>`
  globally in :setting:`ANYMAIL_SEND_DEFAULTS`:

    .. code-block:: python

        ANYMAIL = {
            ...
            "MANDRILL_SEND_DEFAULTS": {
                "esp_extra": {
                    "message": {
                        "subaccount": "<your subaccount>"
                    }
                }
            }
        }

``MANDRILL_IGNORE_RECIPIENT_STATUS``
  Renamed to :setting:`ANYMAIL_IGNORE_RECIPIENT_STATUS`
  (or just `IGNORE_RECIPIENT_STATUS` in the :setting:`ANYMAIL`
  settings dict).

``DJRILL_WEBHOOK_SECRET`` and ``DJRILL_WEBHOOK_SECRET_NAME``
  Replaced with HTTP basic auth. See :ref:`securing-webhooks`.

``DJRILL_WEBHOOK_SIGNATURE_KEY``
  Use :setting:`ANYMAIL_MANDRILL_WEBHOOK_KEY` instead.

``DJRILL_WEBHOOK_URL``
  Often no longer required: Anymail can normally use Django's
  :meth:`HttpRequest.build_absolute_uri <django.http.HttpRequest.build_absolute_uri>`
  to figure out the complete webhook url that Mandrill called.

  If you are experiencing webhook authorization errors, the best solution is to adjust
  your Django :setting:`SECURE_PROXY_SSL_HEADER`, :setting:`USE_X_FORWARDED_HOST`, and/or
  :setting:`USE_X_FORWARDED_PORT` settings to work with your proxy server.
  If that's not possible, you can set :setting:`ANYMAIL_MANDRILL_WEBHOOK_URL` to explicitly
  declare the webhook url.


Changes to EmailMessage attributes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``message.send_at``
  If you are using an aware datetime for
  :attr:`~anymail.message.AnymailMessage.send_at`,
  it will keep working unchanged with Anymail.

  If you are using a date (without a time), or a naive datetime,
  be aware that these now default to Django's current_timezone,
  rather than UTC as in Djrill.

  (As with Djrill, it's best to use an aware datetime
  that says exactly when you want the message sent.)


``message.mandrill_response``
  Anymail normalizes ESP responses, so you don't have to be familiar
  with the format of Mandrill's JSON.
  See :attr:`~anymail.message.AnymailMessage.anymail_status`.

  The *raw* ESP response is attached to a sent message as
  ``anymail_status.esp_response``, so the direct replacement
  for message.mandrill_response is:

    .. code-block:: python

        mandrill_response = message.anymail_status.esp_response.json()

``message.template_name``
  Anymail renames this to :attr:`~anymail.message.AnymailMessage.template_id`.

``message.merge_vars`` and ``message.global_merge_vars``
  Anymail renames these to :attr:`~anymail.message.AnymailMessage.merge_data`
  and :attr:`~anymail.message.AnymailMessage.merge_global_data`, respectively.

``message.use_template_from`` and ``message.use_template_subject``
  With Anymail, set ``message.from_email = None`` or ``message.subject = None``
  to use the values from the stored template.

``message.return_path_domain``
  With Anymail, set :attr:`~anymail.message.AnymailMessage.envelope_sender`
  instead. You'll need to pass a valid email address (not just a domain),
  but Anymail will use only the domain, and will ignore anything before the @.

.. _djrill-message-attributes:

**Other Mandrill-specific attributes**
  Djrill allowed nearly all Mandrill API parameters to be set
  as attributes directly on an EmailMessage. With Anymail, you
  should instead set these in the message's
  :ref:`esp_extra <mandrill-esp-extra>` dict as described above.

  .. versionchanged:: 10.0

        These Djrill-specific attributes are no longer supported,
        and will be silently ignored. (Earlier versions raised a
        :exc:`DeprecationWarning` but still worked.)

  You can also use the following git grep expression to find potential
  problems:

    .. code-block:: console

        git grep -w \
          -e 'async' -e 'auto_html' -e 'auto_text' -e 'from_name' -e 'global_merge_vars' \
          -e 'google_analytics_campaign' -e 'google_analytics_domains' -e 'important' \
          -e 'inline_css' -e 'ip_pool' -e 'merge_language' -e 'merge_vars' \
          -e 'preserve_recipients' -e 'recipient_metadata' -e 'return_path_domain' \
          -e 'signing_domain' -e 'subaccount' -e 'template_content' -e 'template_name' \
          -e 'tracking_domain' -e 'url_strip_qs' -e 'use_template_from' -e 'use_template_subject' \
          -e 'view_content_link'


**Inline images**
  Djrill (incorrectly) used the presence of a :mailheader:`Content-ID`
  header to decide whether to treat an image as inline. Anymail
  looks for :mailheader:`Content-Disposition: inline`.

  If you were constructing MIMEImage inline image attachments
  for your Djrill messages, in addition to setting the Content-ID,
  you should also add::

      image.add_header('Content-Disposition', 'inline')

  Or better yet, use Anymail's new :ref:`inline-images`
  helper functions to attach your inline images.


Changes to webhooks
~~~~~~~~~~~~~~~~~~~

Anymail uses HTTP basic auth as a shared secret for validating webhook
calls, rather than Djrill's "secret" query parameter. See
:ref:`securing-webhooks`. (A slight advantage of basic auth over query
parameters is that most logging and analytics systems are aware of the
need to keep auth secret.)

Anymail replaces `djrill.signals.webhook_event` with
`anymail.signals.tracking` for delivery tracking events,
and `anymail.signals.inbound` for inbound events.
Anymail parses and normalizes
the event data passed to the signal receiver: see :ref:`event-tracking`
and :ref:`inbound`.

The equivalent of Djrill's ``data`` parameter is available
to your signal receiver as
:attr:`event.esp_event <anymail.signals.AnymailTrackingEvent.esp_event>`,
and for most events, the equivalent of Djrill's ``event_type`` parameter
is `event.esp_event['event']`. But consider working with Anymail's
normalized :class:`~anymail.signals.AnymailTrackingEvent` and
:class:`~anymail.signals.AnymailInboundEvent` instead for easy portability
to other ESPs.
