Changelog
=========

Anymail releases follow `semantic versioning <semver>`_.
Among other things, this means that minor updates (1.x to 1.y)
should always be backwards-compatible, and breaking changes will
always increment the major version number (1.x to 2.0).

.. _semver: http://semver.org


..  This changelog is designed to be readable standalone on GitHub,
    as well as included in the Sphinx docs. Do *not* use Sphinx
    references; links into the docs must use absolute urls to
    https://anymail.readthedocs.io/ (generally to en/stable/, though
    linking to a specific older version may be appropriate for features
    that have been retired).

..  You can use docutils 1.0 markup, but *not* any Sphinx additions.
    GitHub rst supports code-block, but *no other* block directives.

.. default-role:: literal

Release history
^^^^^^^^^^^^^^^
    ..  This extra heading level keeps the ToC from becoming unmanageably long

vNext
-----

*Unreleased changes*

Fixes
~~~~~

* **SparkPost:** Drop support for multiple `from_email` addresses. SparkPost has
  started issuing a cryptic "No sending domain specified" error for this case; with
  this fix, Anymail will now treat it as an unsupported feature.

Other
~~~~~

* Move CI testing to GitHub Actions (and stop using Travis-CI).



v8.1
----

*2020-10-09*

Features
~~~~~~~~

* **SparkPost:** Add option for event tracking webhooks to map SparkPost's "Initial Open"
  event to Anymail's normalized "opened" type. (By default, only SparkPost's "Open" is
  reported as Anymail "opened", and "Initial Open" maps to "unknown" to avoid duplicates.
  See `docs <https://anymail.readthedocs.io/en/stable/esps/sparkpost/#sparkpost-webhooks>`__.
  Thanks to `@slinkymanbyday`_.)

* **SparkPost:** In event tracking webhooks, map AMP open and click events to the
  corresponding Anymail normalized event types. (Previously these were treated as
  as "unknown" events.)


v8.0
----

*2020-09-11*

Breaking changes
~~~~~~~~~~~~~~~~

* Require **Django 2.0 or later** and Python 3. (For compatibility with Django 1.11 and
  Python 2.7, stay on the Anymail `v7.2 LTS`_ extended support branch by setting your
  requirements to `django-anymail~=7.2`.)

* **Mailjet:** Upgrade to Mailjet's newer v3.1 send API. Most Mailjet users will not
  be affected by this change, with two exceptions: (1) Mailjet's v3.1 API does not allow
  multiple reply-to addresses, and (2) if you are using Anymail's `esp_extra`, you will
  need to update it for compatibility with the new API. (See
  `docs <https://anymail.readthedocs.io/en/stable/esps/mailjet/#esp-extra-support>`__.)

* **SparkPost:** Call the SparkPost API directly, without using the (now unmaintained)
  Python SparkPost client library. The "sparkpost" package is no longer necessary and
  can be removed from your project requirements. Most SparkPost users will not be
  affected by this change, with two exceptions: (1) You must provide a
  ``SPARKPOST_API_KEY`` in your Anymail settings (Anymail does not check environment
  variables); and (2) if you use Anymail's `esp_extra` you will need to update it with
  SparkPost Transmissions API parameters.

  As part of this change esp_extra now allows use of several SparkPost features, such
  as A/B testing, that were unavailable through the Python SparkPost library. (See
  `docs <https://anymail.readthedocs.io/en/stable/esps/sparkpost/>`__.)

* Remove Anymail internal code related to supporting Python 2 and older Django
  versions. This does not change the documented API, but may affect you if your
  code borrowed from Anymail's undocumented internals. (You should be able to switch
  to the Python standard library equivalents, as Anymail has done.)

* AnymailMessageMixin now correctly subclasses Django's EmailMessage. If you use it
  as part of your own custom EmailMessage-derived class, and you start getting errors
  about "consistent method resolution order," you probably need to change your class's
  inheritance. (For some helpful background, see this comment about
  `mixin superclass ordering <https://nedbatchelder.com/blog/201210/multiple_inheritance_is_hard.html#comment_13805>`__.)

Features
~~~~~~~~

* **SparkPost:** Add support for subaccounts (new ``"SPARKPOST_SUBACCOUNT"`` Anymail
  setting), AMP for Email (via ``message.attach_alternative(..., "text/x-amp-html")``),
  and A/B testing and other SparkPost sending features (via ``esp_extra``). (See
  `docs <https://anymail.readthedocs.io/en/stable/esps/sparkpost/>`__.)


v7.2.1
------

*2020-08-05*

Fixes
~~~~~

* **Inbound:** Fix a Python 2.7-only UnicodeEncodeError when attachments have non-ASCII
  filenames. (Thanks to `@kika115`_ for reporting it.)


v7.2 LTS
--------

*2020-07-25*

This is an extended support release. Anymail v7.2 will receive security updates
and fixes for any breaking ESP API changes through at least July, 2021.

Fixes
~~~~~

* **Amazon SES:** Fix bcc, which wasn't working at all on non-template sends.
  (Thanks to `@mwheels`_ for reporting the issue.)

* **Mailjet:** Fix TypeError when sending to or from addresses with display names
  containing commas (introduced in Django 2.2.15, 3.0.9, and 3.1).

* **SendGrid:** Fix UnicodeError in inbound webhook, when receiving message using
  charsets other than utf-8, and *not* using SendGrid's "post raw" inbound parse
  option. Also update docs to recommend "post raw" with SendGrid inbound. (Thanks to
  `@tcourtqtm`_ for reporting the issue.)


