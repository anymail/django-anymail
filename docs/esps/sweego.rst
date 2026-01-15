.. _sweego-backend:

Sweego
======

Anymail integrates Django with the `Sweego`_ transactional email service,
using their `send API`_ endpoint.

.. _Sweego: https://www.sweego.io/
.. _send API: https://learn.sweego.io/docs/sweego/send-send-post


.. _sweego-installation:

Installation
------------

You don't need any additional packages to use Anymail's Sweego backend.


Settings
--------

.. rubric:: EMAIL_BACKEND

To use Anymail's Sweego backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.sweego.EmailBackend"

in your settings.py.


.. setting:: ANYMAIL_SWEEGO_API_KEY

.. rubric:: SWEEGO_API_KEY

Required. Your Sweego API key:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SWEEGO_API_KEY": "<your API key>",
      }

Anymail will also look for ``SWEEGO_API_KEY`` at the
root of the settings file if neither ``ANYMAIL["SWEEGO_API_KEY"]``
nor ``ANYMAIL_SWEEGO_API_KEY`` is set.

You can retrieve your API key from your `Sweego dashboard`_.

.. _Sweego dashboard: https://app.sweego.io/


.. setting:: ANYMAIL_SWEEGO_CLIENT_UUID

.. rubric:: SWEEGO_CLIENT_UUID

Your Sweego client UUID. Required for :ref:`inbound attachment handling <sweego-inbound-attachments>`,
otherwise optional:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SWEEGO_CLIENT_UUID": "<your client UUID>",
      }

Anymail will also look for ``SWEEGO_CLIENT_UUID`` at the
root of the settings file if neither ``ANYMAIL["SWEEGO_CLIENT_UUID"]``
nor ``ANYMAIL_SWEEGO_CLIENT_UUID`` is set.

You can find your client UUID in your Sweego dashboard under Settings → API.


.. setting:: ANYMAIL_SWEEGO_API_URL

.. rubric:: SWEEGO_API_URL

The base url for calling the Sweego API.

The default is ``SWEEGO_API_URL = "https://api.sweego.io/"``.
(It's unlikely you would need to change this.)


.. setting:: ANYMAIL_SWEEGO_WEBHOOK_SECRET

.. rubric:: SWEEGO_WEBHOOK_SECRET

The Sweego webhook secret used to verify webhook signatures.
Recommended if you are using :ref:`status tracking <event-tracking>`, 
otherwise not necessary:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SWEEGO_WEBHOOK_SECRET": "<your webhook secret>",
      }

You can find your webhook secret in your Sweego webhook configuration.
See :ref:`sweego-webhooks` below for details.


.. _sweego-quirks:

Limitations and quirks
----------------------

Sweego is a full-featured transactional email service provider. Anymail's
Sweego backend supports most Anymail features.

**Single reply_to**
  Sweego's API only supports a single Reply-To address. If your message has
  multiple reply addresses, only the first one will be used.

**Tags format restriction**
  Anymail implements its normalized :attr:`~anymail.message.AnymailMessage.tags`
  using Sweego's ``campaign-tags`` field. Sweego accepts a maximum of 5 tags,
  and each tag must be 1-20 characters containing only alphanumeric characters
  and hyphens ``[A-Za-z0-9-]``. Tags that don't meet these requirements will
  cause an API error from Sweego.

**Metadata exposed to recipient**
  Anymail implements its normalized :attr:`~anymail.message.AnymailMessage.metadata`
  using custom email headers with ``X-Metadata-`` prefix. A maximum of 5 metadata
  items are supported. These headers can be visible to recipients via their
  email app's "show original message" (or similar) command. **Do not include
  sensitive data in metadata.**

**Tracking**
  Open and click tracking are enabled or disabled per sending domain in your
  Sweego account settings, not per message. Anymail does not provide
  :attr:`~anymail.message.AnymailMessage.track_opens` or
  :attr:`~anymail.message.AnymailMessage.track_clicks` attributes for
  controlling tracking on individual messages.

**No cc/bcc distinction**
  Sweego's API uses a single ``recipients`` array. The cc and bcc fields are
  merged with the to field. Each recipient receives an individual email.

**No inline attachments**
  Sweego's ``/send`` API doesn't support inline (embedded) images. Inline
  attachments are automatically converted to regular attachments.


.. _sweego-templates:

Batch sending/merge and ESP templates
--------------------------------------

Sweego supports :ref:`ESP stored templates <esp-stored-templates>` and
:ref:`batch sending <batch-send>` with per-recipient merge data.

Anymail automatically selects the appropriate Sweego API endpoint based on
the number of recipients:

