from django.urls import path, re_path

from .webhooks.amazon_ses import (
    AmazonSESInboundWebhookView,
    AmazonSESTrackingWebhookView,
)
from .webhooks.mailersend import (
    MailerSendInboundWebhookView,
    MailerSendTrackingWebhookView,
)
from .webhooks.mailgun import MailgunInboundWebhookView, MailgunTrackingWebhookView
from .webhooks.mailjet import MailjetInboundWebhookView, MailjetTrackingWebhookView
from .webhooks.mandrill import MandrillCombinedWebhookView
from .webhooks.postal import PostalInboundWebhookView, PostalTrackingWebhookView
from .webhooks.postmark import PostmarkInboundWebhookView, PostmarkTrackingWebhookView
from .webhooks.resend import ResendTrackingWebhookView
from .webhooks.sendgrid import SendGridInboundWebhookView, SendGridTrackingWebhookView
from .webhooks.sendinblue import (
    SendinBlueInboundWebhookView,
    SendinBlueTrackingWebhookView,
)
from .webhooks.sparkpost import (
    SparkPostInboundWebhookView,
    SparkPostTrackingWebhookView,
)

app_name = "anymail"
urlpatterns = [
    path(
        "amazon_ses/inbound/",
        AmazonSESInboundWebhookView.as_view(),
        name="amazon_ses_inbound_webhook",
    ),
    path(
        "mailersend/inbound/",
        MailerSendInboundWebhookView.as_view(),
        name="mailersend_inbound_webhook",
    ),
    re_path(
        # Mailgun delivers inbound messages differently based on whether
        # the webhook url contains "mime" (anywhere). You can use either
        # ".../mailgun/inbound/" or ".../mailgun/inbound_mime/" depending
        # on the behavior you want.
        r"^mailgun/inbound(_mime)?/$",
        MailgunInboundWebhookView.as_view(),
        name="mailgun_inbound_webhook",
    ),
    path(
        "mailjet/inbound/",
        MailjetInboundWebhookView.as_view(),
        name="mailjet_inbound_webhook",
    ),
    path(
        "postal/inbound/",
        PostalInboundWebhookView.as_view(),
        name="postal_inbound_webhook",
    ),
    path(
        "postmark/inbound/",
        PostmarkInboundWebhookView.as_view(),
        name="postmark_inbound_webhook",
    ),
    path(
        "sendgrid/inbound/",
        SendGridInboundWebhookView.as_view(),
        name="sendgrid_inbound_webhook",
    ),
    path(
        "sendinblue/inbound/",
        SendinBlueInboundWebhookView.as_view(),
        name="sendinblue_inbound_webhook",
    ),
    path(
        "sparkpost/inbound/",
        SparkPostInboundWebhookView.as_view(),
        name="sparkpost_inbound_webhook",
    ),
    path(
        "amazon_ses/tracking/",
        AmazonSESTrackingWebhookView.as_view(),
        name="amazon_ses_tracking_webhook",
    ),
    path(
        "mailersend/tracking/",
        MailerSendTrackingWebhookView.as_view(),
        name="mailersend_tracking_webhook",
    ),
    path(
        "mailgun/tracking/",
        MailgunTrackingWebhookView.as_view(),
        name="mailgun_tracking_webhook",
    ),
    path(
        "mailjet/tracking/",
        MailjetTrackingWebhookView.as_view(),
        name="mailjet_tracking_webhook",
    ),
    path(
        "postal/tracking/",
        PostalTrackingWebhookView.as_view(),
        name="postal_tracking_webhook",
    ),
    path(
        "postmark/tracking/",
        PostmarkTrackingWebhookView.as_view(),
        name="postmark_tracking_webhook",
    ),
    path(
        "resend/tracking/",
        ResendTrackingWebhookView.as_view(),
        name="resend_tracking_webhook",
    ),
    path(
        "sendgrid/tracking/",
        SendGridTrackingWebhookView.as_view(),
        name="sendgrid_tracking_webhook",
    ),
    path(
        "sendinblue/tracking/",
        SendinBlueTrackingWebhookView.as_view(),
        name="sendinblue_tracking_webhook",
    ),
    path(
        "sparkpost/tracking/",
        SparkPostTrackingWebhookView.as_view(),
        name="sparkpost_tracking_webhook",
    ),
    # Anymail uses a combined Mandrill webhook endpoint,
    # to simplify Mandrill's key-validation scheme:
    path("mandrill/", MandrillCombinedWebhookView.as_view(), name="mandrill_webhook"),
    # This url is maintained for backwards compatibility with earlier Anymail releases:
    path(
        "mandrill/tracking/",
        MandrillCombinedWebhookView.as_view(),
        name="mandrill_tracking_webhook",
    ),
]
