.. _sendinblue-backend:

SendinBlue
========

Anymail integrates with the `SendinBlue`_ email service, using their `Web API v3`_.

.. important::

    **Troubleshooting:**
    If your SendinBlue messages aren't being delivered as expected, be sure to look for
    events in your SendinBlue `statistic panel`_.

    SendGrid detects certain types of errors only *after* the send API call appears
    to succeed, and reports these errors in the statistic panel.

.. _SendinBlue: https://www.sendinblue.com/
.. _Web API v3: https://developers.sendinblue.com/docs
.. _statistic panel: https://app-smtp.sendinblue.com/statistics


Settings
--------


.. rubric:: EMAIL_BACKEND

To use Anymail's SendinBlue backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.sendinblue.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_SENDINBLUE_API_KEY

.. rubric:: SENDINBLUE_API_KEY

The API key can be retrieved from the
`account settings`_. Make sure to get the
key for the version of the API you're
using..)
Required.

  .. code-block:: python

      ANYMAIL = {
          ...
          "SENDINBLUE_API_KEY": "<your API key>",
      }

Anymail will also look for ``SENDINBLUE_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["SENDINBLUE_API_KEY"]``
nor ``ANYMAIL_SENDINBLUE_API_KEY`` is set.

.. _account settings: https://account.sendinblue.com/advanced/api


Limitations and quirks
----------------------

**Single Reply-To**
  SendinBlue's v3 API only supports a single Reply-To address.

  If your message has multiple reply addresses, you'll get an
  :exc:`~anymail.exceptions.AnymailUnsupportedFeature` error---or
  if you've enabled :setting:`ANYMAIL_IGNORE_UNSUPPORTED_FEATURES`,
  Anymail will use only the first one.

**Attachment content-type**
  Attachment content-type is determined from the filename
  extension and you can't specify a different one. Trying
  to send an attachment without a name or a name without
  an extension generates an error with SendinBlue's API.

**Inline images**
  SendinBlue doesn't support inline images at all, it
  only support basic attachment.

**Email's display-names**
  Email's display-names are only supported
  **without** :attr:`template_id`. If you specify
  a :attr:`template_id` all display-names will be hidden.

**Template's limitation**
  If you use a template you will suffer some limitations:
  you can't change the subject or/and the body, and all email's
  display-names will be hidden.