Sweego supports :ref:`ESP stored templates <esp-stored-templates>` and
:ref:`batch sending <batch-send>` with per-recipient merge data.

Anymail automatically selects the appropriate Sweego API endpoint based on
the number of recipients:

* **Single recipient** (1 to address): Uses Sweego's ``/send`` endpoint
* **Multiple recipients** (2+ to addresses): Uses Sweego's ``/send/bulk/email`` endpoint

Both endpoints support templates and personalization variables, but handle them
slightly differently under the hood. Anymail abstracts these differences so you
can use the same code for both cases.


Single recipient with template
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When sending to a single recipient, you can use templates with personalization
variables:

.. code-block:: python

    from anymail.message import AnymailMessage

    message = AnymailMessage(
        from_email="sender@example.com",
        to=["alice@example.com"]
    )
    message.template_id = "welcome_template"  # Use this stored template
    message.merge_data = {
        'alice@example.com': {'name': "Alice", 'order_no': "12345"},
    }
    message.merge_global_data = {
        'company': "ExampleCo",
    }
    message.send()

With a single recipient, Anymail uses Sweego's ``/send`` endpoint and places
variables at the root level of the API request.


Batch sending to multiple recipients
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When sending to multiple recipients with personalized data, Anymail automatically
uses Sweego's ``/send/bulk/email`` endpoint, which supports per-recipient
personalization:

.. code-block:: python

    from anymail.message import AnymailMessage

    message = AnymailMessage(
        from_email="shipping@example.com",
        to=["alice@example.com", "bob@example.com", "charlie@example.com"]
    )
    message.template_id = "order_shipped"
    message.merge_data = {
        'alice@example.com': {'name': "Alice", 'order_no': "12345"},
        'bob@example.com': {'name': "Bob", 'order_no': "54321"},
        'charlie@example.com': {'name': "Charlie", 'order_no': "67890"},
    }
    message.merge_global_data = {
        'ship_date': "January 15, 2026",
        'company': "ExampleCo",
    }
    message.send()

With multiple recipients, Anymail uses the ``/send/bulk/email`` endpoint and
embeds variables within each recipient object. Each recipient receives their own
personalized email and sees **only their own email address** in the :mailheader:`To`
header—there's no exposure of other recipients.

Sweego does not natively support global merge data. Anymail emulates this by
copying :attr:`~anymail.message.AnymailMessage.merge_global_data` values to every
recipient automatically.


On-the-fly templates
~~~~~~~~~~~~~~~~~~~~

You can also define templates on-the-fly without using stored templates. Sweego
uses ``{{ variable_name }}`` syntax for personalization:

.. code-block:: python

    from django.core.mail import EmailMessage

    message = EmailMessage(
        from_email="shipping@example.com",
        subject="Your order {{ order_no }} has shipped",
        body="""Hi {{ name }},

We shipped your order {{ order_no }} on {{ ship_date }}.

Thanks,
{{ company }}""",
        to=["alice@example.com", "bob@example.com"]
    )
    # Set HTML version with same variables
    message.content_subtype = "html"  # or use EmailMultiAlternatives
    
    message.merge_data = {
        "alice@example.com": {"name": "Alice", "order_no": "12345"},
        "bob@example.com": {"name": "Bob", "order_no": "54321"},
    }
    message.merge_global_data = {
        "ship_date": "January 15",
        "company": "ExampleCo"
    }
    message.send()


Alternative: Loop over recipients
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Another approach to batch sending is to loop over your recipient list and send
a separate message to each. This gives you the most control and clearest error
handling:

.. code-block:: python

    from anymail.message import AnymailMessage
    from anymail.exceptions import AnymailAPIError

    recipients = [
        {"email": "alice@example.com", "name": "Alice", "order_no": "12345"},
        {"email": "bob@example.com", "name": "Bob", "order_no": "54321"},
        {"email": "charlie@example.com", "name": "Charlie", "order_no": "67890"},
    ]
    
    for recipient in recipients:
        message = AnymailMessage(
            to=[recipient["email"]],
            template_id="order_shipped",
            merge_global_data={
                "name": recipient["name"],
                "order_no": recipient["order_no"],
                "ship_date": "January 15, 2026",
                "company": "ExampleCo",
            },
            from_email="shipping@example.com",
        )
        try:
            message.send()
        except AnymailAPIError as e:
            # Handle error for this specific recipient
            # e.g., log error, schedule for retry
            print(f"Failed to send to {recipient['email']}: {e}")
        else:
            # Successfully queued for this recipient
            # You can store message.anymail_status.message_id for tracking
            print(f"Sent to {recipient['email']}: {message.anymail_status.message_id}")

