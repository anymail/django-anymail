.. _mailtrap-backend:

Mailtrap
========

Anymail integrates with `Mailtrap <https://mailtrap.io/>`_'s
transactional, bulk, or test email services, using the corresponding
`REST API`_.

.. note::

    By default, Anymail connects to Mailtrap's transactional API servers.
    If you are using Mailtrap's bulk send service, be sure to change the
    :setting:`MAILTRAP_API_URL <ANYMAIL_MAILTRAP_API_URL>` Anymail setting
    as shown below. Likewise, if you are using Mailtrap's test email service,
    be sure to set :setting:`MAILTRAP_TESTING_ENABLED <ANYMAIL_MAILTRAP_TESTING_ENABLED>`
    and :setting:`MAILTRAP_TEST_INBOX_ID <ANYMAIL_MAILTRAP_TEST_INBOX_ID>`.

.. _REST API: https://api-docs.mailtrap.io/docs/mailtrap-api-docs/


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Mailtrap backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.mailtrap.EmailBackend"

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


.. setting:: ANYMAIL_MAILTRAP_API_URL

.. rubric:: MAILTRAP_API_URL

The base url for calling the Mailtrap API.

The default is ``MAILTRAP_API_URL = "https://send.api.mailtrap.io/api"``, which connects
to Mailtrap's transactional service. You must change this if you are using Mailtrap's bulk
send service. For example, to use the bulk send service:

  .. code-block:: python

      ANYMAIL = {
        "MAILTRAP_API_TOKEN": "...",
        "MAILTRAP_API_URL": "https://bulk.api.mailtrap.io/api",
        # ...
      }


.. setting:: ANYMAIL_MAILTRAP_TESTING_ENABLED

.. rubric:: MAILTRAP_TESTING_ENABLED

Use Mailtrap's test email service by setting this to ``True``, and providing
:setting:`MAILTRAP_TEST_INBOX_ID <ANYMAIL_MAILTRAP_TEST_INBOX_ID>`:

  .. code-block:: python

      ANYMAIL = {
        "MAILTRAP_API_TOKEN": "...",
        "MAILTRAP_TESTING_ENABLED": True,
        "MAILTRAP_TEST_INBOX_ID": "<your test inbox id>",
        # ...
      }

By default, Anymail will switch to using Mailtrap's test email service API: ``https://sandbox.api.mailtrap.io/api``.

.. setting:: ANYMAIL_MAILTRAP_TEST_INBOX_ID

.. rubric:: MAILTRAP_TEST_INBOX_ID

Required if :setting:`MAILTRAP_TESTING_ENABLED <ANYMAIL_MAILTRAP_TESTING_ENABLED>` is ``True``.


.. _mailtrap-quirks:

Limitations and quirks
----------------------

**merge_metadata unsupported**
  Mailtrap supports :ref:`ESP stored templates <esp-stored-templates>`,
  but does NOT support per-recipient merge data via their :ref:`batch sending <batch-send>`
  service.


.. _mailtrap-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`, enter
the url in the Mailtrap webhooks config for your domain. (Note that Mailtrap's sandbox domain
does not trigger webhook events.)


.. _About Mailtrap webhooks: https://help.mailtrap.io/article/102-webhooks
.. _Mailtrap webhook payload: https://api-docs.mailtrap.io/docs/mailtrap-api-docs/016fe2a1efd5a-receive-events-json-format
