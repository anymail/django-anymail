.. _transient-errors:

Handling transient errors
=========================

Applications using Anymail need to be prepared to deal with connectivity issues
and other transient errors from your ESP's API (as with any networked API).

Because Django doesn't have a built-in way to say "try this again in a few moments,"
Anymail doesn't have its own logic to retry network errors. The best way to handle
transient ESP errors depends on your Django project:

* If you already use something like :pypi:`celery` or :pypi:`Django channels <channels>`
  for background task scheduling, that's usually the best choice for handling Anymail sends.
  Queue a task for every send, and wait to mark the task complete until the send succeeds
  (or repeatedly fails, according to whatever logic makes sense for your app).

* Another option is the Pinax :pypi:`django-mailer` package, which queues and automatically
  retries failed sends for any Django EmailBackend, including Anymail. django-mailer maintains
  its send queue in your regular Django DB, which is a simple way to get started but may not
  scale well for very large volumes of outbound email.

In addition to handling connectivity issues, either of these approaches also has the advantage
of moving email sending to a background thread. This is a best practice for sending email from
Django, as it allows your web views to respond faster.

Automatic retries
-----------------

Backends that use :pypi:`requests` for network calls can configure its built-in retry
functionality. Subclass the Anymail backend and mount instances of
:class:`~requests.adapters.HTTPAdapter` and :class:`~urllib3.util.Retry` configured with
your settings on the :class:`~requests.Session` object in `create_session()`.

Automatic retries aren't a substitute for sending emails in a background thread, they're
a way to simplify your retry logic within the worker. Be aware that retrying `read` and `other`
failures may result in sending duplicate emails. Requests will only attempt to retry idempotent
HTTP verbs by default, you may need to whitelist the verbs used by your backend's API in
`allowed_methods` to actually get any retries. It can also automatically retry error HTTP
status codes for you but you may need to configure `status_forcelist` with the error HTTP status
codes used by your backend provider.

   .. code-block:: python

      import anymail.backends.mandrill
      from django.conf import settings
      import requests.adapters


      class RetryableMandrillEmailBackend(anymail.backends.mandrill.EmailBackend):
          def __init__(self, *args, **kwargs):
              super().__init__(*args, **kwargs)
              retry = requests.adapters.Retry(
                  total=settings.EMAIL_TOTAL_RETRIES,
                  connect=settings.EMAIL_CONNECT_RETRIES,
                  read=settings.EMAIL_READ_RETRIES,
                  status=settings.EMAIL_HTTP_STATUS_RETRIES,
                  other=settings.EMAIL_OTHER_RETRIES,
                  allowed_methods=False,  # Retry all HTTP verbs
                  status_forcelist=settings.EMAIL_HTTP_STATUS_RETRYABLE,
                  backoff_factor=settings.EMAIL_RETRY_BACKOFF_FACTOR,
              )
              self.retryable_adapter = requests.adapters.HTTPAdapter(max_retries=retry)

          def create_session(self):
              session = super().create_session()
              session.mount("https://", self.retryable_adapter)
              return session
