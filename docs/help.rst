.. _help:

Help
====


.. _troubleshooting:

Troubleshooting
---------------

If Anymail's not behaving like you expect, these troubleshooting tips can
often help you pinpoint the problem...

**Check the error message**

  Look for an Anymail error message in your console (running Django in dev mode)
  or in your server error logs. If you see something like "invalid API key"
  or "invalid email address", that's often a big first step toward being able
  to solve the problem.

**Check your ESPs API logs**

  Most ESPs offer some sort of API activity log in their dashboards.
  Check their logs to see if the
  data you thought you were sending actually made it to your ESP, and
  if they recorded any errors there.

**Double-check common issues**

  * Did you add any required settings for your ESP to the `ANYMAIL` dict in your
    settings.py? (E.g., ``"SENDGRID_API_KEY"`` for SendGrid.) Check the instructions
    for the ESP you're using under :ref:`supported-esps`.
  * Did you add ``'anymail'`` to the list of :setting:`INSTALLED_APPS` in settings.py?
  * Are you using a valid *from* address? Django's default is "webmaster@localhost",
    which most ESPs reject. Either specify the ``from_email`` explicitly on every message
    you send, or add :setting:`DEFAULT_FROM_EMAIL` to your settings.py.

**Try it without Anymail**

  If you think Anymail might be causing the problem, try switching your
  :setting:`EMAIL_BACKEND` setting to
  Django's :ref:`File backend <django:topic-email-file-backend>` and then running your
  email-sending code again. If that causes errors, you'll know the issue is somewhere
  other than Anymail. And you can look through the :setting:`EMAIL_FILE_PATH`
  file contents afterward to see if you're generating the email you want.

**Examine the raw API communication**

  Sometimes you just want to see exactly what Anymail is telling your ESP to do
  and how your ESP is responding. In a dev environment, enable the Anymail setting
  :setting:`DEBUG_API_REQUESTS <ANYMAIL_DEBUG_API_REQUESTS>`
  to show the raw HTTP requests and responses from (most) ESP APIs. (This is not
  recommended in production, as it can leak sensitive data into your logs.)


.. _contact:
.. _support:

Getting support
---------------

If you've gone through the troubleshooting above and still aren't sure what's wrong,
the Anymail community is happy to help.

Anymail is supported and maintained by the people who use it---like you!
Our contributors volunteer their time (and most are not employees of any ESP).

Here's how to contact the Anymail community:

**"How do I...?"**

  If the *Search docs* box on the left doesn't find an answer,
  ask a question in the GitHub `Anymail discussions`_ forum.

**"I'm getting an error or unexpected behavior..."**

  Ask a question in the GitHub `Anymail discussions`_ forum. Be sure to include:

  * which ESP you're using (Mailgun, SendGrid, etc.)
  * what versions of Anymail, Django, and Python you're running
  * the relevant portions of your code and settings
  * the text of any error messages
  * any exception stack traces

  and any other info you obtained from :ref:`troubleshooting <troubleshooting>`,
  such as what you found in your ESP's activity log.

**"I found a bug..."**

  Open a `GitHub issue`_. Be sure to include the information listed above.
  (And if you know what the problem is, we always welcome
  :ref:`contributions <contributing>` with a fix!)

**"I found a security issue!"**

  Contact the Anymail maintainers by emailing *security<AT>anymail<DOT>info.*
  (Please don't open a GitHub issue or post publicly about potential security problems.)

**"Could Anymail support this ESP or feature...?"**

  If the idea has already been suggested in the GitHub `Anymail discussions`_ forum,
  express your support using GitHub's `thumbs up reaction`_. If not, add the idea
  as a new discussion topic. And either way, if you'd be able to help with development
  or testing, please add a comment saying so.


.. _Anymail discussions: https://github.com/anymail/django-anymail/discussions
.. _GitHub issue: https://github.com/anymail/django-anymail/issues
.. _thumbs up reaction:
    https://blog.github.com/2016-03-10-add-reactions-to-pull-requests-issues-and-comments/
