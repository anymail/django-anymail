.. module:: anymail.signals

.. _event-tracking:

Tracking sent mail status
=========================

Anymail provides normalized handling for your ESP's event-tracking webhooks.
You can use this to be notified when sent messages have been delivered,
bounced, been opened or had links clicked, among other things.

Webhook support is optional. If you haven't yet, you'll need to
:ref:`configure webhooks <webhooks-configuration>` in your Django
project. (You may also want to review :ref:`securing-webhooks`.)

Once you've enabled webhooks, Anymail will send an ``anymail.signals.tracking``
custom Django :doc:`signal <django:topics/signals>` for each ESP tracking event it receives.
You can connect your own receiver function to this signal for further processing.

Be sure to read Django's `listening to signals`_ docs for information on defining
and connecting signal receivers.

Example:

.. code-block:: python

    from anymail.signals import tracking
    from django.dispatch import receiver

    @receiver(tracking)  # add weak=False if inside some other function/class
    def handle_bounce(sender, event, esp_name, **kwargs):
        if event.event_type == 'bounced':
            print("Message %s to %s bounced" % (
                  event.message_id, event.recipient))

    @receiver(tracking)
    def handle_click(sender, event, esp_name, **kwargs):
        if event.event_type == 'clicked':
            print("Recipient %s clicked url %s" % (
                  event.recipient, event.click_url))

You can define individual signal receivers, or create one big one for all
event types, whichever you prefer. You can even handle the same event
in multiple receivers, if that makes your code cleaner. These
:ref:`signal receiver functions <signal-receivers>` are documented
in more detail below.

Note that your tracking signal receiver(s) will be called for all tracking
webhook types you've enabled at your ESP, so you should always check the
:attr:`~AnymailTrackingEvent.event_type` as shown in the examples above
to ensure you're processing the expected events.

Some ESPs batch up multiple events into a single webhook call. Anymail will
invoke your signal receiver once, separately, for each event in the batch.


Normalized tracking event
-------------------------

