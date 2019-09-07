VERSION = (7, 0, 0)
__version__ = '.'.join([str(x) for x in VERSION])  # major.minor.patch or major.minor.devN
__minor_version__ = '.'.join([str(x) for x in VERSION[:2]])  # Sphinx's X.Y "version"
