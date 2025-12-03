.. _resend-backend:

Resend
======

Anymail integrates Django with the `Resend`_ transactional
email service, using their `send-email API`_ endpoint.

.. versionadded:: 10.2

.. _Resend: https://resend.com/
.. _send-email API: https://resend.com/docs/api-reference/emails/send-email


.. _resend-installation:

Installation
------------

Anymail uses the :pypi:`svix` package to validate Resend webhook signatures.
If you will use Anymail's :ref:`status tracking <event-tracking>` webhook
with Resend, and you want to use webhook signature validation, be sure
to include the ``[resend]`` option when you install Anymail:

    .. code-block:: console

        $ python -m pip install 'django-anymail[resend]'

(Or separately run ``python -m pip install svix``.)

The svix package pulls in several other dependencies, so its use
is optional in Anymail. See :ref:`resend-webhooks` below for details.
To avoid installing svix with Anymail, just omit the ``[resend]`` option.


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Resend backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_RESEND_API_KEY

.. rubric:: RESEND_API_KEY

Required for sending. An API key from your `Resend API Keys`_.
Anymail needs only "sending access" permission; "full access" is not recommended.

  .. code-block:: python

      ANYMAIL = {
          ...
          "RESEND_API_KEY": "re_...",
      }

Anymail will also look for ``RESEND_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["RESEND_API_KEY"]``
nor ``ANYMAIL_RESEND_API_KEY`` is set.

.. _Resend API Keys: https://resend.com/api-keys


.. setting:: ANYMAIL_RESEND_SIGNING_SECRET

.. rubric:: RESEND_SIGNING_SECRET