This approach uses Sweego's ``/send`` endpoint for each recipient, providing:

* Immediate error handling per recipient
* Clear tracking with individual message IDs  
* Simple retry logic for failed sends
* No exposure of recipient lists to other recipients

See the `Sweego templates documentation`_ for more information.

.. _Sweego templates documentation:
    https://learn.sweego.io/docs/sending/templates


.. _sweego-webhooks:

Status tracking webhooks
------------------------

If you are using Anymail's normalized :ref:`status tracking <event-tracking>`,
add the url in your `Sweego webhook configuration`_:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/sweego/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Be sure to enter the URL in the "Tracking" section.

Sweego implements webhook signature validation, and Anymail verifies these
signatures against your :setting:`SWEEGO_WEBHOOK_SECRET <ANYMAIL_SWEEGO_WEBHOOK_SECRET>`
setting.

Sweego will report these Anymail :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s:
sent (email_sent), delivered, bounced (hard_bounce), deferred (soft-bounce),
complained (complaint), opened (email_opened), clicked (email_clicked),
unsubscribed (list_unsub).

The event's :attr:`~anymail.signals.AnymailTrackingEvent.esp_event` field will be
a `dict` of Sweego's webhook event data. (The keys are lowercase versions of the
Sweego webhook fields.)

.. _Sweego webhook configuration: https://app.sweego.io/webhooks


.. _sweego-inbound:

Inbound webhook
---------------

If you want to receive email from Sweego through Anymail's normalized
:ref:`inbound <inbound>` handling, follow Sweego's guide to
`configure Inbound Email Routing`_, pointing to Anymail's inbound webhook URL:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/sweego/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

Sweego's Inbound Email Routing feature allows you to receive emails on your
configured inbound domains and have them parsed into structured JSON and
delivered to your webhook endpoint.

**Setup steps:**

1. In your Sweego dashboard, go to the `Inbound Email section`_
2. Add an Inbound Email domain (a subdomain like ``inbound.yourdomain.com`` is recommended)
3. Create an MX record pointing to ``inbound.sweego.co`` with priority 10
4. Set your webhook URL to the Anymail inbound webhook URL above

.. note::

    The Inbound Email feature is available only for paying Sweego customers.
    A catch-all is configured by default, so any email sent to addresses
    on your inbound domain will be processed.

Sweego provides these normalized :class:`~anymail.inbound.AnymailInboundMessage`
fields:

* :attr:`~anymail.inbound.AnymailInboundMessage.from_email`
* :attr:`~anymail.inbound.AnymailInboundMessage.to`
* :attr:`~anymail.inbound.AnymailInboundMessage.cc`
* :attr:`~anymail.inbound.AnymailInboundMessage.subject`
* :attr:`~anymail.inbound.AnymailInboundMessage.text` (plain text body)
* :attr:`~anymail.inbound.AnymailInboundMessage.html` (HTML body, if present)
* :attr:`~anymail.inbound.AnymailInboundMessage.attachments`
* :attr:`~anymail.inbound.AnymailInboundMessage.envelope_sender`
* :attr:`~anymail.inbound.AnymailInboundMessage.envelope_recipient`

Sweego does not provide spam detection fields, so
:attr:`~anymail.inbound.AnymailInboundMessage.spam_detected` and
:attr:`~anymail.inbound.AnymailInboundMessage.spam_score` will be `None`.

The event's :attr:`~anymail.signals.AnymailInboundEvent.esp_event` field will be
a `dict` of the raw Sweego inbound webhook payload.


.. _sweego-inbound-attachments:

Inbound attachments with lazy loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 12.1

Sweego handles inbound email attachments differently from most ESPs. Instead of
including attachment content directly in the webhook payload, Sweego sends only
attachment **metadata** (UUID, filename, content type, size) and requires a
separate API call to fetch the actual content.

Anymail implements **lazy loading** for Sweego attachments: attachment content
is only fetched from Sweego's API when you actually access it, and the result
is cached for subsequent access.

**Additional configuration for attachments**

To enable attachment fetching, you must configure your Sweego client UUID
in addition to the API key:

  .. code-block:: python

      ANYMAIL = {
          ...
          "SWEEGO_API_KEY": "<your API key>",
          "SWEEGO_CLIENT_UUID": "<your client UUID>",  # Required for attachments
      }

You can find your client UUID in your Sweego dashboard under Settings → API.

**Without these credentials**, inbound emails will be processed normally but
:attr:`~anymail.inbound.AnymailInboundMessage.attachments` will be an empty list.

