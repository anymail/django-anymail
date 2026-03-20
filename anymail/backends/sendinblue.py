from __future__ import annotations

import warnings

from ..exceptions import AnymailDeprecationWarning
from .brevo import EmailBackend as BrevoEmailBackend


class EmailBackend(BrevoEmailBackend):
    """
    Deprecated compatibility backend for old Brevo name "SendinBlue".
    """

    esp_name = "SendinBlue"

    def __init__(self, **kwargs):
        warnings.warn(
            "`anymail.backends.sendinblue.EmailBackend` has been renamed"
            " `anymail.backends.brevo.EmailBackend`.",
            AnymailDeprecationWarning,
        )
        super().__init__(**kwargs)
