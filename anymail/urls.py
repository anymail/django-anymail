from django.urls import re_path

from .webhooks.amazon_ses import AmazonSESInboundWebhookView, AmazonSESTrackingWebhookView
from .webhooks.mailgun import MailgunInboundWebhookView, MailgunTrackingWebhookView
from .webhooks.mailjet import MailjetInboundWebhookView, MailjetTrackingWebhookView
from .webhooks.mandrill import MandrillCombinedWebhookView
from .webhooks.postal import PostalInboundWebhookView, PostalTrackingWebhookView
from .webhooks.postmark import PostmarkInboundWebhookView, PostmarkTrackingWebhookView
from .webhooks.sendgrid import SendGridInboundWebhookView, SendGridTrackingWebhookView
from .webhooks.sendinblue import SendinBlueTrackingWebhookView
from .webhooks.sparkpost import SparkPostInboundWebhookView, SparkPostTrackingWebhookView


app_name = 'anymail'
urlpatterns = [
    re_path(r'^amazon_ses/inbound/$', AmazonSESInboundWebhookView.as_view(), name='amazon_ses_inbound_webhook'),
    re_path(r'^mailgun/inbound(_mime)?/$', MailgunInboundWebhookView.as_view(), name='mailgun_inbound_webhook'),
    re_path(r'^mailjet/inbound/$', MailjetInboundWebhookView.as_view(), name='mailjet_inbound_webhook'),
    re_path(r'^postal/inbound/$', PostalInboundWebhookView.as_view(), name='postal_inbound_webhook'),
    re_path(r'^postmark/inbound/$', PostmarkInboundWebhookView.as_view(), name='postmark_inbound_webhook'),
    re_path(r'^sendgrid/inbound/$', SendGridInboundWebhookView.as_view(), name='sendgrid_inbound_webhook'),
    re_path(r'^sparkpost/inbound/$', SparkPostInboundWebhookView.as_view(), name='sparkpost_inbound_webhook'),

    re_path(r'^amazon_ses/tracking/$', AmazonSESTrackingWebhookView.as_view(), name='amazon_ses_tracking_webhook'),
    re_path(r'^mailgun/tracking/$', MailgunTrackingWebhookView.as_view(), name='mailgun_tracking_webhook'),
    re_path(r'^mailjet/tracking/$', MailjetTrackingWebhookView.as_view(), name='mailjet_tracking_webhook'),
    re_path(r'^postal/tracking/$', PostalTrackingWebhookView.as_view(), name='postal_tracking_webhook'),
    re_path(r'^postmark/tracking/$', PostmarkTrackingWebhookView.as_view(), name='postmark_tracking_webhook'),
    re_path(r'^sendgrid/tracking/$', SendGridTrackingWebhookView.as_view(), name='sendgrid_tracking_webhook'),
    re_path(r'^sendinblue/tracking/$', SendinBlueTrackingWebhookView.as_view(), name='sendinblue_tracking_webhook'),
    re_path(r'^sparkpost/tracking/$', SparkPostTrackingWebhookView.as_view(), name='sparkpost_tracking_webhook'),

    # Anymail uses a combined Mandrill webhook endpoint, to simplify Mandrill's key-validation scheme:
    re_path(r'^mandrill/$', MandrillCombinedWebhookView.as_view(), name='mandrill_webhook'),
    # This url is maintained for backwards compatibility with earlier Anymail releases:
    re_path(r'^mandrill/tracking/$', MandrillCombinedWebhookView.as_view(), name='mandrill_tracking_webhook'),
]
