.. _mailtrap-backend:

Mailtrap
========

Anymail integrates with `Mailtrap <https://mailtrap.io/>`_'s
transactional or test (sandbox) email services, using the
`Mailtrap REST API v2`_.

.. _Mailtrap REST API v2: https://api-docs.mailtrap.io/docs/mailtrap-api-docs/


Settings
--------

To use Anymail's Mailtrap backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailtrap.EmailBackend"
      ANYMAIL = {
          "MAILTRAP_API_TOKEN": "<your API token>",
          # Optional, to use the sandbox API:
          "MAILTRAP_TEST_INBOX_ID": <your test inbox id>,
      }

in your settings.py.


.. setting:: ANYMAIL_MAILTRAP_API_TOKEN

.. rubric:: MAILTRAP_API_TOKEN

Required for sending:

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILTRAP_API_TOKEN": "<your API token>",
      }

Anymail will also look for ``MAILTRAP_API_TOKEN`` at the
root of the settings file if neither ``ANYMAIL["MAILTRAP_API_TOKEN"]``
nor ``ANYMAIL_MAILTRAP_API_TOKEN`` is set.


.. setting:: ANYMAIL_MAILTRAP_TEST_INBOX_ID

.. rubric:: MAILTRAP_TEST_INBOX_ID

Required to use Mailtrap's test inbox. (If not provided, emails will be sent
using Mailbox's transactional API.)

  .. code-block:: python

      ANYMAIL = {
          ...
          "MAILTRAP_TEST_INBOX_ID": 12345,
      }


.. setting:: ANYMAIL_MAILTRAP_API_URL

.. rubric:: MAILTRAP_API_URL

The base url for calling the Mailtrap API.

The default is ``MAILTRAP_API_URL = "https://send.api.mailtrap.io/api/"``
(Mailtrap's transactional service)
if :setting:`MAILTRAP_TEST_INBOX_ID <ANYMAIL_MAILTRAP_TEST_INBOX_ID>` is not set,
or ``"https://sandbox.api.mailtrap.io/api/"`` (Mailbox's sandbox testing service)
when a test inbox id is provided.

Most users should not need to change this setting. However, you could set it
to use Mailtrap's bulk send service:

  .. code-block:: python

      ANYMAIL = {
        ...
        "MAILTRAP_API_URL": "https://bulk.api.mailtrap.io/api/",
      }

(Note that Anymail has not been tested for use with Mailtrap's bulk API.)

The value must be only the API base URL: do not include the ``"/send"`` endpoint
or your test inbox id.



.. _mailtrap-quirks:

Limitations and quirks
----------------------

**merge_data and merge_metadata not yet supported**
  Mailtrap supports :ref:`ESP stored templates <esp-stored-templates>`,
  but Anymail does not yet support per-recipient merge data with their
  batch sending APIs.


.. _mailtrap-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, enter
the url in the Mailtrap webhooks config for your domain. (Note that Mailtrap's sandbox domain
does not trigger webhook events.)


.. _About Mailtrap webhooks: https://help.mailtrap.io/article/102-webhooks
.. _Mailtrap webhook payload: https://api-docs.mailtrap.io/docs/mailtrap-api-docs/016fe2a1efd5a-receive-events-json-format
