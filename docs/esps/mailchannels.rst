.. _mailchannels-backend:

MailChannels
============

Anymail integrates with the `MailChannels Email API`_ for sending mail.
It uses the `asynchronous send endpoint`_; tracking and inbound webhook
handlers are not implemented.

.. _MailChannels Email API: https://docs.mailchannels.com/email-api/
.. _asynchronous send endpoint:
    https://docs.mailchannels.com/api-reference/send/send-an-email-asynchronously

Installation
------------

Set your Django email backend and API key in settings.py::

    EMAIL_BACKEND = "anymail.backends.mailchannels.EmailBackend"
    ANYMAIL = {
        "MAILCHANNELS_API_KEY": "<your API key>",
    }

Read the API key from your application's secret store. Sending requires an
active MailChannels Email API account, an authorized sender domain, and
`Domain Lockdown`_ configuration. Enabling open or click tracking also requires
an eligible subscription.

.. _Domain Lockdown: https://docs.mailchannels.com/email-api/domain-lockdown

.. setting:: ANYMAIL_MAILCHANNELS_API_KEY

.. rubric:: MAILCHANNELS_API_KEY

Required for sending. Anymail also looks for ``MAILCHANNELS_API_KEY`` at the
root of your settings if neither ``ANYMAIL["MAILCHANNELS_API_KEY"]`` nor
``ANYMAIL_MAILCHANNELS_API_KEY`` is set. You can pass ``api_key`` directly to
the backend constructor instead.

.. setting:: ANYMAIL_MAILCHANNELS_API_URL

.. rubric:: MAILCHANNELS_API_URL

The base API URL, defaulting to ``"https://api.mailchannels.net/tx/v1/"``.
Do not include ``send-async``. You can pass ``api_url`` directly to the backend
constructor. The normal Anymail :setting:`ANYMAIL_REQUESTS_TIMEOUT` applies.

Sending behavior
----------------

Django's standard sending APIs work with this backend, including
``send_mail``, ``send_mass_mail``, ``EmailMessage``, ``EmailMultiAlternatives``,
reusable connections, display names, To/Cc/Bcc, a single Reply-To address,
text and HTML content, custom headers, and ordinary and inline attachments.
Attachment sizes, recipient limits, and other API policy limits are enforced
by MailChannels, not by this backend.

A successful send reports ``queued`` for every intended recipient and uses
MailChannels' ``request_id`` as :attr:`~anymail.message.AnymailStatus.message_id`.
This ID identifies the whole API request, including all personalizations.
It is not the RFC Message-ID header and is not unique per recipient. HTTP 202
means the request was queued; it does not prove per-recipient validation,
rendering, Domain Lockdown authorization, or delivery. Inspect MailChannels'
events and received messages for those outcomes.

API errors, malformed queue responses, and transport failures raise
:exc:`~anymail.exceptions.AnymailAPIError`. The backend does not retry sends.
A timeout can leave acceptance uncertain; retrying may duplicate mail.
Django's ``fail_silently`` behavior and Anymail's usual connection cleanup apply.

Templates and batch sending
---------------------------

MailChannels renders inline Mustache templates. Set
:attr:`~anymail.message.AnymailMessage.merge_global_data` and/or
:attr:`~anymail.message.AnymailMessage.merge_data` to enable Mustache rendering
of text and HTML content. Per-recipient values override global values::

    from anymail.message import AnymailMessage

    message = AnymailMessage(
        subject="Account update",
        body="Hello {{name}}",
        from_email="support@example.com",
        to=["alice@example.com", "bob@example.com"],
        merge_global_data={"name": "customer"},
        merge_data={"alice@example.com": {"name": "Alice"}},
    )
    message.send()

Setting ``merge_data`` (even ``{}``) or ``merge_headers`` makes a separate
personalization for each To recipient. Each retains the original Cc/Bcc list,
so those recipients receive a copy of every personalization. Global data alone
does not split the To list. ``merge_headers`` overrides root custom headers
per recipient according to MailChannels' case-insensitive header precedence.

Subject templating and stored ``template_id`` templates are not supported.

esp_extra support
-----------------

Use :attr:`~anymail.message.AnymailMessage.esp_extra` for MailChannels-specific
send options such as campaign IDs, DKIM settings, non-transactional mail, and
custom tracking domains::

    message.esp_extra = {
        "campaign_id": "account-update",
        "tracking_settings": {
            "click_tracking": {"custom_domain_name": "clicks"},
        },
    }

The dictionary is deeply merged into the request after Anymail's normalized
options. Lists replace generated lists, including ``personalizations``.
When replacing recipients through this escape hatch, the normalized recipient
status still describes the original Django recipients. Prefer normal ``to``,
``cc``, ``bcc``, and merge options when you need accurate recipient status.
You are responsible for the API's restrictions and any overridden values.

Limitations
-----------

* Each message needs at least one To recipient. Cc-only or Bcc-only messages
  cannot preserve their visible recipient semantics in this API.
* Only one Reply-To address is supported.
* MailChannels reserves certain headers, including Message-ID, To, Cc, Bcc,
  Subject, Content-Type, DKIM-Signature, and Received. These cannot be supplied
  as custom headers. Anymail maps From and Reply-To overrides to native API
  fields and rejects spoofed To headers. See the API reference for the full list.
* ``envelope_sender`` maps to ``envelope_from`` (the display name is ignored).
* ``track_clicks`` and ``track_opens`` map to the corresponding
  ``tracking_settings`` flags. Account eligibility still applies.
* Anymail ``metadata``, ``merge_metadata``, ``tags``, ``send_at``, AMP content,
  stored templates, and alternative bodies other than text/plain and text/html
  are unsupported. Metadata is not silently sent as visible recipient headers.
* Inline attachments need a Content-ID; normal attachments with a Content-ID
  remain normal attachments. MailChannels chooses inline disposition from its
  ``content_id`` field.
* Anymail tracking and inbound webhook handlers are not available.

Unsupported features raise
:exc:`~anymail.exceptions.AnymailUnsupportedFeature` unless you explicitly
configure :ref:`unsupported-features` to ignore them.
