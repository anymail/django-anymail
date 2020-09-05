.. _test-backend:

Testing your app
================

Django's own test runner makes sure your
:ref:`test cases don't send email <django:topics-testing-email>`,
by loading a dummy EmailBackend that accumulates messages
in memory rather than sending them. That works just fine with Anymail.

Anymail also includes its own "test" EmailBackend. This is intended primarily for
Anymail's own internal tests, but you may find it useful for some of your test cases, too:

* Like Django's locmem EmailBackend, Anymail's test EmailBackend collects sent messages
  in :data:`django.core.mail.outbox`.
  Django clears the outbox automatically between test cases.
  See :ref:`email testing tools <django:topics-testing-email>` in the Django docs for more information.

* Unlike the locmem backend, Anymail's test backend processes the messages as though they
  would be sent by a generic ESP. This means every sent EmailMessage will end up with an
  :attr:`~anymail.message.AnymailMessage.anymail_status` attribute after sending,
  and some common problems like malformed addresses may be detected.
  (But no ESP-specific checks are run.)

* Anymail's test backend also adds an :attr:`anymail_test_params` attribute to each EmailMessage
  as it sends it. This is a dict of the actual params that would be used to send the message,
  including both Anymail-specific attributes from the EmailMessage and options that would
  come from Anymail settings defaults.

Here's an example:

.. code-block:: python

    from django.core import mail
    from django.test import TestCase
    from django.test.utils import override_settings

    @override_settings(EMAIL_BACKEND='anymail.backends.test.EmailBackend')
    class SignupTestCase(TestCase):
        # Assume our app has a signup view that accepts an email address...
        def test_sends_confirmation_email(self):
            self.client.post("/account/signup/", {"email": "user@example.com"})

            # Test that one message was sent:
            self.assertEqual(len(mail.outbox), 1)

            # Verify attributes of the EmailMessage that was sent:
            self.assertEqual(mail.outbox[0].to, ["user@example.com"])
            self.assertEqual(mail.outbox[0].tags, ["confirmation"])  # an Anymail custom attr

            # Or verify the Anymail params, including any merged settings defaults:
            self.assertTrue(mail.outbox[0].anymail_test_params["track_clicks"])
