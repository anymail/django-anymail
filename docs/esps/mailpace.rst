.. _mailpace-backend:

MailPace
==========

Anymail integrates Django with the `MailPace`_ transactional
email service, using their `send API`_ endpoint.

.. versionadded:: 10.3

.. _MailPace: https://mailpace.com/
.. _send API: https://docs.mailpace.com/reference/send


.. _mailpace-installation:

Installation
------------

Anymail uses the :pypi:`PyNaCl` package to validate MailPace webhook signatures.
If you will use Anymail's :ref:`status tracking <event-tracking>` webhook
with MailPace, and you want to use webhook signature validation, be sure
to include the ``[mailpace]`` option when you install Anymail:

    .. code-block:: console

        $ python -m pip install 'django-anymail[mailpace]'

(Or separately run ``python -m pip install pynacl``.)

The PyNaCl package pulls in several other dependencies, so its use
is optional in Anymail. See :ref:`mailpace-webhooks` below for details.
To avoid installing PyNaCl with Anymail, just omit the ``[mailpace]`` option.


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's MailPace backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailpace.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_MAILPACE_API_KEY

.. rubric:: MAILPACE_API_KEY

Required for sending. A domain specific API key from the MailPace app `MailPace app`_.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILPACE_API_KEY": "...",
      }

Anymail will also look for ``MAILPACE_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["MAILPACE_API_KEY"]``
nor ``ANYMAIL_MAILPACE_API_KEY`` is set.

.. _MailPace API Keys: https://app.mailpace.com/

.. setting:: MAILPACE_WEBHOOK_KEY

.. rubric:: MAILPACE_WEBHOOK_KEY

The MailPace webhook signing secret used to verify webhook posts.
Recommended if you are using activity tracking, otherwise not necessary.
(This is separate from Anymail's :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>` setting.)

Find this in your MailPace App `MailPace app`_ by opening your domain,
selecting webhooks, and look for the "Public Key Verification" section.

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILPACE_WEBHOOK_KEY": "...",
      }

If you provide this setting, the PyNaCl package is required.
See :ref:`mailpace-installation` above.


.. setting:: ANYMAIL_MAILPACE_API_URL

.. rubric:: MAILPACE_API_URL

The base url for calling the MailPace API.

The default is ``MAILPACE_API_URL = "https://app.mailpace.com/api/v1/send"``.
(It's unlikely you would need to change this.)

.. _MailPace app: https://app.mailpace.com/


.. _mailpace-quirks:

Limitations and quirks
----------------------

- MailPace does not, and will not ever support open tracking or click tracking.
  (You can still use Anymail's :ref:`status tracking <event-tracking>` which uses webhooks for tracking delivery)

.. _mailpace-webhooks:

Status tracking webhooks
------------------------

Anymail's normalized :ref:`status tracking <event-tracking>` works
with MailPace's webhooks.

MailPace implements webhook signing, using the :pypi:`PyNaCl` package
for signature validation (see :ref:`mailpace-installation` above). You have
three options for securing the status tracking webhook:

* Use MailPace's webhook signature validation, by setting
  :setting:`MAILPACE_WEBHOOK_KEY <ANYMAIL_MAILPACE_WEBHOOK_KEY>`
  (requires the PyNaCl package)
* Use Anymail's shared secret validation, by setting
  :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`
  (does not require PyNaCl)
* Use both

Signature validation is recommended, unless you do not want to add
PyNaCl to your dependencies.

To configure Anymail status tracking for MailPace,
add a new webhook endpoint to domain in the `MailPace app`_:

*   For the "Endpoint URL", enter one of these
    (where *yoursite.example.com* is your Django site).

    If are *not* using Anymail's shared webhook secret:

    :samp:`https://{yoursite.example.com}/anymail/mailpace/tracking/`

    Or if you *are* using Anymail's :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`,
    include the *random:random* shared secret in the URL:

    :samp:`https://{random}:{random}@{yoursite.example.com}/mailpace/tracking/`

*   For "Events", select any or all events you want to track.

*   Click the "Add Endpoint" button.

Then, if you are using MailPace's webhook signature validation (with PyNaCl),
add the webhook signing secret to your Anymail settings:

*   Still on the Webhooks page, scroll down to the "Public Key Verification" section.

*   Add that key to your settings.py ``ANYMAIL`` settings as
    :setting:`MAILPACE_WEBHOOK_KEY <ANYMAIL_MAILPACE_WEBHOOK_KEY>`:

    .. code-block:: python

        ANYMAIL = {
            # ...
            "MAILPACE_WEBHOOK_KEY": "..."
        }

MailPace will report these Anymail
:attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
queued, delivered, deferred, bounced, and spam.


.. _mailpace-tracking-recipient:

.. note::

    **Multiple recipients not recommended with tracking**

    If you send a message with multiple recipients (to, cc, and/or bcc),
    you will only receive one event (delivered, deferred, etc.)
    per email. MailPace does not send send different events for each 
    recipient.

    To avoid confusion, it's best to send each message to exactly one ``to``
    address, and avoid using cc or bcc.


.. _mailpace-esp-event:

The status tracking event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event`
field will be the parsed MailPace webhook payload. 

.. _mailpace-inbound:

Inbound
-------

If you want to receive email from Mailgun through Anymail's normalized :ref:`inbound <inbound>`
handling, set up a new Inbound route in the MailPace app points to Anymail's inbound webhook.

Use this url as the route's "forward" destination:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/mailpace/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

MailPace sends the Raw MIME message by default, and that is what Anymail uses to process the inbound email.

.. _mailpace-troubleshooting:

Troubleshooting
---------------

If Anymail's MailPace integration isn't behaving like you expect,
MailPace's dashboard includes information that can help
isolate the problem, for each Domain you have:

* MailPace Outbound Emails lists every email accepted by MailPace for delivery
* MailPace Webhooks page shows every attempt by MailPace to call
  your webhook
* MailPace Inbound page shows every inbound email received and every attempt 
  by MailPace to forward it to your Anymail inbound endpoint


See Anymail's :ref:`troubleshooting` docs for additional suggestions.
