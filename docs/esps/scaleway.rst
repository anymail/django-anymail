.. _scaleway-backend:

Scaleway TEM
============

.. versionadded:: 13.1

Anymail integrates with `Scaleway Transactional Email (TEM)`_ using
their `Transactional Email REST API <TEM_API_>`_.

.. _Scaleway Transactional Email (TEM):
    https://www.scaleway.com/en/transactional-email-tem/
.. _TEM_API:
    https://www.scaleway.com/en/developers/api/transactional-email/


Installation
------------

To use Anymail's Scaleway backend, set::

    EMAIL_BACKEND = "anymail.backends.scaleway.EmailBackend"

in your settings.py.

.. setting:: ANYMAIL_SCALEWAY_SECRET_KEY
.. setting:: ANYMAIL_SCALEWAY_PROJECT_ID

.. rubric:: SCALEWAY_SECRET_KEY and SCALEWAY_PROJECT_ID

A Scaleway API secret key and project ID are required:

.. code-block:: python

    ANYMAIL = {
        ...
        "SCALEWAY_SECRET_KEY": "<your API secret key>",
        "SCALEWAY_PROJECT_ID": "<your Project ID>",
    }

Projects are configured in Scaleway's console under Project Dashboard,
and API keys under Security & Identity > IAM. Anymail needs the "API *secret* key"
(not the "API *access* key").

For security, it's best to create a Scaleway IAM Application limited to the
permissions and projects needed for Anymail (or your Django app) rather using
an API key issued to your IAM user (which may have broad permissions on your
Scaleway account). Anymail requires only the TransactionalEmailEmailApiCreate
permission scoped to the given project ID.

Anymail will also look for ``SCALEWAY_SECRET_KEY`` at the root of the settings file
if neither ``ANYMAIL["SCALEWAY_SECRET_KEY"]`` nor ``ANYMAIL_SCALEWAY_SECRET_KEY``
is set. (The project ID must always be in the ``ANYMAIL`` settings dict.)


.. setting:: ANYMAIL_SCALEWAY_REGION

.. rubric:: SCALEWAY_REGION

The Scaleway region to use. The default is ``"fr-par"``. If Scaleway
provisions your TEM service in their Amsterdam region, you would need:

.. code-block:: python

    ANYMAIL = {
        ...
        "SCALEWAY_REGION": "nl-ams",
    }



.. setting:: ANYMAIL_SCALEWAY_API_URL

.. rubric:: SCALEWAY_API_URL

The base url for calling the Scaleway Transactional Email API. Use ``{region}``
to include the value of the :setting:`SCALEWAY_REGION <ANYMAIL_SCALEWAY_REGION>`
setting. Do not include the specific ``emails`` endpoint at the end.

The default is
``"https://api.scaleway.com/transactional-email/v1alpha1/regions/{region}/"``.
You may need to change this if Scaleway publishes a new API endpoint for
transactional email.


.. _scaleway-esp-extra:

esp_extra support
-----------------

To use Scaleway features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` that will be merged into the json sent to Scaleway's
`Send an email API`_.

For example, to use Scaleway's ``send_before`` option:

    .. code-block:: python

        message.esp_extra = {
            # merged into send params:
            "send_before": "2025-08-13T02:22:00Z",
        }


(You can also set `"esp_extra"` in Anymail's
:ref:`global send defaults <send-defaults>` to apply it to all
messages.)

.. _Send an email API:
    https://www.scaleway.com/en/developers/api/transactional-email/#path-emails-send-an-email


Limitations and quirks
----------------------

Scaleway does not support a few features offered by some other ESPs.
For a complete list of technical limitations, refer to the
`Scaleway Transactional Email API <TEM_API_>`_ documentation.

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using Anymail features that Scaleway doesn't
support. You can tell Anymail to suppress these errors and send the messages
anyway---see :ref:`unsupported-features`.

**Attachment limitations**
  Scaleway limits attachment types and sizes. Consult Scaleway's documentation
  for allowable options.

**No inline images**
  Scaleway's API does not offer support for inline images.

**Minimum content length**
  Scaleway rejects messages that have a subject, text or HTML body shorter than
  10 characters.

**Anymail tags and metadata are exposed to recipient**
  Anymail implements its normalized :attr:`~anymail.message.AnymailMessage.tags`
  and :attr:`~anymail.message.AnymailMessage.metadata` features for Scaleway
  using custom email headers. That means they can be visible to recipients
  via their email app's "show original message" (or similar) command.
  **Do not include sensitive data in tags or metadata.**

**No delayed sending**
  Scaleway does not support :attr:`~anymail.message.AnymailMessage.send_at`.

**No click-tracking or open-tracking options**
  Scaleway does not provide open or click tracking.
  Anymail's :attr:`~anymail.message.AnymailMessage.track_clicks` and
  :attr:`~anymail.message.AnymailMessage.track_opens` options are unsupported.

**No merge features**
  Scaleway does not support batch sending, so Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_headers`,
  :attr:`~anymail.message.AnymailMessage.merge_metadata`,
  and :attr:`~anymail.message.AnymailMessage.merge_data`
  are not supported.

**No envelope sender overrides**
  Scaleway does not support setting
  :attr:`~anymail.message.AnymailMessage.envelope_sender`.

**No non-ASCII mailboxes (EAI)**
  Scaleway incorrectly handles attempts to send from or to Unicode mailboxes
  (the *user* part of *user\@domain*---see :ref:`EAI <eai>`). The resulting
  message is lost or bounces internally within Scaleway's infrastructure,
  presumably due to incorrectly formatted header fields.

  To avoid this, Anymail raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
  error if you attempt to send a message using an EAI address with Scaleway.


.. _scaleway-templates:

Batch sending/merge and ESP templates
-------------------------------------

Scaleway does not support batch sending or ESP templates.


.. _scaleway-webhooks:

Status tracking webhooks
------------------------

Scaleway webhooks are currently in beta and not yet supported by Anymail.


.. _scaleway-inbound:

Inbound
-------

Scaleway does not currently offer inbound email.
