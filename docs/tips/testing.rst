.. _testing:

Testing your app
================

.. _test-backend:
.. _testing-sending:

Testing sending mail
--------------------

Django's documentation covers the basics of
:ref:`testing email sending in Django <django:topics-testing-email>`.
Everything in their examples will work with projects using Anymail.

Django's test runner makes sure your test cases don't actually send email,
by loading a dummy "locmem" EmailBackend that accumulates messages
in memory rather than sending them. You may not need anything more
complicated for verifying your app.

Anymail also includes its own "test" EmailBackend. This is intended primarily for
Anymail's internal testing, but you may find it useful for some of your test cases, too:

* Like Django's locmem EmailBackend, Anymail's test EmailBackend collects sent messages
  in :data:`django.core.mail.outbox`. Django clears the outbox automatically between test cases.

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

Note that :data:`django.core.mail.outbox` is an "outbox," not an attempt to represent end users'
*inboxes*. When using Django's default locmem EmailBackend, each outbox item represents a single
call to an SMTP server. With Anymail's test EmailBackend, each outbox item represents a single
call to an ESP's send API. (Anymail does not try to simulate how an ESP might further process
the message for that API call: Anymail can't render :ref:`esp-stored-templates`, and it keeps a
:ref:`batch send<batch-send>` message as a single outbox item, representing the single ESP API call
that will send multiple messages. You can check ``outbox[n].anymail_test_params['is_batch_send']``
to see if a message would fall under Anymail's batch send logic.)


.. _testing-webhooks:
.. _testing-tracking:

Testing tracking webhooks
-------------------------

If you are using Anymail's :ref:`event tracking webhooks <event-tracking>`,
you'll likely want to test your signal receiver code that processes those events.

One easy approach is to create a simulated :class:`~anymail.signals.AnymailTrackingEvent`
in your test case, then call :func:`anymail.signals.tracking.send` to deliver it to your
receiver function(s). Here's an example:

.. code-block:: python

    from anymail.signals import AnymailTrackingEvent, tracking
    from django.test import TestCase

    class EmailTrackingTests(TestCase):
        def test_delivered_event(self):
            # Build an AnymailTrackingEvent with event_type (required)
            # and any other attributes your receiver cares about. E.g.:
            event = AnymailTrackingEvent(
                event_type="delivered",
                recipient="to@example.com",
                message_id="test-message-id",
            )

            # Invoke all registered Anymail tracking signal receivers:
            tracking.send(sender=object(), event=event, esp_name="TestESP")

            # Verify expected behavior of your receiver. What to test here
            # depends on how your code handles the tracking events. E.g., if
            # you create a Django model to store the event, you might check:
            from myapp.models import MyTrackingModel
            self.assertTrue(MyTrackingModel.objects.filter(
                email="to@example.com", event="delivered",
                message_id="test-message-id",
            ).exists())

        def test_bounced_event(self):
            # ... as above, but with `event_type="bounced"`
            # etc.

This example uses Django's :meth:`Signal.send <django.dispatch.Signal.send>`,
so the test also verifies your receiver was registered properly, and it will
call multiple receiver functions if your code uses them.

Your test cases could instead import your tracking receiver function and call it
directly with the simulated event data. (Either approach is effective, and which
to use is largely a matter of personal taste.)


.. _testing-inbound:
.. _testing-receiving:

Testing receiving mail
----------------------

If your project handles :ref:`receiving inbound mail <inbound>`, you can test that with
an approach similar to the one used for event tracking webhooks above.

First build a simulated :class:`~anymail.signals.AnymailInboundEvent` containing
a simulated :class:`~anymail.inbound.AnymailInboundMessage`. Then dispatch
to your inbound receiver function(s) with :func:`anymail.signals.inbound.send`.
Like this:

.. code-block:: python

    from anymail.inbound import AnymailInboundMessage
    from anymail.signals import AnymailInboundEvent, inbound
    from django.test import TestCase

    class EmailReceivingTests(TestCase):
        def test_inbound_event(self):
            # Build a simple AnymailInboundMessage and AnymailInboundEvent
            # (see tips for more complex messages after the example):
            message = AnymailInboundMessage.construct(
                from_email="user@example.com", to="comments@example.net",
                subject="subject", text="text body", html="html body")
            event = AnymailInboundEvent(message=message)

            # Invoke all registered Anymail inbound signal receivers:
            inbound.send(sender=object(), event=event, esp_name="TestESP")

            # Verify expected behavior of your receiver. What to test here
            # depends on how your code handles the inbound message. E.g., if
            # you create a user comment from the message, you might check:
            from myapp.models import MyCommentModel
            comment = MyCommentModel.objects.get(poster="user@example.com")
            self.assertEqual(comment.text, "text body")

For examples of various ways to build an :class:`~anymail.inbound.AnymailInboundMessage`,
set headers, add attachments, etc., see `test_inbound.py`_ in Anymail's tests. In particular,
you may find ``AnymailInboundMessage.parse_raw_mime(str)`` or
``AnymailInboundMessage.parse_raw_mime_file(fp)`` useful for loading complex, real-world
email messages into test cases.

.. _test_inbound.py:
  https://github.com/anymail/django-anymail/blob/main/tests/test_inbound.py
