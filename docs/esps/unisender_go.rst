.. _unisender-backend:

Unisender Go
=============

Anymail integrates with the `Unisender Go`_ email service, using their API.

Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Unisender Go backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.unisender_go.EmailBackend"

in your settings.py.

.. rubric:: UNISENDER_GO_API_KEY

.. setting:: ANYMAIL_UNISENDER_GO_API_KEY

Unisender Go API key

  .. code-block:: python

      ANYMAIL = {
          ...
          "UNISENDER_GO_API_KEY": "<your API key>",
      }

Anymail will also look for ``UNISENDER_GO_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["UNISENDER_GO_API_KEY"]``
nor ``ANYMAIL_UNISENDER_GO_API_KEY`` is set.

.. setting:: ANYMAIL_UNISENDER_GO_API_URL

.. rubric:: UNISENDER_GO_API_URL

`Unisender GO API endpoint`_ to use. It can depend on server location.

  .. code-block:: python

      ANYMAIL = {
          ...
          "UNISENDER_GO_API_URL": "https://go1.unisender.ru/ru/transactional/api/v1/",  # use Unisender Go RU
      }

You must specify the full, versioned API endpoint as shown above (not just the base_uri).

.. _Unisender GO API Endpoint: https://godocs.unisender.ru/web-api-ref#web-api

Limitations and quirks
----------------------

**Anymail's `message_id` is set in metadata**
  Unisender sets message_id and returns it in the response on request.
  Anyway, for usability we set it in metadata and take from metadata in webhooks.

  If you need campaing_id you have to add it in metadata too.

**skip_unsubscribe option**
  By default, Unisender Go add in the end of email link to unsubscribe.
  If you want to avoid it, you have to ask tech support to enable this option for you.
  Then you should set it in settings, like this.
  For flexibility, you can set it in "esp_extra" arg in backend.

  .. code-block:: python

    ANYMAIL_UNISENDER_GO_SKIP_UNSUBSCRIBE = True

**global_language option**
  Language for link language and unsubscribe page.
  Options: 'be', 'de', 'en', 'es', 'fr', 'it', 'pl', 'pt', 'ru', 'ua', 'kz'.

  .. code-block:: python

    ANYMAIL_UNISENDER_GO_GLOBAL_LANGUAGE = 'en'

.. _unisender-templates:

ESP templates
-------------------------------------
In Unisender Go you can send email with templates. You just create it and set as `template_id='...'`.
Also you can choose simple template with just `{{ x }}` substitutions or velocity templates with loops, arrays, etc.
You will have to put merge data to put it in template gaps. For example:

  .. code-block:: python

    YourEmailClass(
        template_id=email_template_id,
        subject=SUBJECT,
        to=[email_1, email_2],
        merge_data={email_1: 'name_1', email_2: 'name_2'},
        merge_global_data={'common_var': 'some_value'},
    )

.. _unisender-webhooks:

Status tracking webhooks
------------------------

* Target URL: :samp:`https://{yoursite.example.com}/anymail/unisender_go/tracking/`

Unisender Go provides two event types. They differ with event_name and event_data.

`transactional_email_status` - event of email delivery status change.
You can specify, which statuses you want to be notified of.

`transactional_spam_block` - event of block or unblock of service's SMTP-servers by user's services.
On current time is not supported by this lib.

You may need to know, how webhooks auth works.
They hash the whole request body text and replace api key in "auth" field by this hash.
So it is both auth and encryption. Also, they hash JSON without spaces and without double quoters.

You also may want to know, what exactly lays in webhook api callback.

  .. code-block:: python

      {
        "auth":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "events_by_user":
          [
            {
              "user_id":456,
              "project_id":"6432890213745872",
              "project_name":"MyProject",
              "events":
              [
                {
                  "event_name":"transactional_email_status",
                  "event_data":
                  {
                    "job_id":"1a3Q2V-0000OZ-S0",
                    "metadata":
                    {
                      "key1":"val1",
                      "key2":"val2"
                    },
                    "email":"recipient.email@example.com",
                    "status":"sent",
                    "event_time":"2015-11-30 15:09:42",
                    "url":"http://some.url.com",
                    "delivery_info":
                    {
                      "delivery_status": "err_delivery_failed",
                      "destination_response": "550 Spam rejected",
                      "user_agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36",
                      "ip":"111.111.111.111"
                    }
                  }
                },
                {
                  "event_name":"transactional_spam_block",
                  "event_data":
                  {
                    "block_time":"YYYY-MM-DD HH:MM:SS",
                    "block_type":"one_smtp",
                    "domain":"domain_name",
                    "SMTP_blocks_count":8,
                    "domain_status":"blocked"
                  }
                }
              ]
            }
          ]
      }

.. _unisender-inbound:

Inbound webhook
---------------

There is no such webhooks' type in Unisender Go.
