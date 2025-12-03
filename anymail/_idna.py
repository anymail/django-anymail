# Pre-packaged IDNA_ENCODER options
import idna

from anymail.exceptions import AnymailImproperlyInstalled, _LazyError

try:
    from uts46 import encode as uts46_encode
except ImportError:
    uts46_encode = _LazyError(
        AnymailImproperlyInstalled("uts46", "<your-esp>,uts46", 'IDNA_ENCODER="uts46"')
    )

__all__ = ["idna2003", "idna2008", "uts46", "none"]


def idna2003(domain: str) -> str:
    """
    Encode domain (if necessary) using IDNA 2003 standard.
    This matches Django's own behavior and requires no extra libraries.
    But it will fail to encode some newer IDNs that require IDNA 2008, and
    it will use obsolete encoding for IDNs that contain deviation characters.
    """
    return domain.encode("idna").decode("ascii")


def idna2008(domain: str) -> str:
    """
    Encode domain (if necessary) using the IDNA 2008 standard
    with UTS46 preprocessing. (Preprocessing is required to handle
    case insensitivity most users would expect.)

    Will reject some domains (e.g., emojis) that browsers allow.
    Relies on the third-party 'idna' package (installed with django-anymail).
    """
    return idna.encode(domain, uts46=True).decode("ascii")


def uts46(domain: str) -> str:
    """
    Encode domain (if necessary) using the UTS46 standard.
    This is the encoding used by all modern browsers.

    Requires the 'uts46' package (installable via 'django-anymail[uts46]' extra).
    """
    return uts46_encode(domain).decode("ascii")


def none(domain: str) -> str:
    """
    Leaves domain as unencoded Unicode characters.
    Can be used with an ESP whose API correctly handles IDNA encoding.
    """
    return domain
