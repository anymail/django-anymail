# Expose package version at root of package
from ._version import __version__, VERSION  # NOQA: F401


from django import VERSION as DJANGO_VERSION
if DJANGO_VERSION < (3, 2, 0):
    default_app_config = 'anymail.apps.AnymailBaseConfig'
