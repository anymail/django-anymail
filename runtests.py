#!/usr/bin/env python

# usage: python runtests.py [tests.test_x tests.test_y.SomeTestCase ...]

import os
import re
import sys
import warnings
from pathlib import Path

import django
from django.conf import settings
from django.test.utils import get_runner


def find_test_settings():
    """
    Return dotted path to Django settings compatible with current Django version.

    Finds highest tests.test_settings.settings_N_M.py where N.M is <= Django version.
    (Generally, default Django settings don't change meaningfully between Django
    releases, so this will fall back to the most recent settings when there isn't an
    exact match for the current version, while allowing creation of new settings
    files to test significant differences.)
    """
    django_version = django.VERSION[:2]  # (major, minor)
    found_version = None  # (major, minor)
    found_path = None

    for settings_path in Path("tests/test_settings").glob("settings_*.py"):
        try:
            (major, minor) = re.match(
                r"settings_(\d+)_(\d+)\.py", settings_path.name
            ).groups()
            settings_version = (int(major), int(minor))
        except (AttributeError, TypeError, ValueError):
            raise ValueError(
                f"File '{settings_path!s}' doesn't match settings_N_M.py"
            ) from None
        if settings_version <= django_version:
            if found_version is None or settings_version > found_version:
                found_version = settings_version
                found_path = settings_path

    if found_path is None:
        raise ValueError(f"No suitable test_settings for Django {django.__version__}")

    # Convert Path("test/test_settings/settings_N_M.py")
    # to dotted module "test.test_settings.settings_N_M":
    return ".".join(found_path.with_suffix("").parts)


def setup_and_run_tests(test_labels=None):
    """Discover and run project tests. Returns number of failures."""
    test_labels = test_labels or ["tests"]

    tags = envlist("ANYMAIL_ONLY_TEST")
    exclude_tags = envlist("ANYMAIL_SKIP_TESTS")

    # In automated testing, don't run live tests unless specifically requested
    if envbool("CONTINUOUS_INTEGRATION") and not envbool("ANYMAIL_RUN_LIVE_TESTS"):
        exclude_tags.append("live")

    if tags:
        print("Only running tests tagged: %r" % tags)
    if exclude_tags:
        print("Excluding tests tagged: %r" % exclude_tags)

    # show DeprecationWarning and other default-ignored warnings:
    warnings.simplefilter("default")

    settings_module = find_test_settings()
    print(f"Using settings module {settings_module!r}.")
    os.environ["DJANGO_SETTINGS_MODULE"] = settings_module
    django.setup()

    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=1, tags=tags, exclude_tags=exclude_tags)
    return test_runner.run_tests(test_labels)


def runtests(test_labels=None):
    """Run project tests and exit"""
    # Used as setup test_suite: must either exit or return a TestSuite
    failures = setup_and_run_tests(test_labels)
    sys.exit(bool(failures))


def envbool(var, default=False):
    """Returns value of environment variable var as a bool, or default if not set/empty.

    Converts `'true'` and similar string representations to `True`,
    and `'false'` and similar string representations to `False`.
    """
    # Adapted from the old :func:`~distutils.util.strtobool`
    val = os.getenv(var, "").strip().lower()
    if val == "":
        return default
    elif val in ("y", "yes", "t", "true", "on", "1"):
        return True
    elif val in ("n", "no", "f", "false", "off", "0"):
        return False
    else:
        raise ValueError("invalid boolean value env[%r]=%r" % (var, val))


def envlist(var):
    """Returns value of environment variable var split in a comma-separated list.

    Returns an empty list if variable is empty or not set.
    """
    val = [item.strip() for item in os.getenv(var, "").split(",")]
    if val == [""]:
        # "Splitting an empty string with a specified separator returns ['']"
        val = []
    return val


if __name__ == "__main__":
    runtests(test_labels=sys.argv[1:])
