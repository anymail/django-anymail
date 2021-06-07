.. _amazon-ses-backend:

Amazon SES
==========

Anymail integrates with `Amazon Simple Email Service`_ (SES) using the `Boto 3`_
AWS SDK for Python, and includes sending, tracking, and inbound receiving capabilities.

.. sidebar:: Alternatives

    At least two other packages offer Django integration with
    Amazon SES: :pypi:`django-amazon-ses` and :pypi:`django-ses`.
    Depending on your needs, one of them may be more appropriate than Anymail.


.. _Amazon Simple Email Service: https://aws.amazon.com/ses/
.. _Boto 3: https://boto3.readthedocs.io/en/stable/


Installation
------------

You must ensure the :pypi:`boto3` package is installed to use Anymail's Amazon SES
backend. Either include the "amazon_ses" option when you install Anymail:

    .. code-block:: console

        $ pip install "django-anymail[amazon_ses]"

or separately run `pip install boto3`.

To send mail with Anymail's Amazon SES backend, set:

  .. code-block:: python

      EMAIL_BACKEND = "anymail.backends.amazon_ses.EmailBackend"

in your settings.py.

In addition, you must make sure boto3 is configured with AWS credentials having the
necessary :ref:`amazon-ses-iam-permissions`.
There are several ways to do this; see `Credentials`_ in the Boto docs for options.
Usually, an IAM role for EC2 instances, standard Boto environment variables,
or a shared AWS credentials file will be appropriate. For more complex cases,
use Anymail's :setting:`AMAZON_SES_CLIENT_PARAMS <ANYMAIL_AMAZON_SES_CLIENT_PARAMS>`
setting to customize the Boto session.


.. _Credentials: https://boto3.readthedocs.io/en/stable/guide/configuration.html#configuring-credentials


.. _amazon-ses-quirks:

Limitations and quirks
----------------------

**Hard throttling**
  Like most ESPs, Amazon SES `throttles sending`_ for new customers. But unlike
  most ESPs, SES does not queue and slowly release throttled messages. Instead, it
  hard-fails the send API call. A strategy for :ref:`retrying errors <transient-errors>`
  is required with any ESP; you're likely to run into it right away with Amazon SES.

**Tags limitations**
  Amazon SES's handling for tags is a bit different from other ESPs.
  Anymail tries to provide a useful, portable default behavior for its
  :attr:`~anymail.message.AnymailMessage.tags` feature. See :ref:`amazon-ses-tags`
  below for more information and additional options.

**No merge_metadata**
  Amazon SES's batch sending API does not support the custom headers Anymail uses
  for metadata, so Anymail's :attr:`~anymail.message.AnymailMessage.merge_metadata`
  feature is not available. (See :ref:`amazon-ses-tags` below for more information.)

**Open and click tracking overrides**
  Anymail's :attr:`~anymail.message.AnymailMessage.track_opens` and
  :attr:`~anymail.message.AnymailMessage.track_clicks` are not supported.
  Although Amazon SES *does* support open and click tracking, it doesn't offer
  a simple mechanism to override the settings for individual messages. If you
  need this feature, provide a custom ConfigurationSetName in Anymail's
  :ref:`esp_extra <amazon-ses-esp-extra>`.

**No delayed sending**
  Amazon SES does not support :attr:`~anymail.message.AnymailMessage.send_at`.

**No global send defaults for non-Anymail options**
  With the Amazon SES backend, Anymail's :ref:`global send defaults <send-defaults>`
  are only supported for Anymail's added message options (like
  :attr:`~anymail.message.AnymailMessage.metadata` and
  :attr:`~anymail.message.AnymailMessage.esp_extra`), not for standard EmailMessage
  attributes like `bcc` or `from_email`.

**Arbitrary alternative parts allowed**
  Amazon SES is one of the few ESPs that *does* support sending arbitrary alternative
  message parts (beyond just a single text/plain and text/html part).

