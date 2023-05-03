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

See the `contributor chart`_ for a list of some of the people who have helped
improve Anymail.

Anymail evolved from the `Djrill`_ project. Special thanks to the
folks from `brack3t`_ who developed the original version of Djrill.

.. _contributor chart: https://github.com/anymail/django-anymail/graphs/contributors
.. _brack3t: http://brack3t.com/
.. _Djrill: https://github.com/brack3t/Djrill


.. _reporting-bugs:

Bugs
----

You can report problems or request features in `Anymail's GitHub issue tracker`_.
(For a security-related issue that should not be disclosed publicly, instead email
Anymail's maintainers at *security\<at>anymail\<dot>dev*.)

We also have some :ref:`troubleshooting` information that may be helpful.

.. _Anymail's GitHub issue tracker: https://github.com/anymail/django-anymail/issues


Pull requests
-------------

Pull requests are always welcome to fix bugs and improve support for ESP and Django features.

* Please include test cases.
* We try to follow the `Django coding style`_.
* If you install `pre-commit`_, most of the style guidelines will be handled automatically.
* By submitting a pull request, you're agreeing to release your changes under under
  the same BSD license as the rest of this project.
* Documentation is appreciated, but not required.
  (Please don't let missing or incomplete documentation keep you from contributing code.)

.. Intentionally point to Django dev branch for coding docs (rather than Django stable):
.. _Django coding style:
    https://docs.djangoproject.com/en/dev/internals/contributing/writing-code/coding-style/
.. _pre-commit:
    https://pre-commit.com/


Testing
-------

Anymail is `tested via GitHub Actions`_ against several combinations of Django
and Python versions. Tests are run at least once a week, to check whether ESP APIs
and other dependencies have changed out from under Anymail.

To run the tests locally, use :pypi:`tox`:

    .. code-block:: console

        ## install tox and other development requirements:
        $ python -m pip install -r requirements-dev.txt

        ## test a representative combination of Python and Django versions:
        $ tox -e lint,django42-py311-all,django30-py37-all,docs

        ## you can also run just some test cases, e.g.:
        $ tox -e django42-py311-all tests.test_mailgun_backend tests.test_utils

        ## to test more Python/Django versions:
        $ tox --parallel auto  # ALL 20+ envs! (in parallel if possible)

(If your system doesn't come with the necessary Python versions, `pyenv`_ is helpful
to install and manage them. Or use the :shell:`--skip-missing-interpreters` tox option.)

If you don't want to use tox (or have trouble getting it working), you can run
the tests in your current Python environment:

    .. code-block:: console

        ## install the testing requirements (if any):
        $ python -m pip install -r tests/requirements.txt

        ## run the tests:
        $ python runtests.py

        ## this command can also run just a few test cases, e.g.:
        $ python runtests.py tests.test_mailgun_backend tests.test_mailgun_webhooks

Most of the included tests verify that Anymail constructs the expected ESP API
calls, without actually calling the ESP's API or sending any email. (So these
tests don't require any API keys.)

In addition to the mocked tests, Anymail has integration tests which *do* call live ESP APIs.
These tests are normally skipped; to run them, set environment variables with the necessary
API keys or other settings. For example:

    .. code-block:: console

        $ export ANYMAIL_TEST_MAILGUN_API_KEY='your-Mailgun-API-key'
        $ export ANYMAIL_TEST_MAILGUN_DOMAIN='mail.example.com'  # sending domain for that API key
        $ tox -e django42-py311-all tests.test_mailgun_integration

Check the ``*_integration_tests.py`` files in the `tests source`_ to see which variables
are required for each ESP. Depending on the supported features, the integration tests for
a particular ESP send around 5-15 individual messages. For ESPs that don't offer a sandbox,
these will be real sends charged to your account (again, see the notes in each test case).
Be sure to specify a particular testenv with tox's :shell:`-e` option, or tox will repeat the tests
for all 20+ supported combinations of Python and Django, sending hundreds of messages.


.. _pyenv: https://github.com/pyenv/pyenv
.. _tested via GitHub Actions: https://github.com/anymail/django-anymail/actions?query=workflow:test
.. _tests source: https://github.com/anymail/django-anymail/blob/main/tests


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

        $ python -m pip install -r requirements-dev.txt
        $ tox -e docs  # build the docs using Sphinx

You can run Python's simple HTTP server to view them:

    .. code-block:: console

        $ (cd .tox/docs/_html; python -m http.server 8123 --bind 127.0.0.1)

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
