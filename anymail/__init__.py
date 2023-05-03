from ._version import VERSION, __version__

__all__ = [
    "VERSION",
    "__version__",
]

try:
    import django
except ImportError:
    # (don't require django just to get package version)
    pass
else:
    if django.VERSION < (3, 2, 0):
        # (No longer required -- and causes deprecation warning -- in Django 3.2+)
        default_app_config = "anymail.apps.AnymailBaseConfig"
        __all__.append("default_app_config")
