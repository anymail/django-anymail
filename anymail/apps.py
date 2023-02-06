from django.apps import AppConfig
from django.core import checks

from .checks import check_deprecated_settings, check_insecure_settings


class AnymailBaseConfig(AppConfig):
    name = "anymail"
    verbose_name = "Anymail"

    def ready(self):
        checks.register(check_deprecated_settings)
        checks.register(check_insecure_settings)