Features
~~~~~~~~

* Test against Django 3.1 release candidates


Deprecations
~~~~~~~~~~~~

*  This will be the last Anymail release to support Django 1.11 and Python 2.7.

If these deprecations affect you and you cannot upgrade, set your requirements to
`django-anymail~=7.2` (a "compatible release" specifier, equivalent to `>=7.2,==7.*`).


v7.1
-----

*2020-04-13*

Fixes
~~~~~

* **Postmark:** Fix API error when sending with template to single recipient.
  (Thanks to `@jc-ee`_ for finding and fixing the issue.)

* **SendGrid:** Allow non-batch template send to multiple recipients when
  `merge_global_data` is set without `merge_data`. (Broken in v6.0. Thanks to
  `@vgrebenschikov`_ for the bug report.)

Features
~~~~~~~~

* Add `DEBUG_API_REQUESTS` setting to dump raw ESP API requests, which can assist
  in debugging or reporting problems to ESPs.
  (See `docs <https://anymail.readthedocs.io/en/stable/installation/#std:setting-ANYMAIL_DEBUG_API_REQUESTS>`__.
  This setting has was quietly added in Anymail v4.3, and is now officially documented.)

* **Sendinblue:** Now supports file attachments on template sends, when using their
  new template language. (Sendinblue removed this API limitation on 2020-02-18; the
  change works with Anymail v7.0 and later. Thanks to `@sebashwa`_ for noting
  the API change and updating Anymail's docs.)

Other
~~~~~

* Test against released Django 3.0.

* **SendGrid:** Document unpredictable behavior in the SendGrid API that can cause
  text attachments to be sent with the wrong character set.
  (See `docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#limitations-and-quirks>`__
  under "Wrong character set on text attachments." Thanks to `@nuschk`_ and `@swrobel`_
  for helping track down the issue and reporting it to SendGrid.)

* Docs: Fix a number of typos and some outdated information. (Thanks `@alee`_ and
  `@Honza-m`_.)


v7.0
----

*2019-09-07*

Breaking changes
~~~~~~~~~~~~~~~~

* **Sendinblue templates:** Support Sendinblue's new (ESP stored) Django templates and
  new API for template sending. This removes most of the odd limitations in the older
  (now-deprecated) SendinBlue template send API, but involves two breaking changes:

  * You *must* `convert <https://help.sendinblue.com/hc/en-us/articles/360000991960>`_
    each old Sendinblue template to the new language as you upgrade to Anymail v7.0, or
    certain features may be silently ignored on template sends (notably `reply_to` and
    recipient display names).

  * Sendinblue's API no longer supports sending attachments when using templates.
    [Note: Sendinblue removed this API limitation on 2020-02-18.]

  Ordinary, non-template sending is not affected by these changes. See
  `docs <https://anymail.readthedocs.io/en/stable/esps/sendinblue/#batch-sending-merge-and-esp-templates>`__
  for more info and alternatives. (Thanks `@Thorbenl`_.)

Features
~~~~~~~~

* **Mailgun:** Support Mailgun's new (ESP stored) handlebars templates via `template_id`.
  See `docs <https://anymail.readthedocs.io/en/stable/esps/mailgun/#batch-sending-merge-and-esp-templates>`__.
  (Thanks `@anstosa`_.)

* **Sendinblue:** Support multiple `tags`. (Thanks `@Thorbenl`_.)


Other
~~~~~

* **Mailgun:** Disable Anymail's workaround for a Requests/urllib3 issue with non-ASCII
  attachment filenames when a newer version of urllib3--which fixes the problem--is
  installed. (Workaround was added in Anymail v4.3; fix appears in urllib3 v1.25.)


v6.1
----

*2019-07-07*

Features
~~~~~~~~

* **Mailgun:** Add new `MAILGUN_WEBHOOK_SIGNING_KEY` setting for verifying tracking and
  inbound webhook calls. Mailgun's webhook signing key can become different from your
  `MAILGUN_API_KEY` if you have ever rotated either key.
  See `docs <https://anymail.readthedocs.io/en/stable/esps/mailgun/#std:setting-ANYMAIL_MAILGUN_WEBHOOK_SIGNING_KEY>`__.
  (More in `#153`_. Thanks to `@dominik-lekse`_ for reporting the problem and Mailgun's
  `@mbk-ok`_ for identifying the cause.)


v6.0.1
------

*2019-05-19*

Fixes
~~~~~

* Support using `AnymailMessage` with django-mailer and similar packages that pickle
  messages. (See `#147`_. Thanks to `@ewingrj`_ for identifying the problem.)

* Fix UnicodeEncodeError error while reporting invalid email address on Python 2.7.
  (See `#148`_. Thanks to `@fdemmer`_ for reporting the problem.)


v6.0
----

*2019-02-23*

Breaking changes
~~~~~~~~~~~~~~~~

* **Postmark:** Anymail's `message.anymail_status.recipients[email]` no longer
  lowercases the recipient's email address. For consistency with other ESPs, it now
  uses the recipient email with whatever case was used in the sent message. If your
  code is doing something like `message.anymail_status.recipients[email.lower()]`,
  you should remove the `.lower()`

* **SendGrid:** In batch sends, Anymail's SendGrid backend now assigns a separate
  `message_id` for each "to" recipient, rather than sharing a single id for all
  recipients. This improves accuracy of tracking and statistics (and matches the
  behavior of many other ESPs).

  If your code uses batch sending (merge_data with multiple to-addresses) and checks
  `message.anymail_status.message_id` after sending, that value will now be a *set* of
  ids. You can obtain each recipient's individual message_id with
  `message.anymail_status.recipients[to_email].message_id`.
  See `docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#sendgrid-message-id>`__.

Features
~~~~~~~~

* Add new `merge_metadata` option for providing per-recipient metadata in batch
  sends. Available for all supported ESPs *except* Amazon SES and SendinBlue.
  See `docs <https://anymail.readthedocs.io/en/stable/sending/anymail_additions/#anymail.message.AnymailMessage.merge_metadata>`__.
  (Thanks `@janneThoft`_ for the idea and SendGrid implementation.)

* **Mailjet:** Remove limitation on using `cc` or `bcc` together with `merge_data`.


Fixes
~~~~~

* **Mailgun:** Better error message for invalid sender domains (that caused a cryptic
  "Mailgun API response 200: OK Mailgun Magnificent API" error in earlier releases).

* **Postmark:** Don't error if a message is sent with only Cc and/or Bcc recipients
  (but no To addresses). Also, `message.anymail_status.recipients[email]` now includes
  send status for Cc and Bcc recipients. (Thanks to `@ailionx`_ for reporting the error.)

* **SendGrid:** With legacy templates, stop (ab)using "sections" for merge_global_data.
  This avoids potential conflicts with a template's own use of SendGrid section tags.


v5.0
----

*2018-11-07*

Breaking changes
~~~~~~~~~~~~~~~~

* **Mailgun:** Anymail's status tracking webhooks now report Mailgun "temporary failure"
  events as Anymail's normalized "deferred" `event_type`. (Previously they were reported
  as "bounced", lumping them in with permanent failures.) The new behavior is consistent
  with how Anymail handles other ESP's tracking notifications. In the unlikely case your
  code depended on "temporary failure" showing up as "bounced" you will need to update it.
  (Thanks `@costela`_.)

