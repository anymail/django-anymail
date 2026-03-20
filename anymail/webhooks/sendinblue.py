from __future__ import annotations

import warnings

from ..exceptions import AnymailDeprecationWarning
from .brevo import BrevoInboundWebhookView, BrevoTrackingWebhookView


class SendinBlueTrackingWebhookView(BrevoTrackingWebhookView):
    """
    Deprecated compatibility tracking webhook for old Brevo name "SendinBlue".
    """

    esp_name = "SendinBlue"

    def __init__(self, **kwargs):
        warnings.warn(
            "Anymail's SendinBlue webhook URLs are deprecated."
            " Update your Brevo transactional email webhook URL to change"
            " 'anymail/sendinblue' to 'anymail/brevo'.",
            AnymailDeprecationWarning,
        )
        super().__init__(**kwargs)


class SendinBlueInboundWebhookView(BrevoInboundWebhookView):
    """
    Deprecated compatibility inbound webhook for old Brevo name "SendinBlue".
    """

    esp_name = "SendinBlue"

    def __init__(self, **kwargs):
        warnings.warn(
            "Anymail's SendinBlue webhook URLs are deprecated."
            " Update your Brevo inbound webhook URL to change"
            " 'anymail/sendinblue' to 'anymail/brevo'.",
            AnymailDeprecationWarning,
        )
        super().__init__(**kwargs)
