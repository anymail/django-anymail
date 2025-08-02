.. _scaleway-backend:

Scaleway
========

.. versionadded:: 13.1

.. _Scaleway: https://www.scaleway.com/en/
.. _Transactional Email API: https://www.scaleway.com/en/developers/api/transactional-email/
.. |Anymail feature| replace:: Anymail feature
.. |Anymail features| replace:: Anymail features
.. |Scaleway feature| replace:: Scaleway feature
.. |Scaleway features| replace:: Scaleway features

Anymail integrates with the `Scaleway`_ `Transactional Email API`_.

Installation
------------

To use Anymail's Scaleway backend, set::

    EMAIL_BACKEND = "anymail.backends.scaleway.EmailBackend"

in your settings.py.

**API keys**

Anymail requires your Scaleway secret key and Project ID.

.. setting:: ANYMAIL_SCALEWAY_SECRET_KEY

.. rubric:: SCALEWAY_SECRET_KEY

Your Scaleway secret key.

.. code-block:: python

    ANYMAIL = {
        ...
        "SCALEWAY_SECRET_KEY": "<your API key>",
    }

.. setting:: ANYMAIL_SCALEWAY_PROJECT_ID

.. rubric:: SCALEWAY_PROJECT_ID

Your Scaleway Project ID.

.. code-block:: python

    ANYMAIL = {
        ...
        "SCALEWAY_PROJECT_ID": "<your Project ID>",
    }

Anymail will also look for ``SCALEWAY_SECRET_KEY`` and ``SCALEWAY_PROJECT_ID`` at the
root of the settings file if neither ``ANYMAIL["SCALEWAY_SECRET_KEY"]``
nor ``ANYMAIL_SCALEWAY_SECRET_KEY`` is set.

**Other settings**

.. setting:: ANYMAIL_SCALEWAY_API_URL

.. rubric:: SCALEWAY_API_URL

The base url for calling the Scaleway API.

The default is ``SCALEWAY_API_URL = "https://api.scaleway.com/transactional-email/v1alpha1/regions/fr-par"``.
You may need to change this when Scaleway publishes a new API endpoint for Transactional Email.

.. setting:: ANYMAIL_SCALEWAY_REGION

.. rubric:: SCALEWAY_REGION

The Scaleway region to use. The default is `fr-par`.


.. _scaleway-esp-extra:

esp_extra support
-----------------

To use Scaleway features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` that will be merged into the json sent to Scaleway's
`email API`_.

Example:

    .. code-block:: python

        message.esp_extra = {
            'HypotheticalFutureScalewayParam': '2024',  # merged into send params
        }


(You can also set `"esp_extra"` in Anymail's
:ref:`global send defaults <send-defaults>` to apply it to all
messages.)

.. _email API: https://www.scaleway.com/en/developers/api/transactional-email/

.. _scaleway-features:

Supported features
------------------

Anymail supports these |Scaleway features| through the following |Anymail features|:

.. list-table::
    :header-rows: 1
    :widths: 25 25 50

    * - |Anymail feature|
      - |Scaleway feature|
      - Notes

    * - :attr:`~anymail.message.AnymailMessage.attachments`
      - ``attachments``
      - Binary attachments

    * - :attr:`~anymail.message.AnymailMessage.bcc`
      - ``bcc``
      - Blind carbon copy recipients

    * - :attr:`~anymail.message.AnymailMessage.cc`
      - ``cc``
      - Carbon copy recipients

    * - :attr:`~anymail.message.AnymailMessage.extra_headers`
      - ``additional_headers``
      - Custom email headers

    * - :attr:`~anymail.message.AnymailMessage.from_email`
      - ``from``
      - Sender email and name

    * - :attr:`~anymail.message.AnymailMessage.reply_to`
      - ``additional_headers``
      - Reply-To header

    * - :attr:`~anymail.message.AnymailMessage.subject`
      - ``subject``
      - Email subject line

    * - :attr:`~anymail.message.AnymailMessage.to`
      - ``to``
      - Primary recipients


Limitations and quirks
----------------------

Scaleway does not support a few features offered by some other ESPs.
For a complete list of technical limitations, refer to the `Scaleway Transactional Email API documentation`_.

Anymail normally raises an :exc:`~anymail.exceptions.AnymailUnsupportedFeature`
error when you try to send a message using features that Scaleway doesn't support.
You can tell Anymail to suppress these errors and send the messages anyway --
see :ref:`unsupported-features`.

**Attachment limitations**
  Scaleway limits attachment types to a predefined list (e.g., common document, image, and text formats).
  Attachment size is limited to 2MB.

**Minimum content length**
  The subject, body, and HTML content of your emails must each have at least 10 characters.

**No delayed sending**
  Scaleway does not support :attr:`~anymail.message.AnymailMessage.send_at`.

**Tags and Metadata**
  Scaleway does not have explicit support for tags or metadata. Anymail emulates
  support for :attr:`~anymail.message.AnymailMessage.tags` and
  :attr:`~anymail.message.AnymailMessage.metadata` by adding the data in
  custom ``X-Anymail-Tags`` and ``X-Anymail-Metadata`` headers.

**No click-tracking or open-tracking options**
  Scaleway does not provide a way to control open or click tracking for individual
  messages. Anymail's :attr:`~anymail.message.AnymailMessage.track_clicks` and
  :attr:`~anymail.message.AnymailMessage.track_opens` settings are unsupported.

**No merge features**
  Scaleway does not support batch sending, so Anymail's
  :attr:`~anymail.message.AnymailMessage.merge_headers`,
  :attr:`~anymail.message.AnymailMessage.merge_metadata`,
  and :attr:`~anymail.message.AnymailMessage.merge_data`
  are not supported.

**No envelope sender overrides**
  Scaleway does not support overriding :attr:`~anymail.message.AnymailMessage.envelope_sender`
  on individual messages.

.. _Scaleway Transactional Email API documentation: https://www.scaleway.com/en/developers/api/transactional-email/


Batch sending/merge and ESP templates
-------------------------------------

Scaleway does not support batch sending or ESP templates.


Inbound webhook
---------------

Scaleway does not currently offer inbound email.


.. _scaleway-webhooks:

Webhooks
--------

Scaleway webhooks are currently in beta and not yet supported by Anymail.