Features
~~~~~~~~

* **Postmark:** Allow either template alias (string) or numeric template id for
  Anymail's `template_id` when sending with Postmark templates.

Fixes
~~~~~

* **Mailgun:** Improve error reporting when an inbound route is accidentally pointed
  at Anymail's tracking webhook url or vice versa.


v4.3
----

*2018-10-11*

Features
~~~~~~~~

*  Treat MIME attachments that have a *Content-ID* but no explicit *Content-Disposition*
   header as inline, matching the behavior of many email clients. For maximum
   compatibility, you should always set both (or use Anymail's inline helper functions).
   (Thanks `@costela`_.)

Fixes
~~~~~

*  **Mailgun:** Raise `AnymailUnsupportedFeature` error when attempting to send an
   attachment without a filename (or inline attachment without a *Content-ID*), because
   Mailgun silently drops these attachments from the sent message. (See
   `docs <https://anymail.readthedocs.io/en/stable/esps/mailgun/#limitations-and-quirks>`__.
   Thanks `@costela`_ for identifying this undocumented Mailgun API limitation.)
*  **Mailgun:** Fix problem where attachments with non-ASCII filenames would be lost.
   (Works around Requests/urllib3 issue encoding multipart/form-data filenames in a way
   that isn't RFC 7578 compliant. Thanks to `@decibyte`_ for catching the problem.)

Other
~~~~~
*  Add (undocumented) DEBUG_API_REQUESTS Anymail setting. When enabled, prints raw
   API request and response during send. Currently implemented only for Requests-based
   backends (all but Amazon SES and SparkPost). Because this can expose API keys and
   other sensitive info in log files, it should not be used in production.


v4.2
----

*2018-09-07*

Features
~~~~~~~~

*  **Postmark:** Support per-recipient template `merge_data` and batch sending. (Batch
   sending can be used with or without a template. See
   `docs <https://anymail.readthedocs.io/en/stable/esps/postmark/#postmark-templates>`__.)

Fixes
~~~~~

*  **Postmark:** When using `template_id`, ignore empty subject and body. (Postmark
   issues an error if Django's default empty strings are used with template sends.)


v4.1
----

*2018-08-27*

Features
~~~~~~~~

*  **SendGrid:** Support both new "dynamic" and original "legacy" transactional
   templates. (See
   `docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#sendgrid-templates>`__.)
*  **SendGrid:** Allow merging `esp_extra["personalizations"]` dict into other message-derived
   personalizations. (See
   `docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#sendgrid-esp-extra>`__.)


v4.0
----

*2018-08-19*

Breaking changes
~~~~~~~~~~~~~~~~

*  Drop support for Django versions older than Django 1.11.
   (For compatibility back to Django 1.8, stay on the Anymail `v3.0`_
   extended support branch.)
*  **SendGrid:** Remove the legacy SendGrid *v2* EmailBackend.
   (Anymail's default since v0.8 has been SendGrid's newer v3 API.)
   If your settings.py `EMAIL_BACKEND` still references "sendgrid_v2," you must
   `upgrade to v3 <https://anymail.readthedocs.io/en/v3.0/esps/sendgrid/#upgrading-to-sendgrid-s-v3-api>`__.

Features
~~~~~~~~

*  **Mailgun:** Add support for new Mailgun webhooks. (Mailgun's original "legacy
   webhook" format is also still supported. See
   `docs <https://anymail.readthedocs.io/en/stable/esps/mailgun/#mailgun-webhooks>`__.)
*  **Mailgun:** Document how to use new European region. (This works in earlier
   Anymail versions, too.)
*  **Postmark:** Add support for Anymail's normalized `metadata` in sending
   and webhooks.

Fixes
~~~~~

*  Avoid problems with Gmail blocking messages that have inline attachments, when sent
   from a machine whose local hostname ends in *.com*. Change Anymail's
   `attach_inline_image()` default *Content-ID* domain to the literal text "inline"
   (rather than Python's default of the local hostname), to work around a limitation
   of some ESP APIs that don't permit distinct content ID and attachment filenames
   (Mailgun, Mailjet, Mandrill and SparkPost). See `#112`_ for more details.
*  **Amazon SES:** Work around an
   `Amazon SES bug <https://forums.aws.amazon.com/thread.jspa?threadID=287048>`__
   that can corrupt non-ASCII message bodies if you are using SES's open or click
   tracking. (See `#115`_ for more details. Thanks to `@varche1`_ for isolating
   the specific conditions that trigger the bug.)

Other
~~~~~

*  Maintain changelog in the repository itself (rather than in GitHub release notes).
*  Test against released versions of Python 3.7 and Django 2.1.


v3.0
----

*2018-05-30*

This is an extended support release. Anymail v3.x will receive security updates
and fixes for any breaking ESP API changes through at least April, 2019.

Breaking changes
~~~~~~~~~~~~~~~~

*  Drop support for Python 3.3 (see `#99`_).
*  **SendGrid:** Fix a problem where Anymail's status tracking webhooks didn't always
   receive the same `event.message_id` as the sent `message.anymail_status.message_id`,
   due to unpredictable behavior by SendGrid's API. Anymail now generates a UUID for
   each sent message and attaches it as a SendGrid custom arg named anymail_id. For most
   users, this change should be transparent. But it could be a breaking change if you
   are relying on a specific message_id format, or relying on message_id matching the
   *Message-ID* mail header or SendGrid's "smtp-id" event field. (More details in the
   `docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#sendgrid-message-id>`__;
   also see `#108`_.) Thanks to `@joshkersey`_ for the report and the fix.

Features
~~~~~~~~

*  Support Django 2.1 prerelease.

Fixes
~~~~~

*  **Mailjet:** Fix tracking webhooks to work correctly when Mailjet "group events"
   option is disabled (see `#106`_).

Deprecations
~~~~~~~~~~~~

*  This will be the last Anymail release to support Django 1.8, 1.9, and 1.10
   (see `#110`_).
*  This will be the last Anymail release to support the legacy SendGrid v2 EmailBackend
   (see `#111`_). (SendGrid's newer v3 API has been the default since Anymail v0.8.)

If these deprecations affect you and you cannot upgrade, set your requirements to
`django-anymail~=3.0` (a "compatible release" specifier, equivalent to `>=3.0,==3.*`).


v2.2
----

*2018-04-16*

Fixes
~~~~~

*  Fix a breaking change accidentally introduced in v2.1: The boto3 package is no
   longer required if you aren't using Amazon SES.


v2.1
----

*2018-04-11*

**NOTE:** v2.1 accidentally introduced a **breaking change:** enabling Anymail webhooks
with `include('anymail.urls')` causes an error if boto3 is not installed, even if you
aren't using Amazon SES. This is fixed in v2.2.

Features
~~~~~~~~

*  **Amazon SES:** Add support for this ESP
   (`docs <https://anymail.readthedocs.io/en/stable/esps/amazon_ses/>`__).
*  **SparkPost:** Add SPARKPOST_API_URL setting to support SparkPost EU and SparkPost
   Enterprise
   (`docs <https://anymail.readthedocs.io/en/stable/esps/sparkpost/#std:setting-ANYMAIL_SPARKPOST_API_URL>`__).
*  **Postmark:** Update for Postmark "modular webhooks." This should not impact client
   code. (Also, older versions of Anymail will still work correctly with Postmark's
   webhook changes.)

Fixes
~~~~~

*  **Inbound:** Fix several issues with inbound messages, particularly around non-ASCII
   headers and body content. Add workarounds for some limitations in older Python email
   packages.

Other
~~~~~

*  Use tox to manage Anymail test environments (see contributor
   `docs <https://anymail.readthedocs.io/en/stable/contributing/#testing>`__).

Deprecations
~~~~~~~~~~~~

*  This will be the last Anymail release to support Python 3.3. See `#99`_ for more
   information.


v2.0
----

*2018-03-08*

Breaking changes
~~~~~~~~~~~~~~~~

*  Drop support for deprecated WEBHOOK_AUTHORIZATION setting. If you are using webhooks
   and still have this Anymail setting, you must rename it to WEBHOOK_SECRET. See the
   `v1.4`_ release notes.
*  Handle *Reply-To,* *From,* and *To* in EmailMessage `extra_headers` the same as
   Django's SMTP EmailBackend if supported by your ESP, otherwise raise an unsupported
   feature error. Fixes the SparkPost backend to be consistent with other backends if
   both `headers["Reply-To"]` and `reply_to` are set on the same message. If you are
   setting a message's `headers["From"]` or `headers["To"]` (neither is common), the
   new behavior is likely a breaking change. See
   `docs <https://anymail.readthedocs.io/en/stable/sending/django_email/#additional-headers>`__
   and `#91`_.
*  Treat EmailMessage `extra_headers` keys as case-\ *insensitive* in all backends, for
   consistency with each other (and email specs). If you are specifying duplicate
   headers whose names differ only in case, this may be a breaking change. See
   `docs <https://anymail.readthedocs.io/en/stable/sending/django_email/#additional-headers>`__.

Features
~~~~~~~~

*  **SendinBlue:** Add support for this ESP
   (`docs <https://anymail.readthedocs.io/en/stable/esps/sendinblue/>`__).
   Thanks to `@RignonNoel`_ for the implementation.
*  Add EmailMessage `envelope_sender` attribute, which can adjust the message's
   *Return-Path* if supported by your ESP
   (`docs <https://anymail.readthedocs.io/en/stable/sending/anymail_additions/#anymail.message.AnymailMessage.envelope_sender>`__).
*  Add universal wheel to PyPI releases for faster installation.

Other
~~~~~

*  Update setup.py metadata, clean up implementation. (Hadn't really been touched
   since original Djrill version.)
*  Prep for Python 3.7.


v1.4
----

*2018-02-08*

Security
~~~~~~~~

*  Fix a low severity security issue affecting Anymail v0.2–v1.3: rename setting
   WEBHOOK_AUTHORIZATION to WEBHOOK_SECRET to prevent inclusion in Django error
   reporting.
   (`CVE-2018-1000089 <https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2018-1000089>`__)

*More information*

Django error reporting includes the value of your Anymail WEBHOOK_AUTHORIZATION
setting. In a properly-configured deployment, this should not be cause for concern.
But if you have somehow exposed your Django error reports (e.g., by mis-deploying
with DEBUG=True or by sending error reports through insecure channels), anyone who
gains access to those reports could discover your webhook shared secret. An
attacker could use this to post fabricated or malicious Anymail tracking/inbound events
to your app, if you are using those Anymail features.

The fix renames Anymail's webhook shared secret setting so that Django's error
reporting mechanism will
`sanitize <https://docs.djangoproject.com/en/stable/ref/settings/#debug>`__ it.

If you are using Anymail's event tracking and/or inbound webhooks, you should upgrade
to this release and change "WEBHOOK_AUTHORIZATION" to "WEBHOOK_SECRET" in the ANYMAIL
section of your settings.py. You may also want to
`rotate the shared secret <https://anymail.readthedocs.io/en/stable/tips/securing_webhooks/#use-a-shared-authorization-secret>`__
value, particularly if you have ever exposed your Django error reports to untrusted
individuals.

If you are only using Anymail's EmailBackends for sending email and have not set up
Anymail's webhooks, this issue does not affect you.

The old WEBHOOK_AUTHORIZATION setting is still allowed in this release, but will issue
a system-check warning when running most Django management commands. It will be removed
completely in a near-future release, as a breaking change.

Thanks to Charlie DeTar (`@yourcelf`_) for responsibly reporting this security issue
through private channels.


v1.3
----

*2018-02-02*

Security
~~~~~~~~

*  v1.3 includes the v1.2.1 security fix released at the same time. Please review the
   `v1.2.1`_ release notes, below, if you are using Anymail's tracking webhooks.

Features
~~~~~~~~

*  **Inbound handling:** Add normalized inbound message event, signal, and webhooks
   for all supported ESPs. (See new
   `Receiving mail <https://anymail.readthedocs.io/en/stable/inbound/>`__ docs.)
   This hasn't been through much real-world testing yet; bug reports and feedback
   are very welcome.
*  **API network timeouts:** For Requests-based backends (all but SparkPost), use a
   default timeout of 30 seconds for all ESP API calls, to avoid stalling forever on
   a bad connection. Add a REQUESTS_TIMEOUT Anymail setting to override. (See `#80`_.)
*  **Test backend improvements:** Generate unique tracking `message_id` when using the
   `test backend <https://anymail.readthedocs.io/en/stable/tips/test_backend/>`__;
   add console backend for use in development. (See `#85`_.)


.. _release_1_2_1:

v1.2.1
------

*2018-02-02*

Security
~~~~~~~~

*  Fix a **moderate severity** security issue affecting Anymail v0.2–v1.2:
   prevent timing attack on WEBHOOK_AUTHORIZATION secret.
   (`CVE-2018-6596 <https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2018-6596>`__)

*More information*

If you are using Anymail's tracking webhooks, you should upgrade to this release,
and you may want to rotate to a new WEBHOOK_AUTHORIZATION shared secret (see
`docs <https://anymail.readthedocs.io/en/stable/tips/securing_webhooks/#use-a-shared-authorization-secret>`__).
You should definitely change your webhook auth if your logs indicate attempted exploit.

(If you are only sending email using an Anymail EmailBackend, and have not set up
Anymail's event tracking webhooks, this issue does not affect you.)

Anymail's webhook validation was vulnerable to a timing attack. A remote attacker
could use this to obtain your WEBHOOK_AUTHORIZATION shared secret, potentially allowing
them to post fabricated or malicious email tracking events to your app.

There have not been any reports of attempted exploit. (The vulnerability was discovered
through code review.) Attempts would be visible in HTTP logs as a very large number of
400 responses on Anymail's webhook urls (by default "/anymail/*esp_name*/tracking/"),
and in Python error monitoring as a very large number of
AnymailWebhookValidationFailure exceptions.


v1.2
----

*2017-11-02*

Features
~~~~~~~~

*  **Postmark:** Support new click webhook in normalized tracking events


v1.1
----

*2017-10-28*

Fixes
~~~~~

*  **Mailgun:** Support metadata in opened/clicked/unsubscribed tracking webhooks,
   and fix potential problems if metadata keys collided with Mailgun event parameter
   names. (See `#76`_, `#77`_)

Other
~~~~~

*  Rework Anymail's ParsedEmail class and rename to EmailAddress to align it with
   similar functionality in the Python 3.6 email package, in preparation for future
   inbound support. ParsedEmail was not documented for use outside Anymail's internals
   (so this change does not bump the semver major version), but if you were using
   it in an undocumented way you will need to update your code.


v1.0
----

*2017-09-18*

It's official: Anymail is no longer "pre-1.0." The API has been stable
for many months, and there's no reason not to use Anymail in production.

Breaking changes
~~~~~~~~~~~~~~~~

*  There are no *new* breaking changes in the 1.0 release, but a breaking change
   introduced several months ago in v0.8 is now strictly enforced. If you still have
   an EMAIL_BACKEND setting that looks like
   "anymail.backends.*espname*.\ *EspName*\ Backend", you'll need to change it to just
   "anymail.backends.*espname*.EmailBackend". (Earlier versions had issued a
   DeprecationWarning. See the `v0.8`_ release notes.)

Features
~~~~~~~~

*  Clean up and document Anymail's
   `Test EmailBackend <https://anymail.readthedocs.io/en/stable/tips/test_backend/>`__
*  Add notes on
   `handling transient ESP errors <https://anymail.readthedocs.io/en/stable/tips/transient_errors/>`__
   and improving
   `batch send performance <https://anymail.readthedocs.io/en/stable/tips/performance/>`__
*  **SendGrid:** handle Python 2 `long` integers in metadata and extra headers


v1.0.rc0
--------

*2017-09-09*

Breaking changes
~~~~~~~~~~~~~~~~

*  **All backends:** The old *EspName*\ Backend names that were deprecated in v0.8 have
   been removed. Attempting to use the old names will now fail, rather than issue a
   DeprecationWarning. See the `v0.8`_ release notes.

Features
~~~~~~~~

*  Anymail's Test EmailBackend is now
   `documented <https://anymail.readthedocs.io/en/stable/tips/test_backend/>`__
   (and cleaned up)


v0.11.1
-------

*2017-07-24*

Fixes
~~~~~

*  **Mailjet:** Correct settings docs.


v0.11
-----

*2017-07-13*

Features
~~~~~~~~

*  **Mailjet:** Add support for this ESP. Thanks to `@Lekensteyn`_ and `@calvin`_.
   (`Docs <https://anymail.readthedocs.io/en/stable/esps/mailjet/>`__)
*  In webhook handlers, AnymailTrackingEvent.metadata now defaults to `{}`, and
   .tags defaults to `[]`, if the ESP does not supply these fields with the event.
   (See `#67`_.)


v0.10
-----

*2017-05-22*

Features
~~~~~~~~

*  **Mailgun, SparkPost:** Support multiple from addresses, as a comma-separated
   `from_email` string. (*Not* a list of strings, like the recipient fields.)
   RFC-5322 allows multiple from email addresses, and these two ESPs support it.
   Though as a practical matter, multiple from emails are either ignored or treated
   as a spam signal by receiving mail handlers. (See `#60`_.)

Fixes
~~~~~

*  Fix crash sending forwarded email messages as attachments. (See `#59`_.)
*  **Mailgun:** Fix webhook crash on bounces from some receiving mail handlers.
   (See `#62`_.)
*  Improve recipient-parsing error messages and consistency with Django's SMTP
   backend. In particular, Django (and now Anymail) allows multiple, comma-separated
   email addresses in a single recipient string.


v0.9
----

*2017-04-04*

Breaking changes
~~~~~~~~~~~~~~~~

*  **Mandrill, Postmark:** Normalize soft-bounce webhook events to event_type
   'bounced' (rather than 'deferred').

Features
~~~~~~~~

*  Officially support released Django 1.11, including under Python 3.6.


.. _release_0_8:

v0.8
----

*2017-02-02*

Breaking changes
~~~~~~~~~~~~~~~~

*  **All backends:** Rename all Anymail backends to just `EmailBackend`, matching
   Django's naming convention. E.g., you should update:
   `EMAIL_BACKEND = "anymail.backends.mailgun.MailgunBackend" # old`
   to: `EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend" # new`

   The old names still work, but will issue a DeprecationWarning and will be removed
   in some future release (Apologies for this change; the old naming was a holdover
   from Djrill, and I wanted to establish consistency with other Django EmailBackends
   before Anymail 1.0. See `#49`_.)

*  **SendGrid:** Update SendGrid backend to their newer Web API v3. This should be a
   transparent change for most projects. Exceptions: if you use SendGrid
   username/password auth, Anymail's `esp_extra` with "x-smtpapi", or multiple Reply-To
   addresses, please review the
   `porting notes <https://anymail.readthedocs.io/en/v3.0/esps/sendgrid/#sendgrid-v3-upgrade>`__.

   The SendGrid v2 EmailBackend
   `remains available <https://anymail.readthedocs.io/en/v3.0/esps/sendgrid/#sendgrid-v2-backend>`__
   if you prefer it, but is no longer the default.

   .. SendGrid v2 backend removed after Anymail v3.0; links frozen to that doc version

Features
~~~~~~~~

*  Test on Django 1.11 prerelease, including under Python 3.6.

Fixes
~~~~~

*  **Mandrill:** Fix bug in webhook signature validation when using basic auth via the
   WEBHOOK_AUTHORIZATION setting. (If you were using the MANDRILL_WEBHOOK_URL setting
   to work around this problem, you should be able to remove it. See `#48`_.)


v0.7
----

*2016-12-30*

Breaking changes
~~~~~~~~~~~~~~~~

*  Fix a long-standing bug validating email addresses. If an address has a display name
   containing a comma or parentheses, RFC-5322 *requires* double-quotes around the
   display name (`'"Widgets, Inc." <widgets@example.com>'`). Anymail now raises a new
   `AnymailInvalidAddress` error for misquoted display names and other malformed
   addresses. (Previously, it silently truncated the address, leading to obscure
   exceptions or unexpected behavior. If you were unintentionally relying on that buggy
   behavior, this may be a breaking change. See `#44`_.) In general, it's safest to
   always use double-quotes around all display names.

Features
~~~~~~~~

*  **Postmark:** Support Postmark's new message delivery event in Anymail normalized
   tracking webhook. (Update your Postmark config to enable the new event. See
   `docs <https://anymail.readthedocs.io/en/stable/esps/postmark/#status-tracking-webhooks>`__.)
*  Handle virtually all uses of Django lazy translation strings as EmailMessage
   properties. (In earlier releases, these could sometimes lead to obscure exceptions
   or unexpected behavior with some ESPs. See `#34`_.)
*  **Mandrill:** Simplify and document two-phase process for setting up
   Mandrill webhooks
   (`docs <https://anymail.readthedocs.io/en/stable/esps/mandrill/#status-tracking-webhooks>`__).


v0.6.1
------

*2016-11-01*

Fixes
~~~~~

*  **Mailgun, Mandrill:** Support older Python 2.7.x versions in webhook validation
   (`#39`_; thanks `@sebbacon`_).
*  **Postmark:** Handle older-style 'Reply-To' in EmailMessage `headers` (`#41`_).


v0.6
----

*2016-10-25*

Breaking changes
~~~~~~~~~~~~~~~~

*  **SendGrid:** Fix missing html or text template body when using `template_id` with
   an empty Django EmailMessage body. In the (extremely-unlikely) case you were relying
   on the earlier quirky behavior to *not* send your saved html or text template, you
   may want to verify that your SendGrid templates have matching html and text.
   (`docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#batch-sending-merge-and-esp-templates>`__
   -- also see `#32`_.)

Features
~~~~~~~~

*  **Postmark:** Add support for `track_clicks`
   (`docs <https://anymail.readthedocs.io/en/stable/esps/postmark/#limitations-and-quirks>`__)
*  Initialize AnymailMessage.anymail_status to empty status, rather than None;
   clarify docs around `anymail_status` availability
   (`docs <https://anymail.readthedocs.io/en/stable/sending/anymail_additions/#esp-send-status>`__)


v0.5
----

*2016-08-22*

Features
~~~~~~~~

*  **Mailgun:** Add MAILGUN_SENDER_DOMAIN setting.
   (`docs <https://anymail.readthedocs.io/en/stable/esps/mailgun/#mailgun-sender-domain>`__)


v0.4.2
------

*2016-06-24*

Fixes
~~~~~

*  **SparkPost:** Fix API error "Both content object and template_id are specified"
   when using `template_id` (`#24`_).


v0.4.1
------

*2016-06-23*

Features
~~~~~~~~

*  **SparkPost:** Add support for this ESP.
   (`docs <https://anymail.readthedocs.io/en/stable/esps/sparkpost/>`__)
*  Test with Django 1.10 beta
*  Requests-based backends (all but SparkPost) now raise AnymailRequestsAPIError
   for any requests.RequestException, for consistency and proper fail_silently behavior.
   (The exception will also be a subclass of the original RequestException, so no
   changes are required to existing code looking for specific requests failures.)


v0.4
----

*(not released)*


v0.3.1
------

*2016-05-18*

Fixes
~~~~~

*  **SendGrid:** Fix API error that `to` is required when using `merge_data`
   (see `#14`_; thanks `@lewistaylor`_).


v0.3
----

*2016-05-13*

Features
~~~~~~~~

*  Add support for ESP stored templates and batch sending/merge. Exact capabilities
   vary widely by ESP -- be sure to read the notes for your ESP.
   (`docs <https://anymail.readthedocs.io/en/stable/sending/templates/>`__)
*  Add pre_send and post_send signals.
   `docs <https://anymail.readthedocs.io/en/stable/sending/signals/>`__
*  **Mandrill:** add support for esp_extra; deprecate Mandrill-specific message
   attributes left over from Djrill. See
   `migrating from Djrill <https://anymail.readthedocs.io/en/stable/esps/mandrill/#migrating-from-djrill>`__.


v0.2
----

*2016-04-30*

Breaking changes
~~~~~~~~~~~~~~~~

*  **Mailgun:** eliminate automatic JSON encoding of complex metadata values like lists
   and dicts. (Was based on misreading of Mailgun docs; behavior now matches metadata
   handling for all other ESPs.)
*  **Mandrill:** remove obsolete wehook views and signal inherited from Djrill. See
   `Djrill migration notes <https://anymail.readthedocs.io/en/stable/esps/mandrill/#changes-to-webhooks>`__
   if you were relying on that code.

Features
~~~~~~~~

*  Add support for ESP event-tracking webhooks, including normalized
   AnymailTrackingEvent.
   (`docs <https://anymail.readthedocs.io/en/stable/sending/tracking/>`__)
*  Allow get_connection kwargs overrides of most settings for individual backend
   instances. Can be useful for, e.g., working with multiple SendGrid subusers.
   (`docs <https://anymail.readthedocs.io/en/stable/installation/#anymail-settings-reference>`__)
*  **SendGrid:** Add SENDGRID_GENERATE_MESSAGE_ID setting to control workarounds for
   ensuring unique tracking ID on SendGrid messages/events (default enabled).
   `docs <https://anymail.readthedocs.io/en/stable/esps/sendgrid/#sendgrid-message-id>`__
*  **SendGrid:** improve handling of 'filters' in esp_extra, making it easier to mix
   custom SendGrid app filter settings with Anymail normalized message options.

Other
~~~~~

*  Drop pre-Django 1.8 test code. (Wasn't being used, as Anymail requires Django 1.8+.)
*  **Mandrill:** note limited support in docs (because integration tests no
   longer available).


v0.1
----

*2016-03-14*

Although this is an early release, it provides functional Django
EmailBackends and passes integration tests with all supported ESPs
(Mailgun, Mandrill, Postmark, SendGrid).

It has (obviously) not yet undergone extensive real-world testing, and
you are encouraged to monitor it carefully if you choose to use it in
production. Please report bugs and problems here in GitHub.

Features
~~~~~~~~

*  **Postmark:** Add support for this ESP.
*  **SendGrid:** Add support for username/password auth.
*  Simplified install: no need to name the ESP (`pip install django-anymail`
   -- not `... django-anymail[mailgun]`)


0.1.dev2
--------

*2016-03-12*

Features
~~~~~~~~

*  **SendGrid:** Add support for this ESP.
*  Add attach_inline_image_file helper

Fixes
~~~~~

*  Change inline-attachment handling to look for `Content-Disposition: inline`,
   and to preserve filenames where supported by the ESP.


0.1.dev1
--------

*2016-03-10*

Features
~~~~~~~~

*  **Mailgun, Mandrill:** initial supported ESPs.
*  Initial docs


.. GitHub issue and user links
   (GitHub auto-linking doesn't work in Sphinx)

.. _#14: https://github.com/anymail/django-anymail/issues/14
.. _#24: https://github.com/anymail/django-anymail/issues/24
.. _#32: https://github.com/anymail/django-anymail/issues/32
.. _#34: https://github.com/anymail/django-anymail/issues/34
.. _#39: https://github.com/anymail/django-anymail/issues/39
.. _#41: https://github.com/anymail/django-anymail/issues/41
.. _#44: https://github.com/anymail/django-anymail/issues/44
.. _#48: https://github.com/anymail/django-anymail/issues/48
.. _#49: https://github.com/anymail/django-anymail/issues/49
.. _#59: https://github.com/anymail/django-anymail/issues/59
.. _#60: https://github.com/anymail/django-anymail/issues/60
.. _#62: https://github.com/anymail/django-anymail/issues/62
.. _#67: https://github.com/anymail/django-anymail/issues/67
.. _#76: https://github.com/anymail/django-anymail/issues/76
.. _#77: https://github.com/anymail/django-anymail/issues/77
.. _#80: https://github.com/anymail/django-anymail/issues/80
.. _#85: https://github.com/anymail/django-anymail/issues/85
.. _#91: https://github.com/anymail/django-anymail/issues/91
.. _#99: https://github.com/anymail/django-anymail/issues/99
.. _#106: https://github.com/anymail/django-anymail/issues/106
.. _#108: https://github.com/anymail/django-anymail/issues/108
.. _#110: https://github.com/anymail/django-anymail/issues/110
.. _#111: https://github.com/anymail/django-anymail/issues/111
.. _#112: https://github.com/anymail/django-anymail/issues/112
.. _#115: https://github.com/anymail/django-anymail/issues/115
.. _#147: https://github.com/anymail/django-anymail/issues/147
.. _#148: https://github.com/anymail/django-anymail/issues/148
.. _#153: https://github.com/anymail/django-anymail/issues/153

.. _@ailionx: https://github.com/ailionx
.. _@alee: https://github.com/alee
.. _@anstosa: https://github.com/anstosa
.. _@calvin: https://github.com/calvin
.. _@costela: https://github.com/costela
.. _@decibyte: https://github.com/decibyte
.. _@dominik-lekse: https://github.com/dominik-lekse
.. _@ewingrj: https://github.com/ewingrj
.. _@fdemmer: https://github.com/fdemmer
.. _@Honza-m: https://github.com/Honza-m
.. _@janneThoft: https://github.com/janneThoft
.. _@jc-ee: https://github.com/jc-ee
.. _@joshkersey: https://github.com/joshkersey
.. _@kika115: https://github.com/kika115
.. _@Lekensteyn: https://github.com/Lekensteyn
.. _@lewistaylor: https://github.com/lewistaylor
.. _@mbk-ok: https://github.com/mbk-ok
.. _@mwheels: https://github.com/mwheels
.. _@nuschk: https://github.com/nuschk
.. _@RignonNoel: https://github.com/RignonNoel
.. _@sebashwa: https://github.com/sebashwa
.. _@sebbacon: https://github.com/sebbacon
.. _@slinkymanbyday: https://github.com/slinkymanbyday
.. _@swrobel: https://github.com/swrobel
.. _@Thorbenl: https://github.com/Thorbenl
.. _@tcourtqtm: https://github.com/tcourtqtm
.. _@varche1: https://github.com/varche1
.. _@vgrebenschikov: https://github.com/vgrebenschikov
.. _@yourcelf: https://github.com/yourcelf
