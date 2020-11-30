.. role:: shell(code)
    :language: shell

.. role:: rst(code)
    :language: rst


.. _contributing:

Contributing
============

Anymail is maintained by its users. Your contributions are encouraged!

The `Anymail source code`_ is on GitHub.

.. _Anymail source code: https://github.com/anymail/django-anymail


Contributors
------------

See `AUTHORS.txt`_ for a list of some of the people who have helped
improve Anymail.

Anymail evolved from the `Djrill`_ project. Special thanks to the
folks from `brack3t`_ who developed the original version of Djrill.

.. _AUTHORS.txt: https://github.com/anymail/django-anymail/blob/main/AUTHORS.txt
.. _brack3t: http://brack3t.com/
.. _Djrill: https://github.com/brack3t/Djrill


.. _reporting-bugs:

Bugs
----

You can report problems or request features in `Anymail's GitHub issue tracker`_.
(For a security-related issue that should not be disclosed publicly, instead email
Anymail's maintainers at security<AT>anymail<DOT>info.)

We also have some :ref:`troubleshooting` information that may be helpful.

.. _Anymail's GitHub issue tracker: https://github.com/anymail/django-anymail/issues


Pull requests
-------------

Pull requests are always welcome to fix bugs and improve support for ESP and Django features.

* Please include test cases.
* We try to follow the `Django coding style`_
  (basically, :pep:`8` with longer lines OK).
* By submitting a pull request, you're agreeing to release your changes under under
  the same BSD license as the rest of this project.
* Documentation is appreciated, but not required.
  (Please don't let missing or incomplete documentation keep you from contributing code.)

.. Intentionally point to Django dev branch for coding docs (rather than Django stable):
.. _Django coding style:
    https://docs.djangoproject.com/en/dev/internals/contributing/writing-code/coding-style/


Testing
-------

Anymail is `tested via GitHub Actions`_ against several combinations of Django
and Python versions. Tests are run at least once a week, to check whether ESP APIs
and other dependencies have changed out from under Anymail.

For local development, the recommended test command is
:shell:`tox -e django31-py38-all,django20-py35-all,lint`, which tests a representative
combination of Python and Django versions. It also runs :pypi:`flake8` and other
code-style checkers. Some other test options are covered below, but using this
tox command catches most problems, and is a good pre-pull-request check.

Most of the included tests verify that Anymail constructs the expected ESP API
calls, without actually calling the ESP's API or sending any email. So these tests
don't require API keys, but they *do* require :pypi:`mock` and all ESP-specific
package requirements.

To run the tests, you can:

    .. code-block:: console

        $ python setup.py test  # (also installs test dependencies if needed)

Or:

    .. code-block:: console

        $ pip install mock boto3  # install test dependencies
        $ python runtests.py

        ## this command can also run just a few test cases, e.g.:
        $ python runtests.py tests.test_mailgun_backend tests.test_mailgun_webhooks

Or to test against multiple versions of Python and Django all at once, use :pypi:`tox`.
You'll need some version of Python 3 available. (If your system doesn't come
with that, `pyenv`_ is a helpful way to install and manage multiple Python versions.)

    .. code-block:: console

        $ pip install tox  # (if you haven't already)
        $ tox -e django31-py38-all,django20-py35-all,lint  # test recommended environments

        ## you can also run just some test cases, e.g.:
        $ tox -e django31-py38-all,django20-py35-all tests.test_mailgun_backend tests.test_utils

        ## to test more Python/Django versions:
        $ tox --parallel auto  # ALL 20+ envs! (in parallel if possible)
        $ tox --skip-missing-interpreters  # if some Python versions aren't installed

In addition to the mocked tests, Anymail has integration tests which *do* call live ESP APIs.
These tests are normally skipped; to run them, set environment variables with the necessary
API keys or other settings. For example:

    .. code-block:: console

        $ export ANYMAIL_TEST_MAILGUN_API_KEY='your-Mailgun-API-key'
        $ export ANYMAIL_TEST_MAILGUN_DOMAIN='mail.example.com'  # sending domain for that API key
        $ tox -e django31-py38-all tests.test_mailgun_integration

Check the ``*_integration_tests.py`` files in the `tests source`_ to see which variables
are required for each ESP. Depending on the supported features, the integration tests for
a particular ESP send around 5-15 individual messages. For ESPs that don't offer a sandbox,
these will be real sends charged to your account (again, see the notes in each test case).
Be sure to specify a particular testenv with tox's `-e` option, or tox may repeat the tests
for all 20+ supported combinations of Python and Django, sending hundreds of messages.


.. _pyenv: https://github.com/pyenv/pyenv
.. _tested via GitHub Actions: https://github.com/anymail/django-anymail/actions?query=workflow:test
.. _tests source: https://github.com/anymail/django-anymail/blob/main/tests
.. _.travis.yml: https://github.com/anymail/django-anymail/blob/main/.travis.yml


Documentation
-------------

As noted above, Anymail welcomes pull requests with missing or incomplete
documentation. (Code without docs is better than no contribution at all.)
But documentation---even needing edits---is always appreciated, as are pull
requests simply to improve the docs themselves.

Like many Python packages, Anymail's docs use :pypi:`Sphinx`. If you've never
worked with Sphinx or reStructuredText, Django's `Writing Documentation`_ can
get you started.

It's easiest to build Anymail's docs using tox:

    .. code-block:: console

        $ pip install tox  # (if you haven't already)
        $ tox -e docs  # build the docs using Sphinx

You can run Python's simple HTTP server to view them:

    .. code-block:: console

        $ (cd .tox/docs/_html; python3 -m http.server 8123 --bind 127.0.0.1)

... and then open http://localhost:8123/ in a browser. Leave the server running,
and just re-run the tox command and refresh your browser as you make changes.

If you've edited the main README.rst, you can preview an approximation of what
will end up on PyPI at http://localhost:8123/readme.html.

Anymail's Sphinx conf sets up a few enhancements you can use in the docs:

* Loads `intersphinx`_ mappings for Python 3, Django (stable), and Requests.
  Docs can refer to things like :rst:`:ref:`django:topics-testing-email``
  or :rst:`:class:`django.core.mail.EmailMessage``.
* Supports much of `Django's added markup`_, notably :rst:`:setting:`
  for documenting or referencing Django and Anymail settings.
* Allows linking to Python packages with :rst:`:pypi:`package-name``
  (via `extlinks`_).

.. _Django's added markup:
    https://docs.djangoproject.com/en/stable/internals/contributing/writing-documentation/#django-specific-markup
.. _extlinks: https://www.sphinx-doc.org/en/stable/usage/extensions/extlinks.html
.. _intersphinx: https://www.sphinx-doc.org/en/stable/usage/extensions/intersphinx.html
.. _Writing Documentation:
    https://docs.djangoproject.com/en/stable/internals/contributing/writing-documentation/