.. class:: AnymailTrackingEvent

    The `event` parameter to Anymail's `tracking`
    :ref:`signal receiver <signal-receivers>`
    is an object with the following attributes:

    .. attribute:: event_type

        A normalized `str` identifying the type of tracking event.

        .. note::

            Most ESPs will send some, but *not all* of these event types.
            Check the :ref:`specific ESP <supported-esps>` docs for more
            details. In particular, very few ESPs implement the "sent" and
            "delivered" events.

        One of:

          * `'queued'`: the ESP has accepted the message
            and will try to send it (possibly at a later time).
          * `'sent'`: the ESP has sent the message
            (though it may or may not get successfully delivered).
          * `'rejected'`: the ESP refused to send the messsage
            (e.g., because of a suppression list, ESP policy, or invalid email).
            Additional info may be in :attr:`reject_reason`.
          * `'failed'`: the ESP was unable to send the message
            (e.g., because of an error rendering an ESP template)
          * `'bounced'`: the message was rejected or blocked by receiving MTA
            (message transfer agent---the receiving mail server).
          * `'deferred'`: the message was delayed by in transit
            (e.g., because of a transient DNS problem, a full mailbox, or
            certain spam-detection strategies).
            The ESP will keep trying to deliver the message, and should generate
            a separate `'bounced'` event if later it gives up.
          * `'delivered'`: the message was accepted by the receiving MTA.
            (This does not guarantee the user will see it. For example, it might
            still be classified as spam.)
          * `'autoresponded'`: a robot sent an automatic reply, such as a vacation
            notice, or a request to prove you're a human.
          * `'opened'`: the user opened the message (used with your ESP's
            :attr:`~anymail.message.AnymailMessage.track_opens` feature).
          * `'clicked'`: the user clicked a link in the message (used with your ESP's
            :attr:`~anymail.message.AnymailMessage.track_clicks` feature).
          * `'complained'`: the recipient reported the message as spam.
          * `'unsubscribed'`: the recipient attempted to unsubscribe
            (when you are using your ESP's subscription management features).
          * `'subscribed'`: the recipient attempted to subscribe to a list,
            or undo an earlier unsubscribe (when you are using your ESP's
            subscription management features).
          * `'unknown'`: anything else. Anymail isn't able to normalize this event,
            and you'll need to examine the raw :attr:`esp_event` data.

    .. attribute:: message_id

        A `str` unique identifier for the message, matching the
        :attr:`message.anymail_status.message_id <anymail.message.AnymailStatus.message_id>`
        attribute from when the message was sent.

        The exact format of the string varies by ESP. (It may or may not be
        an actual "Message-ID", and is often some sort of UUID.)

    .. attribute:: timestamp

        A `~datetime.datetime` indicating when the event was generated.
        (The timezone is often UTC, but the exact behavior depends on your ESP and
        account settings. Anymail ensures that this value is an *aware* datetime
        with an accurate timezone.)

    .. attribute:: event_id

        A `str` unique identifier for the event, if available; otherwise `None`.
        Can be used to avoid processing the same event twice. Exact format varies
        by ESP, and not all ESPs provide an event_id for all event types.

    .. attribute:: recipient

        The `str` email address of the recipient. (Just the "recipient\@example.com"
        portion.)

    .. attribute:: metadata

        A `dict` of unique data attached to the message. Will be empty if the ESP
        doesn't provide metadata with its tracking events.
        (See :attr:`AnymailMessage.metadata <anymail.message.AnymailMessage.metadata>`.)

    .. attribute:: tags

        A `list` of `str` tags attached to the message. Will be empty if the ESP
        doesn't provide tags with its tracking events.
        (See :attr:`AnymailMessage.tags <anymail.message.AnymailMessage.tags>`.)

    .. attribute:: reject_reason

        For `'bounced'` and `'rejected'` events, a normalized `str` giving the reason
        for the bounce/rejection. Otherwise `None`. One of:

          * `'invalid'`: bad email address format.
          * `'bounced'`: bounced recipient. (In a `'rejected'` event, indicates the
            recipient is on your ESP's prior-bounces suppression list.)
          * `'timed_out'`: your ESP is giving up after repeated transient
            delivery failures (which may have shown up as `'deferred'` events).
          * `'blocked'`: your ESP's policy prohibits this recipient.
          * `'spam'`: the receiving MTA or recipient determined the message is spam.
            (In a `'rejected'` event, indicates the recipient is on your ESP's
            prior-spam-complaints suppression list.)
          * `'unsubscribed'`: the recipient is in your ESP's unsubscribed
            suppression list.
          * `'other'`: some other reject reason; examine the raw :attr:`esp_event`.
          * `None`: Anymail isn't able to normalize a reject/bounce reason for
            this ESP.

        .. note::

            Not all ESPs provide all reject reasons, and this area is often
            under-documented by the ESP. Anymail does its best to interpret
            the ESP event, but you may find that it will report
            `'timed_out'` for one ESP, and `'bounced'` for another, sending
            to the same non-existent mailbox.

            We appreciate :ref:`bug reports <reporting-bugs>` with the raw
            :attr:`esp_event` data in cases where Anymail is getting it wrong.

    .. attribute:: description

        If available, a `str` with a (usually) human-readable description of the event.
        Otherwise `None`. For example, might explain why an email has bounced. Exact
        format varies by ESP (and sometimes event type).

    .. attribute:: mta_response

        If available, a `str` with a raw (intended for email administrators) response
        from the receiving mail transfer agent. Otherwise `None`. Often includes SMTP
        response codes, but the exact format varies by ESP (and sometimes receiving MTA).

    .. attribute:: user_agent

        For `'opened'` and `'clicked'` events, a `str` identifying the browser and/or
        email client the user is using, if available. Otherwise `None`.

    .. attribute:: click_url

        For `'clicked'` events, the `str` url the user clicked. Otherwise `None`.

    .. attribute:: esp_event

        The "raw" event data from the ESP, deserialized into a Python data structure.
        For most ESPs this is either parsed JSON (as a `dict`), or HTTP POST fields
        (as a Django :class:`~django.http.QueryDict`).

        This gives you (non-portable) access to additional information provided by
        your ESP. For example, some ESPs include geo-IP location information with
        open and click events.


.. _signal-receivers:

Signal receiver functions
-------------------------

Your Anymail signal receiver must be a function with this signature:

.. function:: def my_handler(sender, event, esp_name, **kwargs):

   (You can name it anything you want.)

   :param class sender: The source of the event. (One of the
                        :mod:`anymail.webhook.*` View classes, but you
                        generally won't examine this parameter; it's
                        required by Django's signal mechanism.)
   :param AnymailTrackingEvent event: The normalized tracking event.
                                      Almost anything you'd be interested in
                                      will be in here.
   :param str esp_name: e.g., "Mailtrap" or "Postmark". If you are working
                        with multiple ESPs, you can use this to distinguish
                        ESP-specific handling in your shared event processing.
   :param \**kwargs: Required by Django's signal mechanism
                     (to support future extensions).

   :returns: nothing
   :raises: any exceptions in your signal receiver will result
            in a 400 HTTP error to the webhook. See discussion
            below.

If any of your signal receivers raise an exception, Anymail
will discontinue processing the current batch of events and return
an HTTP 400 error to the ESP. Most ESPs respond to this by re-sending
the event(s) later, a limited number of times.

This is the desired behavior for transient problems (e.g., your
Django database being unavailable), but can cause confusion in other
error cases. You may want to catch some (or all) exceptions
in your signal receiver, log the problem for later follow up,
and allow Anymail to return the normal 200 success response
to your ESP.

Some ESPs impose strict time limits on webhooks, and will consider
them failed if they don't respond within (say) five seconds.
And will retry sending the "failed" events, which could cause duplicate
processing in your code.
If your signal receiver code might be slow, you should instead
queue the event for later, asynchronous processing (e.g., using
something like :pypi:`celery`).

If your signal receiver function is defined within some other
function or instance method, you *must* use the `weak=False`
option when connecting it. Otherwise, it might seem to work at first,
but will unpredictably stop being called at some point---typically
on your production server, in a hard-to-debug way. See Django's
`listening to signals`_ docs for more information.

.. _listening to signals:
    https://docs.djangoproject.com/en/stable/topics/signals/#listening-to-signals