**How it works**

When a Sweego inbound webhook includes attachments, Anymail creates
``SweegoLazyAttachment`` objects that fetch content on demand:

.. code-block:: python

    from anymail.signals import inbound
    from django.dispatch import receiver

    @receiver(inbound)
    def handle_inbound(sender, event, esp_name, **kwargs):
        if esp_name != "Sweego":
            return
            
        message = event.message
        
        # Attachment metadata is immediately available (no API call)
        for attachment in message.attachments:
            filename = attachment.get_filename()  # No API call
            size = attachment.size  # No API call (from webhook metadata)
            content_type = attachment.get_content_type()  # No API call
            
            print(f"Attachment: {filename} ({content_type}, {size} bytes)")
            
            # Content is fetched only when accessed (triggers API call)
            content = attachment.get_content_bytes()
            
            # Subsequent access uses cached content (no additional API calls)
            content_again = attachment.get_content_bytes()

**Benefits of lazy loading:**

* **Faster webhook processing**: Smaller payloads mean quicker delivery
* **Bandwidth efficiency**: Only download attachments you actually need
* **Selective processing**: Check metadata before deciding to fetch content
* **Automatic caching**: Content is cached once fetched

**Error handling**

If fetching an attachment fails (network error, authentication failure, etc.),
an :exc:`~anymail.exceptions.AnymailAPIError` is raised when you access the content:

.. code-block:: python

    from anymail.exceptions import AnymailAPIError
    
    @receiver(inbound)
    def handle_inbound(sender, event, esp_name, **kwargs):
        if esp_name != "Sweego":
            return
            
        message = event.message
        
        for attachment in message.attachments:
            try:
                content = attachment.get_content_bytes()
                # Process attachment...
            except AnymailAPIError as e:
                # Handle fetch error gracefully
                print(f"Failed to fetch attachment: {e}")

**Best practices**

1. **Check attachment metadata** before fetching to skip large or unwanted files:

   .. code-block:: python

       for attachment in message.attachments:
           filename = attachment.get_filename()
           size = attachment.size
           
           # Skip large attachments
           if size > 10 * 1024 * 1024:  # 10 MB
               print(f"Skipping large attachment: {filename}")
               continue
           
           # Only fetch PDFs
           if filename.endswith('.pdf'):
               content = attachment.get_content_bytes()

2. **Save to persistent storage** early if you need to keep attachments:

   .. code-block:: python

       from django.core.files.base import ContentFile
       from django.core.files.storage import default_storage
       
       for attachment in message.attachments:
           try:
               content = attachment.get_content_bytes()
               path = default_storage.save(
                   f'attachments/{attachment.get_filename()}',
                   ContentFile(content)
               )
           except AnymailAPIError as e:
               print(f"Failed to save attachment: {e}")

3. **Handle errors gracefully** to avoid webhook failures when attachments can't be fetched.

**Under the hood**

When you access attachment content, Anymail makes a GET request to::

    GET https://api.sweego.io/clients/{client_uuid}/domains/inbound/attachments/{attachment_uuid}
    Headers:
      Api-Key: {your_api_key}
      Accept: application/octet-stream

The response contains the raw binary content, which is then cached in memory
for the lifetime of the attachment object.

**Complete example**

.. code-block:: python

    from anymail.signals import inbound
    from anymail.exceptions import AnymailAPIError
    from django.dispatch import receiver
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    @receiver(inbound)
    def handle_inbound(sender, event, esp_name, **kwargs):
        if esp_name != "Sweego":
            return
        
        message = event.message
        print(f"Received email from {message.envelope_sender}")
        print(f"Subject: {message['Subject']}")
        print(f"Body: {message.text}")
        
        # Process attachments with lazy loading
        for attachment in message.attachments:
            filename = attachment.get_filename()
            size = attachment.size
            content_type = attachment.get_content_type()
            
            print(f"\nAttachment: {filename}")
            print(f"  Type: {content_type}")
            print(f"  Size: {size} bytes")
            
            # Skip large files
            if size > 5 * 1024 * 1024:  # 5 MB limit
                print(f"  Skipped (too large)")
                continue
            
            # Fetch and save content
            try:
                content = attachment.get_content_bytes()
                path = default_storage.save(
                    f'inbound-attachments/{filename}',
                    ContentFile(content)
                )
                print(f"  Saved to: {path}")
            except AnymailAPIError as e:
                print(f"  Error fetching: {e}")

.. _configure Inbound Email Routing: https://www.sweego.io/product/new-inbound-email-routing
.. _Inbound Email section: https://app.sweego.io/home/inbound
