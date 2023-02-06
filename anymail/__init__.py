# Expose package version at root of package
from django import VERSION as DJANGO_VERSION

from ._version import VERSION, __version__  # NOQA: F401

if DJANGO_VERSION < (3, 2, 0):
    default_app_config = "anymail.apps.AnymailBaseConfig"
