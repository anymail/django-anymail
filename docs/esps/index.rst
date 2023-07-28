.. _supported-esps:

Supported ESPs
==============

Anymail currently supports these Email Service Providers.
Click an ESP's name for specific Anymail settings required,
and notes about any quirks or limitations:

.. these are listed in alphabetical order

.. toctree::
   :maxdepth: 1

   amazon_ses
   brevo
   mailersend
   mailgun
   mailjet
   mandrill
   postal
   postmark
   sendgrid
   sparkpost


Anymail feature support
-----------------------

The table below summarizes the Anymail features supported for each ESP.

.. currentmodule:: anymail.message

.. rst-class:: sticky-left

============================================  ============  =======  ============  ===========  ==========  ===========  ==========  ==========  ==========  ===========
Email Service Provider                        |Amazon SES|  |Brevo|  |MailerSend|  |Mailgun|    |Mailjet|   |Mandrill|   |Postal|    |Postmark|  |SendGrid|  |SparkPost|
============================================  ============  =======  ============  ===========  ==========  ===========  ==========  ==========  ==========  ===========
.. rubric:: :ref:`Anymail send options <anymail-send-options>`
------------------------------------------------------------------------------------------------------------------------------------------------------------------------
:attr:`~AnymailMessage.envelope_sender`       Yes           No       No            Domain only  Yes         Domain only  Yes         No          No          Yes
:attr:`~AnymailMessage.metadata`              Yes           Yes      No            Yes          Yes         Yes          No          Yes         Yes         Yes
:attr:`~AnymailMessage.merge_metadata`        No            No       No            Yes          Yes         Yes          No          Yes         Yes         Yes
:attr:`~AnymailMessage.send_at`               No            Yes      Yes           Yes          No          Yes          No          No          Yes         Yes
:attr:`~AnymailMessage.tags`                  Yes           Yes      Yes           Yes          Max 1 tag   Yes          Max 1 tag   Max 1 tag   Yes         Max 1 tag
:attr:`~AnymailMessage.track_clicks`          No            No       Yes           Yes          Yes         Yes          No          Yes         Yes         Yes
:attr:`~AnymailMessage.track_opens`           No            No       Yes           Yes          Yes         Yes          No          Yes         Yes         Yes
:ref:`amp-email`                              Yes           No       No            Yes          No          No           No          No          Yes         Yes

.. rubric:: :ref:`templates-and-merge`
------------------------------------------------------------------------------------------------------------------------------------------------------------------------
:attr:`~AnymailMessage.template_id`           Yes           Yes      Yes           Yes          Yes         Yes          No          Yes         Yes         Yes
:attr:`~AnymailMessage.merge_data`            Yes           No       Yes           Yes          Yes         Yes          No          Yes         Yes         Yes
:attr:`~AnymailMessage.merge_global_data`     Yes           Yes      (emulated)    (emulated)   Yes         Yes          No          Yes         Yes         Yes
.. rubric:: :ref:`Status <esp-send-status>` and :ref:`event tracking <event-tracking>`
------------------------------------------------------------------------------------------------------------------------------------------------------------------------
:attr:`~AnymailMessage.anymail_status`        Yes           Yes      Yes           Yes          Yes         Yes          Yes         Yes         Yes         Yes
|AnymailTrackingEvent| from webhooks          Yes           Yes      Yes           Yes          Yes         Yes          Yes         Yes         Yes         Yes
.. rubric:: :ref:`Inbound handling <inbound>`
------------------------------------------------------------------------------------------------------------------------------------------------------------------------
|AnymailInboundEvent| from webhooks           Yes           Yes      Yes           Yes          Yes         Yes          Yes         Yes         Yes         Yes
============================================  ============  =======  ============  ===========  ==========  ===========  ==========  ==========  ==========  ===========


Trying to choose an ESP? Please **don't** start with this table. It's far more
important to consider things like an ESP's deliverability stats, latency, uptime,
and support for developers. The *number* of extra features an ESP offers is almost
meaningless. (And even specific features don't matter if you don't plan to use them.)

.. |Amazon SES| replace:: :ref:`amazon-ses-backend`
.. |Brevo| replace:: :ref:`brevo-backend`
.. |MailerSend| replace:: :ref:`mailersend-backend`
.. |Mailgun| replace:: :ref:`mailgun-backend`
.. |Mailjet| replace:: :ref:`mailjet-backend`
.. |Mandrill| replace:: :ref:`mandrill-backend`
.. |Postal| replace:: :ref:`postal-backend`
.. |Postmark| replace:: :ref:`postmark-backend`
.. |SendGrid| replace:: :ref:`sendgrid-backend`
.. |SparkPost| replace:: :ref:`sparkpost-backend`
.. |AnymailTrackingEvent| replace:: :class:`~anymail.signals.AnymailTrackingEvent`
.. |AnymailInboundEvent| replace:: :class:`~anymail.signals.AnymailInboundEvent`


Other ESPs
----------

Don't see your favorite ESP here? Anymail is designed to be extensible.
You can suggest that Anymail add an ESP, or even contribute
your own implementation to Anymail. See :ref:`contributing`.
