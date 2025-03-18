.. _securing-webhooks:

Securing Webhooks
=================

Webhooks are a powerful way to receive event notifications from external services, but if not secured properly, they can expose your Django application to security vulnerabilities.

At a minimum, you should **use HTTPS** and a **shared authentication secret** for your Anymail webhooks. These practices apply to *any* webhook implementation, not just Anymail.

.. sidebar:: Why does this matter?

    Short answer: **Yes, it matters!**

    Webhooks function as APIs that your application exposes. If left unsecured, attackers can:

    * Collect your customers' email addresses.
    * Send fake bounces and spam reports, leading to blocked valid users.
    * Intercept email contents.
    * Spoof incoming mail to execute malicious commands in your app.
    * Flood your database with garbage data, impacting performance.

    Secure your webhooks to prevent these risks.

Use HTTPS
---------

Your Django application **must use HTTPS** to receive webhooks securely. The webhook URLs you provide to your ESP should always begin with `https://`.

Without HTTPS, webhook payloads travel unencrypted, exposing sensitive data like email addresses, message contents, and authentication secrets. This can lead to data leaks and potential account takeovers.

Setting up HTTPS is outside the scope of Anymail, but here are some helpful resources:

* Use `Let's Encrypt`_ for free SSL certificates.
* Many hosting providers offer built-in HTTPS support.
* Check web tutorials for configuring HTTPS on your web server.

If you **cannot** enable HTTPS on your Django site, you **should not** configure ESP webhooks.

.. _Let's Encrypt: https://letsencrypt.org/

.. setting:: ANYMAIL_WEBHOOK_SECRET

Use a Shared Authentication Secret
-----------------------------------

Since a webhook URL is a public endpoint, **anyone** can send requests to it. To ensure only your ESP can send valid webhook data, use a shared secret for authentication.

Most ESPs recommend **HTTP Basic Authentication** for securing webhooks. Anymail supports this via the :setting:`!ANYMAIL_WEBHOOK_SECRET` setting.

When configured, Anymail validates webhook requests using Basic Authentication. If a request lacks the correct credentials, Anymail raises an :exc:`AnymailWebhookValidationFailure` exception, preventing further processing. This exception is a subclass of Django's :exc:`~django.core.exceptions.SuspiciousOperation` and results in an HTTP 400 "Bad Request" response.

Here’s how to configure multiple authentication secrets for easy rotation:

.. code-block:: python

   ANYMAIL = {
       ...
       'WEBHOOK_SECRET': [
           'abcdefghijklmnop:qrstuvwxyz0123456789',
           'ZYXWVUTSRQPONMLK:JIHGFEDCBA9876543210',
       ],
   }

**Credential Rotation Steps:**
1. Add a new authentication string to the list and deploy your Django site.
2. Update the webhook URLs at your ESP to use the new authentication.
3. Remove the old authentication string after confirming all requests use the new one.

.. warning::

    If your webhook URLs don’t use HTTPS, your authentication secret could be exposed, rendering it useless.

Signed Webhooks
---------------

Some ESPs offer **signed webhooks**, which allow you to verify that the webhook payload was not tampered with in transit. Anymail supports signature verification for ESPs that provide this feature.

Check the documentation for your :ref:`specific ESP <supported-esps>` to configure webhook signing.

Even with signed webhooks, using a shared secret for authentication adds an extra layer of security.

Additional Security Measures
----------------------------

Beyond HTTPS and authentication secrets, consider these additional security steps:

* **Prevent Replay Attacks:** Track :attr:`~anymail.signals.AnymailTrackingEvent.event_id` to avoid processing duplicate events.
* **Validate Timestamps:** Ensure :attr:`~anymail.signals.AnymailTrackingEvent.timestamp` is recent to mitigate replay attacks.
* **Restrict Incoming Requests:** If your ESP provides a list of IP addresses, configure your firewall to accept requests only from those addresses.
* **Rate-Limit Requests:** Use web server rate-limiting or a tool like :pypi:`django-ratelimit` to prevent abuse.

### Testing Your Webhooks

To test your webhook security, you can use API request inspection tools such as:

* **[Beeceptor](https://beeceptor.com/)** – Create a custom endpoint to inspect webhook payloads before integrating them into your application.
* **[Typed Webhook](https://typedwebhook.tools/)** – A tool that helps validate and debug webhook requests with structured analysis.