**AMP for Email**
  Amazon SES supports sending AMPHTML email content. To include it, use
  ``message.attach_alternative("...AMPHTML content...", "text/x-amp-html")``
  (and be sure to also include regular HTML and text bodies, too).

**Spoofed To header and multiple From emails allowed**
  Amazon SES is one of the few ESPs that supports spoofing the :mailheader:`To` header
  (see :ref:`message-headers`) and supplying multiple addresses in a message's `from_email`.
  (Most ISPs consider these to be very strong spam signals, and using either them will almost
  certainly prevent delivery of your mail.)

**Template limitations**
  Messages sent with templates have a number of additional limitations, such as not
  supporting attachments. See :ref:`amazon-ses-templates` below.


.. _throttles sending:
   https://docs.aws.amazon.com/ses/latest/DeveloperGuide/manage-sending-limits.html

.. _amazon-ses-tags:

Tags and metadata
-----------------

Amazon SES provides two mechanisms for associating additional data with sent messages,
which Anymail uses to implement its :attr:`~anymail.message.AnymailMessage.tags`
and :attr:`~anymail.message.AnymailMessage.metadata` features:

* **SES Message Tags** can be used for filtering or segmenting CloudWatch metrics and
  dashboards, and are available to Kinesis Firehose streams. (See "How do message
  tags work?" in the Amazon blog post `Introducing Sending Metrics`_.)

  By default, Anymail does *not* use SES Message Tags. They have strict limitations
  on characters allowed, and are not consistently available to tracking webhooks.
  (They may be included in `SES Event Publishing`_ but not `SES Notifications`_.)

* **Custom Email Headers** are available to all SNS notifications (webhooks), but
  not to CloudWatch or Kinesis.

  These are ordinary extension headers included in the sent message (and visible to
  recipients who view the full headers). There are no restrictions on characters allowed.

By default, Anymail uses only custom email headers. A message's
:attr:`~anymail.message.AnymailMessage.metadata` is sent JSON-encoded in a custom
:mailheader:`X-Metadata` header, and a message's :attr:`~anymail.message.AnymailMessage.tags`
are sent in custom :mailheader:`X-Tag` headers. Both are available in Anymail's
:ref:`tracking webhooks <amazon-ses-webhooks>`.

Because Anymail :attr:`~anymail.message.AnymailMessage.tags` are often used for
segmenting reports, Anymail has an option to easily send an Anymail tag
as an SES Message Tag that can be used in CloudWatch. Set the Anymail setting
:setting:`AMAZON_SES_MESSAGE_TAG_NAME <ANYMAIL_AMAZON_SES_MESSAGE_TAG_NAME>`
to the name of an SES Message Tag whose value will be the *single* Anymail tag
on the message. For example, with this setting:

  .. code-block:: python

      ANYMAIL = {
          ...
          "AMAZON_SES_MESSAGE_TAG_NAME": "Type",
      }

this send will appear in CloudWatch with the SES Message Tag `"Type": "Marketing"`:

  .. code-block:: python

      message = EmailMessage(...)
      message.tags = ["Marketing"]
      message.send()

Anymail's :setting:`AMAZON_SES_MESSAGE_TAG_NAME <ANYMAIL_AMAZON_SES_MESSAGE_TAG_NAME>`
setting is disabled by default. If you use it, then only a single tag is supported,
and both the tag and the name must be limited to alphanumeric, hyphen, and underscore
characters.

For more complex use cases, set the SES `Tags` parameter directly in Anymail's
:ref:`esp_extra <amazon-ses-esp-extra>`. See the example below. (Because custom headers do not
work with SES's SendBulkTemplatedEmail call, esp_extra Tags is the only way to attach
data to SES messages also using Anymail's :attr:`~anymail.message.AnymailMessage.template_id`
and :attr:`~anymail.message.AnymailMessage.merge_data` features, and the
:attr:`~anymail.message.AnymailMessage.merge_metadata` cannot be supported.)


.. _Introducing Sending Metrics:
    https://aws.amazon.com/blogs/ses/introducing-sending-metrics/
.. _SES Event Publishing:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/monitor-using-event-publishing.html
.. _SES Notifications:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/monitor-sending-using-notifications.html


.. _amazon-ses-esp-extra:

esp_extra support
-----------------

To use Amazon SES features not directly supported by Anymail, you can
set a message's :attr:`~anymail.message.AnymailMessage.esp_extra` to
a `dict` that will be merged into the params for the `SendRawEmail`_
or `SendBulkTemplatedEmail`_ SES API call.

Example:

    .. code-block:: python

        message.esp_extra = {
            # Override AMAZON_SES_CONFIGURATION_SET_NAME for this message
            'ConfigurationSetName': 'NoOpenOrClickTrackingConfigSet',
            # Authorize a custom sender
            'SourceArn': 'arn:aws:ses:us-east-1:123456789012:identity/example.com',
            # Set Amazon SES Message Tags
            'Tags': [
                # (Names and values must be A-Z a-z 0-9 - and _ only)
                {'Name': 'UserID', 'Value': str(user_id)},
                {'Name': 'TestVariation', 'Value': 'Subject-Emoji-Trial-A'},
            ],
        }


(You can also set `"esp_extra"` in Anymail's :ref:`global send defaults <send-defaults>`
to apply it to all messages.)

.. _SendRawEmail:
    https://docs.aws.amazon.com/ses/latest/APIReference/API_SendRawEmail.html

.. _SendBulkTemplatedEmail:
    https://docs.aws.amazon.com/ses/latest/APIReference/API_SendBulkTemplatedEmail.html


.. _amazon-ses-templates:

Batch sending/merge and ESP templates
-------------------------------------

Amazon SES offers :ref:`ESP stored templates <esp-stored-templates>`
and :ref:`batch sending <batch-send>` with per-recipient merge data.
See Amazon's `Sending personalized email`_ guide for more information.

When you set a message's :attr:`~anymail.message.AnymailMessage.template_id`
to the name of one of your SES templates, Anymail will use the SES
`SendBulkTemplatedEmail`_ call to send template messages personalized with data
from Anymail's normalized :attr:`~anymail.message.AnymailMessage.merge_data`
and :attr:`~anymail.message.AnymailMessage.merge_global_data`
message attributes.

  .. code-block:: python

      message = EmailMessage(
          from_email="shipping@example.com",
          # you must omit subject and body (or set to None) with Amazon SES templates
          to=["alice@example.com", "Bob <bob@example.com>"]
      )
      message.template_id = "MyTemplateName"  # Amazon SES TemplateName
      message.merge_data = {
          'alice@example.com': {'name': "Alice", 'order_no': "12345"},
          'bob@example.com': {'name': "Bob", 'order_no': "54321"},
      }
      message.merge_global_data = {
          'ship_date': "May 15",
      }

Amazon's templated email APIs don't support several features available for regular email.
When :attr:`~anymail.message.AnymailMessage.template_id` is used:

* Attachments and alternative parts (including AMPHTML) are not supported
* Extra headers are not supported
* Overriding the template's subject or body is not supported
* Anymail's :attr:`~anymail.message.AnymailMessage.metadata` is not supported
* Anymail's :attr:`~anymail.message.AnymailMessage.tags` are only supported
  with the :setting:`AMAZON_SES_MESSAGE_TAG_NAME <ANYMAIL_AMAZON_SES_MESSAGE_TAG_NAME>`
  setting; only a single tag is allowed, and the tag is not directly available
  to webhooks. (See :ref:`amazon-ses-tags` above.)

.. _Sending personalized email:
   https://docs.aws.amazon.com/ses/latest/DeveloperGuide/send-personalized-email-api.html


.. _amazon-ses-webhooks:

Status tracking webhooks
------------------------

Anymail can provide normalized :ref:`status tracking <event-tracking>` notifications
for messages sent through Amazon SES. SES offers two (confusingly) similar kinds of
tracking, and Anymail supports both:

* `SES Notifications`_ include delivered, bounced, and complained (spam) Anymail
  :attr:`~anymail.signals.AnymailTrackingEvent.event_type`\s. (Enabling these
  notifications may allow you to disable SES "email feedback forwarding.")

* `SES Event Publishing`_ also includes delivered, bounced and complained events,
  as well as sent, rejected, opened, clicked, and (template rendering) failed.

Both types of tracking events are delivered to Anymail's webhook URL through
Amazon Simple Notification Service (SNS) subscriptions.

Amazon's naming here can be really confusing. We'll try to be clear about "SES Notifications"
vs. "SES Event Publishing" as the two different kinds of SES tracking events.
And then distinguish all of that from "SNS"---the publish/subscribe service
used to notify Anymail's tracking webhooks about *both* kinds of SES tracking event.

To use Anymail's status tracking webhooks with Amazon SES:

1. First, :ref:`configure Anymail webhooks <webhooks-configuration>` and deploy your
   Django project. (Deploying allows Anymail to confirm the SNS subscription for you
   in step 3.)

Then in Amazon's **Simple Notification Service** console:

2. `Create an SNS Topic`_ to receive Amazon SES tracking events.
   The exact topic name is up to you; choose something meaningful like *SES_Tracking_Events*.

3. Subscribe Anymail's tracking webhook to the SNS Topic you just created. In the SNS
   console, click into the topic from step 2, then click the "Create subscription" button.
   For protocol choose HTTPS. For endpoint enter:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/amazon_ses/tracking/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

   Anymail will automatically confirm the SNS subscription. (For other options, see
   :ref:`amazon-ses-confirm-sns-subscriptions` below.)

Finally, switch to Amazon's **Simple Email Service** console:

4. **If you want to use SES Notifications:** Follow Amazon's guide to
   `configure SES notifications through SNS`_, using the SNS Topic you created above.
   Choose any event types you want to receive. Be sure to choose "Include original headers"
   if you need access to Anymail's :attr:`~anymail.message.AnymailMessage.metadata` or
   :attr:`~anymail.message.AnymailMessage.tags` in your webhook handlers.

5. **If you want to use SES Event Publishing:**

    a. Follow Amazon's guide to `create an SES "Configuration Set"`_. Name it something meaningful,
       like *TrackingConfigSet.*

    b. Follow Amazon's guide to `add an SNS event destination for SES event publishing`_, using the
       SNS Topic you created above. Choose any event types you want to receive.

    c. Update your Anymail settings to send using this Configuration Set by default:

        .. code-block:: python

            ANYMAIL = {
                ...
                "AMAZON_SES_CONFIGURATION_SET_NAME": "TrackingConfigSet",
            }

.. caution::

    The delivery, bounce, and complaint event types are available in both SES Notifications
    *and* SES Event Publishing. If you're using both, don't enable the same events in both
    places, or you'll receive duplicate notifications with *different*
    :attr:`~anymail.signals.AnymailTrackingEvent.event_id`\s.


Note that Amazon SES's open and click tracking does not distinguish individual recipients.
If you send a single message to multiple recipients, Anymail will call your tracking handler
with the "opened" or "clicked" event for *every* original recipient of the message, including
all to, cc and bcc addresses. (Amazon recommends avoiding multiple recipients with SES.)

In your tracking signal receiver, the normalized AnymailTrackingEvent's
:attr:`~anymail.signals.AnymailTrackingEvent.esp_event` will be set to the
the parsed, top-level JSON event object from SES: either `SES Notification contents`_
or `SES Event Publishing contents`_. (The two formats are nearly identical.)
You can use this to obtain SES Message Tags (see :ref:`amazon-ses-tags`) from
SES Event Publishing notifications:

.. code-block:: python

    from anymail.signals import tracking
    from django.dispatch import receiver

    @receiver(tracking)  # add weak=False if inside some other function/class
    def handle_tracking(sender, event, esp_name, **kwargs):
        if esp_name == "Amazon SES":
            try:
                message_tags = {
                    name: values[0]
                    for name, values in event.esp_event["mail"]["tags"].items()}
            except KeyError:
                message_tags = None  # SES Notification (not Event Publishing) event
            print("Message %s to %s event %s: Message Tags %r" % (
                  event.message_id, event.recipient, event.event_type, message_tags))


Anymail does *not* currently check `SNS signature verification`_, because Amazon has not
released a standard way to do that in Python. Instead, Anymail relies on your
:setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>` to verify SNS notifications are from an
authorized source.

.. _amazon-ses-sns-retry-policy:

.. note::

    Amazon SNS's default policy for handling HTTPS notification failures is to retry
    three times, 20 seconds apart, and then drop the notification. That means
    **if your webhook is ever offline for more than one minute, you may miss events.**

    For most uses, it probably makes sense to `configure an SNS retry policy`_ with more
    attempts over a longer period. E.g., 20 retries ranging from 5 seconds minimum
    to 600 seconds (5 minutes) maximum delay between attempts, with geometric backoff.

    Also, SNS does *not* guarantee notifications will be delivered to HTTPS subscribers
    like Anymail webhooks. The longest SNS will ever keep retrying is one hour total. If you need
    retries longer than that, or guaranteed delivery, you may need to implement your own queuing
    mechanism with something like Celery or directly on Amazon Simple Queue Service (SQS).


.. _Create an SNS Topic:
    https://docs.aws.amazon.com/sns/latest/dg/CreateTopic.html
.. _configure SES notifications through SNS:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/configure-sns-notifications.html
.. _create an SES "Configuration Set":
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/event-publishing-create-configuration-set.html
.. _add an SNS event destination for SES event publishing:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/event-publishing-add-event-destination-sns.html
.. _SES Notification contents:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-contents.html
.. _SES Event Publishing contents:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/event-publishing-retrieving-sns-contents.html
.. _SNS signature verification:
    https://docs.aws.amazon.com/sns/latest/dg/SendMessageToHttp.verify.signature.html
.. _configure an SNS retry policy:
    https://docs.aws.amazon.com/sns/latest/dg/DeliveryPolicies.html


.. _amazon-ses-inbound:

Inbound webhook
---------------

You can receive email through Amazon SES with Anymail's normalized :ref:`inbound <inbound>`
handling. See `Receiving email with Amazon SES`_ for background.

Configuring Anymail's inbound webhook for Amazon SES is similar to installing the
:ref:`tracking webhook <amazon-ses-webhooks>`. You must use a different SNS Topic
for inbound.

To use Anymail's inbound webhook with Amazon SES:

1. First, if you haven't already, :ref:`configure Anymail webhooks <webhooks-configuration>`
   and deploy your Django project. (Deploying allows Anymail to confirm the SNS subscription
   for you in step 3.)

2. `Create an SNS Topic`_ to receive Amazon SES inbound events.
   The exact topic name is up to you; choose something meaningful like *SES_Inbound_Events*.
   (If you are also using Anymail's tracking events, this must be a *different* SNS Topic.)

3. Subscribe Anymail's inbound webhook to the SNS Topic you just created. In the SNS
   console, click into the topic from step 2, then click the "Create subscription" button.
   For protocol choose HTTPS. For endpoint enter:

   :samp:`https://{random}:{random}@{yoursite.example.com}/anymail/amazon_ses/inbound/`

     * *random:random* is an :setting:`ANYMAIL_WEBHOOK_SECRET` shared secret
     * *yoursite.example.com* is your Django site

   Anymail will automatically confirm the SNS subscription. (For other options, see
   :ref:`amazon-ses-confirm-sns-subscriptions` below.)

4. Next, follow Amazon's guide to `Setting up Amazon SES email receiving`_.
   There are several steps. Come back here when you get to "Action Options"
   in the last step, "Creating Receipt Rules."

5. Anymail supports two SES receipt actions: S3 and SNS. (Both actually use SNS.)
   You can choose either one: the SNS action is easier to set up, but the S3 action
   allows you to receive larger messages and can be more robust.
   (You can change at any time, but don't use both simultaneously.)

   * **For the SNS action:** choose the SNS Topic you created in step 2. Anymail will handle
     either Base64 or UTF-8 encoding; use Base64 if you're not sure.

   * **For the S3 action:** choose or create any S3 bucket that Boto will be able to read.
     (See :ref:`amazon-ses-iam-permissions`; *don't* use a world-readable bucket!)
     "Object key prefix" is optional. Anymail does *not* currently support the
     "Encrypt message" option. Finally, choose the SNS Topic you created in step 2.

Amazon SES will likely deliver a test message to your Anymail inbound handler immediately
after you complete the last step.

If you are using the S3 receipt action, note that Anymail does not delete the S3 object.
You can delete it from your code after successful processing, or set up S3 bucket policies
to automatically delete older messages. In your inbound handler, you can retrieve the S3
object key by prepending the "object key prefix" (if any) from your receipt rule to Anymail's
:attr:`event.event_id <anymail.signals.AnymailInboundEvent.event_id>`.

Amazon SNS imposes a 15 second limit on all notifications. This includes time to download
the message (if you are using the S3 receipt action) and any processing in your
signal receiver. If the total takes longer, SNS will consider the notification failed
and will make several repeat attempts. To avoid problems, it's essential any lengthy
operations are offloaded to a background task.

Amazon SNS's default retry policy times out after one minute of failed notifications.
If your webhook is ever unreachable for more than a minute, **you may miss inbound mail.**
You'll probably want to adjust your SNS topic settings to reduce the chances of that.
See the note about :ref:`retry policies <amazon-ses-sns-retry-policy>` in the tracking
webhooks discussion above.

In your inbound signal receiver, the normalized AnymailTrackingEvent's
:attr:`~anymail.signals.AnymailTrackingEvent.esp_event` will be set to the
the parsed, top-level JSON object described in `SES Email Receiving contents`_.

.. _Receiving email with Amazon SES:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/receiving-email.html
.. _Setting up Amazon SES email receiving:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/receiving-email-setting-up.html
.. _SES Email Receiving contents:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/receiving-email-notifications-contents.html


.. _amazon-ses-confirm-sns-subscriptions:

Confirming SNS subscriptions
----------------------------

Amazon SNS requires HTTPS endpoints (webhooks) to confirm they actually want to subscribe
to an SNS Topic. See `Sending SNS messages to HTTPS endpoints`_ in the Amazon SNS docs
for more information.

(This has nothing to do with verifying email identities in Amazon *SES*,
and is not related to email recipients confirming subscriptions to your content.)

Anymail will automatically handle SNS endpoint confirmation for you, for both tracking and inbound
webhooks, if both:

1. You have deployed your Django project with :ref:`Anymail webhooks enabled <webhooks-configuration>`
   and an Anymail :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>` set, **before** subscribing the SNS Topic
   to the webhook URL.

   .. caution::

      If you create the SNS subscription *before* deploying your Django project with the webhook secret
      set, confirmation will fail and you will need to **re-create the subscription** by entering the
      full URL and webhook secret into the SNS console again.

      You **cannot** use the SNS console's "Request confirmation" button to re-try confirmation.
      (That will fail due to an `SNS console bug`_ that sends authentication as asterisks,
      rather than the username:password secret you originally entered.)

2. The SNS endpoint URL includes the correct Anymail :setting:`WEBHOOK_SECRET <ANYMAIL_WEBHOOK_SECRET>`
   as HTTP basic authentication. (Amazon SNS only allows this with https urls, not plain http.)

   Anymail requires a valid secret to ensure the subscription request is coming from you, not some other
   AWS user.

If you do not want Anymail to automatically confirm SNS subscriptions for its webhook URLs, set
:setting:`AMAZON_SES_AUTO_CONFIRM_SNS_SUBSCRIPTIONS <ANYMAIL_AMAZON_SES_AUTO_CONFIRM_SNS_SUBSCRIPTIONS>`
to `False` in your ANYMAIL settings.

When auto-confirmation is disabled (or if Anymail receives an unexpected confirmation request),
it will raise an :exc:`AnymailWebhookValidationFailure`, which should show up in your Django error
logging. The error message will include the Token you can use to manually confirm the subscription
in the Amazon SNS console or through the SNS API.


.. _Sending SNS messages to HTTPS endpoints:
    https://docs.aws.amazon.com/sns/latest/dg/SendMessageToHttp.html
.. _SNS console bug:
    https://github.com/anymail/django-anymail/issues/194#issuecomment-665350148


.. _amazon-ses-settings:

Settings
--------

Additional Anymail settings for use with Amazon SES:

.. setting:: ANYMAIL_AMAZON_SES_CLIENT_PARAMS

.. rubric:: AMAZON_SES_CLIENT_PARAMS

Optional. Additional `client parameters`_ Anymail should use to create the boto3 session client. Example:

  .. code-block:: python

      ANYMAIL = {
          ...
          "AMAZON_SES_CLIENT_PARAMS": {
              # example: override normal Boto credentials specifically for Anymail
              "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_FOR_ANYMAIL_SES"),
              "aws_secret_access_key": os.getenv("AWS_SECRET_KEY_FOR_ANYMAIL_SES"),
              "region_name": "us-west-2",
              # override other default options
              "config": {
                  "connect_timeout": 30,
                  "read_timeout": 30,
              }
          },
      }

In most cases, it's better to let Boto obtain its own credentials through one of its other
mechanisms: an IAM role for EC2 instances, standard AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
and AWS_SESSION_TOKEN environment variables, or a shared AWS credentials file.

.. _client parameters:
    https://boto3.readthedocs.io/en/stable/reference/core/session.html#boto3.session.Session.client


.. setting:: ANYMAIL_AMAZON_SES_SESSION_PARAMS

.. rubric:: AMAZON_SES_SESSION_PARAMS

Optional. Additional `session parameters`_ Anymail should use to create the boto3 Session. Example:

  .. code-block:: python

      ANYMAIL = {
          ...
          "AMAZON_SES_SESSION_PARAMS": {
              "profile_name": "anymail-testing",
          },
      }

.. _session parameters:
    https://boto3.readthedocs.io/en/stable/reference/core/session.html#boto3.session.Session


.. setting:: ANYMAIL_AMAZON_SES_CONFIGURATION_SET_NAME

.. rubric:: AMAZON_SES_CONFIGURATION_SET_NAME

Optional. The name of an Amazon SES `Configuration Set`_ Anymail should use when sending messages.
The default is to send without any Configuration Set. Note that a Configuration Set is
required to receive SES Event Publishing tracking events. See :ref:`amazon-ses-webhooks` above.

You can override this for individual messages with :ref:`esp_extra <amazon-ses-esp-extra>`.

.. _Configuration Set:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/using-configuration-sets.html


.. setting:: ANYMAIL_AMAZON_SES_MESSAGE_TAG_NAME

.. rubric:: AMAZON_SES_MESSAGE_TAG_NAME

Optional, default `None`. The name of an Amazon SES "Message Tag" whose value is set
from a message's Anymail :attr:`~anymail.message.AnymailMessage.tags`.
See :ref:`amazon-ses-tags` above.


.. setting:: ANYMAIL_AMAZON_SES_AUTO_CONFIRM_SNS_SUBSCRIPTIONS

.. rubric:: AMAZON_SES_AUTO_CONFIRM_SNS_SUBSCRIPTIONS

Optional boolean, default `True`. Set to `False` to prevent Anymail webhooks from automatically
accepting Amazon SNS subscription confirmation requests.
See :ref:`amazon-ses-confirm-sns-subscriptions` above.


.. _amazon-ses-iam-permissions:

IAM permissions
---------------

Anymail requires IAM permissions that will allow it to use these actions:

* To send mail:

  * Ordinary (non-templated) sends: ``ses:SendRawEmail``
  * Template/merge sends: ``ses:SendBulkTemplatedEmail``

* To :ref:`automatically confirm <amazon-ses-confirm-sns-subscriptions>`
  webhook SNS subscriptions: ``sns:ConfirmSubscription``

* For status tracking webhooks: no special permissions

* To receive inbound mail:

  * With an "SNS action" receipt rule: no special permissions
  * With an "S3 action" receipt rule: ``s3:GetObject`` on the S3 bucket
    and prefix used (or S3 Access Control List read access for inbound
    messages in that bucket)


This IAM policy covers all of those:

    .. code-block:: json

        {
          "Version": "2012-10-17",
          "Statement": [{
            "Effect": "Allow",
            "Action": ["ses:SendRawEmail", "ses:SendBulkTemplatedEmail"],
            "Resource": "*"
          }, {
            "Effect": "Allow",
            "Action": ["sns:ConfirmSubscription"],
            "Resource": ["arn:aws:sns:*:*:*"]
          }, {
            "Effect": "Allow",
            "Action": ["s3:GetObject"],
            "Resource": ["arn:aws:s3:::MY-PRIVATE-BUCKET-NAME/MY-INBOUND-PREFIX/*"]
          }]
        }

Following the principle of `least privilege`_, you should omit permissions
for any features you aren't using, and you may want to add additional restrictions:

* For Amazon SES sending, you can add conditions to restrict senders, recipients, times,
  or other properties. See Amazon's `Controlling access to Amazon SES`_ guide.

* For auto-confirming webhooks, you might limit the resource to SNS topics owned
  by your AWS account, and/or specific topic names or patterns. E.g.,
  ``"arn:aws:sns:*:0000000000000000:SES_*_Events"`` (replacing the zeroes with
  your numeric AWS account id). See Amazon's guide to `Amazon SNS ARNs`_.

* For inbound S3 delivery, there are multiple ways to control S3 access and data
  retention. See Amazon's `Managing access permissions to your Amazon S3 resources`_.
  (And obviously, you should *never store incoming emails to a public bucket!*)

  Also, you may need to grant Amazon SES (but *not* Anymail) permission to *write*
  to your inbound bucket. See Amazon's `Giving permissions to Amazon SES for email receiving`_.

* For all operations, you can limit source IP, allowable times, user agent, and more.
  (Requests from Anymail will include "django-anymail/*version*" along with Boto's user-agent.)
  See Amazon's guide to `IAM condition context keys`_.


.. _least privilege:
    https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html#grant-least-privilege
.. _Controlling access to Amazon SES:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/control-user-access.html
.. _Amazon SNS ARNs:
    https://docs.aws.amazon.com/sns/latest/dg/UsingIAMwithSNS.html#SNS_ARN_Format
.. _Managing access permissions to your Amazon S3 resources:
    https://docs.aws.amazon.com/AmazonS3/latest/dev/s3-access-control.html
.. _Giving permissions to Amazon SES for email receiving:
    https://docs.aws.amazon.com/ses/latest/DeveloperGuide/receiving-email-permissions.html
.. _IAM condition context keys:
    https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html