The Resend webhook signing secret used to verify webhook posts.
Recommended if you are using activity tracking, otherwise not necessary.
(This is separate from Anymail's
:setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>` setting.)

Find this in your Resend `Webhooks settings`_: after adding
a webhook, click into its management page and look for "signing secret"
near the top.

  .. code-block:: python

      ANYMAIL = {
          ...
          "RESEND_SIGNING_SECRET": "whsec_...",
      }

If you provide this setting, the svix package is required.
See :ref:`resend-installation` above.


.. setting:: ANYMAIL_RESEND_API_URL

.. rubric:: RESEND_API_URL

The base url for calling the Resend API.

The default is ``RESEND_API_URL = "https://api.resend.com/"``.
(It's unlikely you would need to change this.)

.. _Webhooks settings: https://resend.com/webhooks


.. _resend-quirks:

Limitations and quirks
----------------------

Resend does not support a few features offered by some other ESPs,
and can have unexpected behavior for some common use cases.

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using features that Resend doesn't support.
You can tell Anymail to suppress these errors and send the messages
anyway---see :ref:`unsupported-features`.

**Attachment filename determines content type**
  Resend determines the content type of an attachment from its filename extension.

  If you try to send an attachment without a filename, Anymail will substitute
  "attachment\ *.ext*" using an appropriate *.ext* for the content type.

  If you try to send an attachment whose content type doesn't match its filename
  extension, Resend will change the content type to match the extension.
  (E.g., the filename "data.txt" will always be sent as "text/plain",
  even if you specified a "text/csv" content type.)

**No inline images**
  Resend's API does not provide a mechanism to send inline content
  or to specify :mailheader:`Content-ID` for an attachment.

**Anymail tags and metadata are exposed to recipient**
  Anymail implements its normalized :attr:`~anymail.message.AnymailMessage.tags`
  and :attr:`~anymail.message.AnymailMessage.metadata` features for Resend
  using custom email headers. That means they can be visible to recipients
  via their email app's "show original message" (or similar) command.
  **Do not include sensitive data in tags or metadata.**

  Resend also offers a feature it calls "tags", which allows arbitrary key-value
  data to be tracked with a sent message (similar Anymail's
  :attr:`~anymail.message.AnymailMessage.metadata`). Resend's native tags
  are *not* exposed to recipients, but they have significant restrictions
  on character set and length (for both keys and values).

  If you want to use Resend's native tags with Anymail, you can send them
  using :ref:`esp_extra <resend-esp-extra>`, and retrieve them in a status
  tracking webhook using :ref:`esp_event <resend-esp-event>`. (The linked
  sections below include examples.)

**No click/open tracking overrides**
  Resend does not support :attr:`~anymail.message.AnymailMessage.track_clicks`
  or :attr:`~anymail.message.AnymailMessage.track_opens`. Its
  tracking features can only be configured at the domain level
  in Resend's control panel.

**No attachments with delayed sending**
  Resend does not support attachments or batch sending features when using
  :attr:`~anymail.message.AnymailMessage.send_at`.

  .. versionchanged:: 12.0
      Resend now supports :attr:`~anymail.message.AnymailMessage.send_at`.

**No attachments with batch sending**
  Resend does not currently support attachments when using
  :ref:`batch sending <resend-templates>`. Trying to send an attachment
  while using :attr:`~anymail.message.AnymailMessage.merge_metadata` may
  result in a Resend API error.

**No envelope sender**
  Resend does not support specifying the
  :attr:`~anymail.message.AnymailMessage.envelope_sender`.

**Status tracking does not identify recipient**
  If you send a message with multiple recipients (to, cc, and/or bcc),
  Resend's status webhooks do not identify which recipient applies
  for an event. See the :ref:`note below <resend-tracking-recipient>`.


.. _resend-api-rate-limits:

API rate limits
---------------
Resend provides `rate limit headers`_ with each API call response.
To access them after a successful send, use (e.g.,)
``message.anymail_status.esp_response.headers["ratelimit-remaining"]``.

If you exceed a rate limit, you'll get an :exc:`~anymail.exceptions.AnymailAPIError`
with ``error.status_code == 429``, and can determine how many seconds to wait
from ``error.response.headers["retry-after"]``.

.. _rate limit headers:
   https://resend.com/docs/api-reference/introduction#rate-limit


.. _resend-esp-extra:

exp_extra support
-----------------

Anymail's Resend backend will pass :attr:`~anymail.message.AnymailMessage.esp_extra`
values directly to Resend's `send-email API`_. Example:

  .. code-block:: python

      message = AnymailMessage(...)
      message.esp_extra = {
          # Use Resend's native "tags" feature
          # (be careful about character set restrictions):
          "tags": [
              {"name": "Co_Brand", "value": "Acme_Inc"},
              {"name": "Feature_Flag_1", "value": "test_22_a"},
          ],
      }


.. _resend-templates:

Batch sending/merge and ESP templates
-------------------------------------

.. versionadded:: 10.3

    Support for batch sending with
    :attr:`~anymail.message.AnymailMessage.merge_metadata`.

Resend supports :ref:`batch sending <batch-send>` (where each *To*
recipient sees only their own email address). It also supports
per-recipient metadata with batch sending.

Set Anymail's normalized :attr:`~anymail.message.AnymailMessage.merge_metadata`
attribute to use Resend's batch-send API:

  .. code-block:: python

      message = EmailMessage(
          to=["alice@example.com", "Bob <bob@example.com>"],
          from_email="...", subject="...", body="..."
      )
      message.merge_metadata = {
          'alice@example.com': {'user_id': "12345"},
          'bob@example.com': {'user_id': "54321"},
      }

Resend does not currently offer :ref:`ESP stored templates <esp-stored-templates>`
or merge capabilities, so does not support Anymail's
:attr:`~anymail.message.AnymailMessage.merge_data`,
:attr:`~anymail.message.AnymailMessage.merge_global_data`, or
:attr:`~anymail.message.AnymailMessage.template_id` message attributes.
(Resend's current template feature is only supported in node.js,
using templates that are rendered in their API client.)

(Setting :attr:`~anymail.message.AnymailMessage.merge_data` to an empty
dict will also invoke batch send, but trying to supply merge data for
any recipient will raise an :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error.)


.. _resend-webhooks:

Status tracking webhooks
------------------------

Anymail's normalized :ref:`status tracking <event-tracking>` works
with Resend's webhooks.

Resend implements webhook signing, using the :pypi:`svix` package
for signature validation (see :ref:`resend-installation` above). You have
three options for securing the status tracking webhook:

* Use Resend's webhook signature validation, by setting
  :setting:`RESEND_SIGNING_SECRET <ANYMAIL_RESEND_SIGNING_SECRET>`
  (requires the svix package)
* Use Anymail's shared secret validation, by setting
  :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`
  (does not require svix)
* Use both

Signature validation is recommended, unless you do not want to add
svix to your dependencies.

To configure Anymail status tracking for Resend,
add a new webhook endpoint to your `Resend Webhooks settings`_:

*   For the "Endpoint URL", enter one of these
    (where *yoursite.example.com* is your Django site).

    If are *not* using Anymail's shared webhook secret:

    :samp:`https://{yoursite.example.com}/anymail/resend/tracking/`

    Or if you *are* using Anymail's :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`,
    include the *random:random* shared secret in the URL:

    :samp:`https://{random}:{random}@{yoursite.example.com}/resend/tracking/`

*   For "Events to listen", select any or all events you want to track.

*   Click the "Add" button.

Then, if you are using Resend's webhook signature validation (with svix),
add the webhook signing secret to your Anymail settings:

*   Still on the `Resend Webhooks settings`_ page, click into the
    webhook endpoint URL you added above,
    and copy the "signing secret" listed near the top of the page.

*   Add that to your settings.py ``ANYMAIL`` settings as
    :setting:`RESEND_SIGNING_SECRET <ANYMAIL_RESEND_SIGNING_SECRET>`:

    .. code-block:: python

        ANYMAIL = {
            # ...
            "RESEND_SIGNING_SECRET": "whsec_..."
        }

Resend will report these Anymail
:attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
sent, delivered, bounced, deferred, complained, opened, and clicked.


.. _resend-tracking-recipient:

.. note::

    **Multiple recipients not recommended with tracking**

    If you send a message with multiple recipients (to, cc, and/or bcc),
    you will receive separate events (delivered, bounced, opened, etc.)
    for *every* recipient. But Resend does not identify *which* recipient
    applies for a particular event.

    The :attr:`event.recipient <anymail.signals.AnymailTrackingEvent.recipient>`
    will always be the first ``to`` email, but the event might actually have been
    generated by some other recipient.

    To avoid confusion, it's best to send each message to exactly one ``to``
    address, and avoid using cc or bcc.


.. _resend-esp-event:

The status tracking event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event`
field will be the parsed Resend webhook payload. For example, if you provided
Resend's native "tags" via :ref:`esp_extra <resend-esp-extra>` when sending,
you can retrieve them in your tracking signal receiver like this:

.. code-block:: python

    @receiver(tracking)
    def handle_tracking(sender, event, esp_name, **kwargs):
        ...
        resend_tags = event.esp_event.get("tags", {})
        # resend_tags will be a flattened dict (not
        # the name/value list used when sending). E.g.:
        # {"Co_Brand": "Acme_Inc", "Feature_Flag_1": "test_22_a"}


.. _Resend Webhooks settings: https://resend.com/webhooks


.. _resend-inbound:

Inbound
-------

Resend does not currently support inbound email.


.. _resend-troubleshooting:

Troubleshooting
---------------

If Anymail's Resend integration isn't behaving like you expect,
Resend's dashboard includes diagnostic logs that can help
isolate the problem:

* `Resend Logs page`_ lists every call received by Resend's API
* `Resend Emails page`_ shows every event related to email
  sent through Resend
* `Resend Webhooks page`_ shows every attempt by Resend to call
  your webhook (click into a webhook endpoint url to see
  the logs for that endpoint)

.. _Resend Emails page: https://resend.com/emails
.. _Resend Logs page: https://resend.com/logs
.. _Resend Webhooks page: https://resend.com/webhooks

See Anymail's :ref:`troubleshooting` docs for additional suggestions.
