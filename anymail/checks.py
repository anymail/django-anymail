import warnings

from django.conf import settings
from django.core import checks

from anymail.utils import get_anymail_setting


def get_configured_email_backends():
    try:
        mailers = settings.MAILERS
    except AttributeError:
        # Django < 6.1, or < 7.0 and using deprecated email settings.
        pass
    else:
        return {
            config.get("BACKEND", "django.core.mail.backends.smtp.EmailBackend")
            for config in mailers.values()
        }

    try:
        from django.utils.deprecation import RemovedInDjango70Warning
    except ImportError:
        # Django < 6.1
        return {settings.EMAIL_BACKEND}
    else:
        # Django 6.1 -- 6.2: ignore warning on deprecated setting access
        with warnings.catch_warnings(
            action="ignore", category=RemovedInDjango70Warning
        ):
            return {settings.EMAIL_BACKEND}


def check_deprecated_settings(app_configs, **kwargs):
    errors = []

    anymail_settings = getattr(settings, "ANYMAIL", {})

    # anymail.W001: reserved [was deprecation warning that became anymail.E001]

    # anymail.E001: rename WEBHOOK_AUTHORIZATION to WEBHOOK_SECRET
    if "WEBHOOK_AUTHORIZATION" in anymail_settings:
        errors.append(
            checks.Error(
                "The ANYMAIL setting 'WEBHOOK_AUTHORIZATION' has been renamed"
                " 'WEBHOOK_SECRET' to improve security.",
                hint="You must update your settings.py.",
                id="anymail.E001",
            )
        )
    if hasattr(settings, "ANYMAIL_WEBHOOK_AUTHORIZATION"):
        errors.append(
            checks.Error(
                "The ANYMAIL_WEBHOOK_AUTHORIZATION setting has been renamed"
                " ANYMAIL_WEBHOOK_SECRET to improve security.",
                hint="You must update your settings.py.",
                id="anymail.E001",
            )
        )

    if any(
        backend == "anymail.backends.sendgrid.EmailBackend"
        for backend in get_configured_email_backends()
    ):
        errors.append(
            checks.Warning(
                "django-anymail has dropped official support for SendGrid.",
                hint="See https://github.com/anymail/django-anymail/issues/432.",
                id="anymail.W003",
            )
        )

    return errors


def check_insecure_settings(app_configs, **kwargs):
    errors = []

    # anymail.W002: DEBUG_API_REQUESTS can leak private information
    if get_anymail_setting("debug_api_requests", default=False) and not settings.DEBUG:
        errors.append(
            checks.Warning(
                "You have enabled the ANYMAIL setting DEBUG_API_REQUESTS, which can "
                "leak API keys and other sensitive data into logs or the console.",
                hint="You should not use DEBUG_API_REQUESTS in production deployment.",
                id="anymail.W002",
            )
        )

    return errors
