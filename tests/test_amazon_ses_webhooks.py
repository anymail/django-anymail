import json
import warnings
from datetime import datetime
from unittest.mock import ANY, patch

from django.test import SimpleTestCase, override_settings, tag
from django.utils.timezone import utc

from anymail.exceptions import AnymailConfigurationError, AnymailInsecureWebhookWarning
from anymail.signals import AnymailTrackingEvent
from anymail.webhooks.amazon_ses import AmazonSESTrackingWebhookView

from .webhook_cases import WebhookBasicAuthTestCase, WebhookTestCase


class AmazonSESWebhookTestsMixin(SimpleTestCase):
    def post_from_sns(self, path, raw_sns_message, **kwargs):
        return self.client.post(
            path,
            content_type='text/plain; charset=UTF-8',  # SNS posts JSON as text/plain
            data=json.dumps(raw_sns_message),
            HTTP_X_AMZ_SNS_MESSAGE_ID=raw_sns_message["MessageId"],
            HTTP_X_AMZ_SNS_MESSAGE_TYPE=raw_sns_message["Type"],
            # Anymail doesn't use other x-amz-sns-* headers
            **kwargs)


@tag('amazon_ses')
class AmazonSESWebhookSecurityTests(AmazonSESWebhookTestsMixin, WebhookBasicAuthTestCase):
    def call_webhook(self):
        return self.post_from_sns('/anymail/amazon_ses/tracking/',
                                  {"Type": "Notification", "MessageId": "123", "Message": "{}"})

    # Most actual tests are in WebhookBasicAuthTestCase

    def test_verifies_missing_auth(self):
        # Must handle missing auth header slightly differently from Anymail default 400 SuspiciousOperation:
        # SNS will only send basic auth after missing auth responds 401 WWW-Authenticate: Basic realm="..."
        self.clear_basic_auth()
        response = self.call_webhook()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], 'Basic realm="Anymail WEBHOOK_SECRET"')


@tag('amazon_ses')
class AmazonSESNotificationsTests(WebhookTestCase, AmazonSESWebhookTestsMixin):
    def test_bounce_event(self):
        # This test includes a complete Amazon SES example event. (Later tests omit some payload for brevity.)
        # https://docs.aws.amazon.com/ses/latest/DeveloperGuide/notification-examples.html#notification-examples-bounce
        raw_ses_event = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "reportingMTA": "dns; email.example.com",
                "bouncedRecipients": [{
                    "emailAddress": "jane@example.com",
                    "status": "5.1.1",
                    "action": "failed",
                    "diagnosticCode": "smtp; 550 5.1.1 <jane@example.com>... User unknown",
                }],
                "bounceSubType": "General",
                "timestamp": "2016-01-27T14:59:44.101Z",  # when bounce sent (by receiving ISP)
                "feedbackId": "00000138111222aa-44455566-cccc-cccc-cccc-ddddaaaa068a-000000",  # unique id for bounce
                "remoteMtaIp": "127.0.2.0",
            },
            "mail": {
                "timestamp": "2016-01-27T14:59:38.237Z",  # when message sent
                "source": "john@example.com",
                "sourceArn": "arn:aws:ses:us-west-2:888888888888:identity/example.com",
                "sourceIp": "127.0.3.0",
                "sendingAccountId": "123456789012",
                "messageId": "00000138111222aa-33322211-cccc-cccc-cccc-ddddaaaa0680-000000",
                "destination": ["jane@example.com", "mary@example.com", "richard@example.com"],
                "headersTruncated": False,
                "headers": [
                    {"name": "From", "value": '"John Doe" <john@example.com>'},
                    {"name": "To", "value": '"Jane Doe" <jane@example.com>, "Mary Doe" <mary@example.com>,'
                                            ' "Richard Doe" <richard@example.com>'},
                    {"name": "Message-ID", "value": "custom-message-ID"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Content-Type", "value": 'text/plain; charset="UTF-8"'},
                    {"name": "Content-Transfer-Encoding", "value": "base64"},
                    {"name": "Date", "value": "Wed, 27 Jan 2016 14:05:45 +0000"},
                    {"name": "X-Tag", "value": "tag 1"},
                    {"name": "X-Tag", "value": "tag 2"},
                    {"name": "X-Metadata", "value": '{"meta1":"string","meta2":2}'},
                ],
                "commonHeaders": {
                    "from": ["John Doe <john@example.com>"],
                    "date": "Wed, 27 Jan 2016 14:05:45 +0000",
                    "to": ["Jane Doe <jane@example.com>, Mary Doe <mary@example.com>,"
                           " Richard Doe <richard@example.com>"],
                    "messageId": "custom-message-ID",
                    "subject": "Hello",
                },
            },
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",  # unique id for SNS event
            "TopicArn": "arn:aws:sns:us-east-1:1234567890:SES_Events",
            "Subject": "Amazon SES Email Event Notification",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
            "SignatureVersion": "1",
            "Signature": "EXAMPLE-SIGNATURE==",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-12345abcde.pem",
            "UnsubscribeURL": "https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=arn...",
        }

        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.esp_event, raw_ses_event)
        self.assertEqual(event.timestamp, datetime(2018, 3, 26, 17, 58, 59, microsecond=675000, tzinfo=utc))  # SNS
        self.assertEqual(event.message_id, "00000138111222aa-33322211-cccc-cccc-cccc-ddddaaaa0680-000000")
        self.assertEqual(event.event_id, "19ba9823-d7f2-53c1-860e-cb10e0d13dfc")
        self.assertEqual(event.recipient, "jane@example.com")
        self.assertEqual(event.reject_reason, "bounced")
        self.assertEqual(event.description, "Permanent: General")
        self.assertEqual(event.mta_response, "smtp; 550 5.1.1 <jane@example.com>... User unknown")
        self.assertEqual(event.tags, ["tag 1", "tag 2"])
        self.assertEqual(event.metadata, {"meta1": "string", "meta2": 2})

    # For brevity, remaining tests omit some event fields that aren't used by Anymail

    def test_multiple_bounce_event(self):
        """Amazon SES notification can cover multiple recipients"""
        raw_ses_event = {
            "notificationType": "Bounce",
            "bounce": {
                "bounceType": "Permanent",
                "bounceSubType": "General",
                "bouncedRecipients": [
                    {"emailAddress": "jane@example.com"},
                    {"emailAddress": "richard@example.com"}
                ],
            },
            "mail": {
                "messageId": "00000137860315fd-34208509-5b74-41f3-95c5-22c1edc3c924-000000",
                "destination": ["jane@example.com", "mary@example.com", "richard@example.com"],
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)

        # tracking handler should be called twice -- once for each bounced recipient
        # (but not for the third, non-bounced recipient)
        self.assertEqual(self.tracking_handler.call_count, 2)

        _, kwargs = self.tracking_handler.call_args_list[0]
        event = kwargs['event']
        self.assertEqual(event.event_type, "bounced")
        self.assertEqual(event.recipient, "jane@example.com")
        self.assertEqual(event.description, "Permanent: General")
        self.assertIsNone(event.mta_response)

        _, kwargs = self.tracking_handler.call_args_list[1]
        event = kwargs['event']
        self.assertEqual(event.esp_event, raw_ses_event)
        self.assertEqual(event.recipient, "richard@example.com")

    def test_complaint_event(self):
        raw_ses_event = {
            "notificationType": "Complaint",
            "complaint": {
                "userAgent": "AnyCompany Feedback Loop (V0.01)",
                "complainedRecipients": [{"emailAddress": "richard@example.com"}],
                "complaintFeedbackType": "abuse",
            },
            "mail": {
                "messageId": "000001378603177f-7a5433e7-8edb-42ae-af10-f0181f34d6ee-000000",
                "destination": ["jane@example.com", "mary@example.com", "richard@example.com"],
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertEqual(event.event_type, "complained")
        self.assertEqual(event.recipient, "richard@example.com")
        self.assertEqual(event.reject_reason, "spam")
        self.assertEqual(event.description, "abuse")
        self.assertEqual(event.user_agent, "AnyCompany Feedback Loop (V0.01)")

    def test_delivery_event(self):
        raw_ses_event = {
            "notificationType": "Delivery",
            "mail": {
                "timestamp": "2016-01-27T14:59:38.237Z",
                "messageId": "0000014644fe5ef6-9a483358-9170-4cb4-a269-f5dcdf415321-000000",
                "destination": ["jane@example.com", "mary@example.com", "richard@example.com"],
            },
            "delivery": {
                "timestamp": "2016-01-27T14:59:38.237Z",
                "recipients": ["jane@example.com"],
                "processingTimeMillis": 546,
                "reportingMTA": "a8-70.smtp-out.amazonses.com",
                "smtpResponse": "250 ok:  Message 64111812 accepted",
                "remoteMtaIp": "127.0.2.0"
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertEqual(event.event_type, "delivered")
        self.assertEqual(event.recipient, "jane@example.com")
        self.assertEqual(event.mta_response, "250 ok:  Message 64111812 accepted")

    def test_send_event(self):
        raw_ses_event = {
            "eventType": "Send",
            "mail": {
                "timestamp": "2016-10-14T05:02:16.645Z",
                "messageId": "7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000",
                "destination": ["recipient@example.com"],
                "tags": {
                    "ses:configuration-set": ["ConfigSet"],
                    "ses:source-ip": ["192.0.2.0"],
                    "ses:from-domain": ["example.com"],
                    "ses:caller-identity": ["ses_user"],
                    "myCustomTag1": ["myCustomTagValue1"],
                    "myCustomTag2": ["myCustomTagValue2"]
                }
            },
            "send": {}
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertIsInstance(event, AnymailTrackingEvent)
        self.assertEqual(event.event_type, "sent")
        self.assertEqual(event.esp_event, raw_ses_event)
        self.assertEqual(event.timestamp, datetime(2018, 3, 26, 17, 58, 59, microsecond=675000, tzinfo=utc))  # SNS
        self.assertEqual(event.message_id, "7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000")
        self.assertEqual(event.event_id, "19ba9823-d7f2-53c1-860e-cb10e0d13dfc")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.tags, [])  # Anymail doesn't load Amazon SES "Message Tags"
        self.assertEqual(event.metadata, {})

    def test_reject_event(self):
        raw_ses_event = {
            "eventType": "Reject",
            "mail": {
                "timestamp": "2016-10-14T17:38:15.211Z",
                "messageId": "7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000",
                "destination": ["recipient@example.com"],
            },
            "reject": {
                "reason": "Bad content"
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertEqual(event.event_type, "rejected")
        self.assertEqual(event.reject_reason, "blocked")
        self.assertEqual(event.description, "Bad content")
        self.assertEqual(event.recipient, "recipient@example.com")

    def test_open_event(self):
        raw_ses_event = {
            "eventType": "Open",
            "mail": {
                "destination": ["recipient@example.com"],
                "messageId": "7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000",
            },
            "open": {
                "ipAddress": "192.0.2.1",
                "timestamp": "2017-08-09T22:00:19.652Z",
                "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_3 like Mac OS X)..."
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertEqual(event.event_type, "opened")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (iPhone; CPU iPhone OS 10_3_3 like Mac OS X)...")

    def test_click_event(self):
        raw_ses_event = {
            "eventType": "Click",
            "click": {
                "ipAddress": "192.0.2.1",
                "link": "https://docs.aws.amazon.com/ses/latest/DeveloperGuide/",
                "linkTags": {
                    "samplekey0": ["samplevalue0"],
                    "samplekey1": ["samplevalue1"],
                },
                "timestamp": "2017-08-09T23:51:25.570Z",
                "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."
            },
            "mail": {
                "destination": ["recipient@example.com"],
                "messageId": "7c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000",
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertEqual(event.event_type, "clicked")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.user_agent, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...")
        self.assertEqual(event.click_url, "https://docs.aws.amazon.com/ses/latest/DeveloperGuide/")

    def test_rendering_failure_event(self):
        raw_ses_event = {
            "eventType": "Rendering Failure",
            "mail": {
                "messageId": "c191be45-e9aedb9a-02f9-4d12-a87d-dd0099a07f8a-000000",
                "destination": ["recipient@example.com"],
            },
            "failure": {
                "errorMessage": "Attribute 'attributeName' is not present in the rendering data.",
                "templateName": "MyTemplate"
            }
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "19ba9823-d7f2-53c1-860e-cb10e0d13dfc",
            "Message": json.dumps(raw_ses_event) + "\n",
            "Timestamp": "2018-03-26T17:58:59.675Z",
        }
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(self.tracking_handler, sender=AmazonSESTrackingWebhookView,
                                                      event=ANY, esp_name='Amazon SES')
        event = kwargs['event']
        self.assertEqual(event.event_type, "failed")
        self.assertEqual(event.recipient, "recipient@example.com")
        self.assertEqual(event.description, "Attribute 'attributeName' is not present in the rendering data.")

    def test_incorrect_received_event(self):
        """The tracking webhook should warn if it receives inbound events"""
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Message": '{"notificationType": "Received"}',
        }
        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set an Amazon SES *inbound* receipt rule to publish to an SNS Topic that posts "
            "to Anymail's *tracking* webhook URL. (SNS TopicArn arn:aws:sns:us-east-1:111111111111:SES_Inbound)"
        ):
            self.post_from_sns('/anymail/amazon_ses/tracking/', raw_sns_message)


@tag('amazon_ses')
class AmazonSESSubscriptionManagementTests(WebhookTestCase, AmazonSESWebhookTestsMixin):
    # Anymail will automatically respond to SNS subscription notifications
    # if Anymail is configured to require basic auth via WEBHOOK_SECRET.
    # (Note that WebhookTestCase sets up ANYMAIL WEBHOOK_SECRET.)

    def setUp(self):
        super().setUp()
        # Mock boto3.session.Session().client('sns').confirm_subscription (and any other client operations)
        # (We could also use botocore.stub.Stubber, but mock works well with our test structure)
        self.patch_boto3_session = patch('anymail.webhooks.amazon_ses.boto3.session.Session', autospec=True)
        self.mock_session = self.patch_boto3_session.start()  # boto3.session.Session
        self.addCleanup(self.patch_boto3_session.stop)
        self.mock_client = self.mock_session.return_value.client  # boto3.session.Session().client
        self.mock_client_instance = self.mock_client.return_value  # boto3.session.Session().client('sns', ...)
        self.mock_client_instance.confirm_subscription.return_value = {
            'SubscriptionArn': 'arn:aws:sns:us-west-2:123456789012:SES_Notifications:aaaaaaa-...'
        }

    SNS_SUBSCRIPTION_CONFIRMATION = {
        "Type": "SubscriptionConfirmation",
        "MessageId": "165545c9-2a5c-472c-8df2-7ff2be2b3b1b",
        "Token": "EXAMPLE_TOKEN",
        "TopicArn": "arn:aws:sns:us-west-2:123456789012:SES_Notifications",
        "Message": "You have chosen to subscribe ...\nTo confirm..., visit the SubscribeURL included in this message.",
        "SubscribeURL": "https://sns.us-west-2.amazonaws.com/?Action=ConfirmSubscription&TopicArn=...",
        "Timestamp": "2012-04-26T20:45:04.751Z",
        "SignatureVersion": "1",
        "Signature": "EXAMPLE-SIGNATURE==",
        "SigningCertURL": "https://sns.us-west-2.amazonaws.com/SimpleNotificationService-12345abcde.pem"
    }

    def test_sns_subscription_auto_confirmation(self):
        """Anymail webhook will auto-confirm SNS topic subscriptions"""
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', self.SNS_SUBSCRIPTION_CONFIRMATION)
        self.assertEqual(response.status_code, 200)
        # auto-confirmed:
        self.mock_client.assert_called_once_with('sns', config=ANY, region_name="us-west-2")
        self.mock_client_instance.confirm_subscription.assert_called_once_with(
            TopicArn="arn:aws:sns:us-west-2:123456789012:SES_Notifications",
            Token="EXAMPLE_TOKEN", AuthenticateOnUnsubscribe="true")
        # didn't notify receivers:
        self.assertEqual(self.tracking_handler.call_count, 0)
        self.assertEqual(self.inbound_handler.call_count, 0)

    def test_sns_subscription_confirmation_failure(self):
        """Auto-confirmation allows error through if confirm call fails"""
        from botocore.exceptions import ClientError
        self.mock_client_instance.confirm_subscription.side_effect = ClientError({
            'Error': {
                'Type': 'Sender',
                'Code': 'InternalError',
                'Message': 'Gremlins!',
            },
            'ResponseMetadata': {
                'RequestId': 'aaaaaaaa-2222-1111-8888-bbbb3333bbbb',
                'HTTPStatusCode': 500,
            }
        }, operation_name="confirm_subscription")
        with self.assertRaisesMessage(ClientError, "Gremlins!"):
            self.post_from_sns('/anymail/amazon_ses/tracking/', self.SNS_SUBSCRIPTION_CONFIRMATION)
        # didn't notify receivers:
        self.assertEqual(self.tracking_handler.call_count, 0)
        self.assertEqual(self.inbound_handler.call_count, 0)

    @override_settings(ANYMAIL_AMAZON_SES_CLIENT_PARAMS={"region_name": "us-east-1"})
    def test_sns_subscription_confirmation_different_region(self):
        """Anymail confirms the subscription in the SNS Topic's own region, rather than any default region"""
        # (The SNS_SUBSCRIPTION_CONFIRMATION above has a TopicArn in region us-west-2)
        self.post_from_sns('/anymail/amazon_ses/tracking/', self.SNS_SUBSCRIPTION_CONFIRMATION)
        self.mock_client.assert_called_once_with('sns', config=ANY, region_name="us-west-2")

    @override_settings(ANYMAIL={})  # clear WEBHOOK_SECRET setting from base WebhookTestCase
    def test_sns_subscription_confirmation_auth_disabled(self):
        """Anymail *won't* auto-confirm SNS subscriptions if WEBHOOK_SECRET isn't in use"""
        warnings.simplefilter("ignore", AnymailInsecureWebhookWarning)  # (this gets tested elsewhere)
        with self.assertLogs('django.security.AnymailWebhookValidationFailure') as cm:
            response = self.post_from_sns('/anymail/amazon_ses/tracking/', self.SNS_SUBSCRIPTION_CONFIRMATION)
        self.assertEqual(response.status_code, 400)  # bad request
        self.assertEqual(
            ["Anymail received an unexpected SubscriptionConfirmation request for Amazon SNS topic "
             "'arn:aws:sns:us-west-2:123456789012:SES_Notifications'. (Anymail can automatically confirm "
             "SNS subscriptions if you set a WEBHOOK_SECRET and use that in your SNS notification url. Or "
             "you can manually confirm this subscription in the SNS dashboard with token 'EXAMPLE_TOKEN'.)"],
            [record.getMessage() for record in cm.records])
        # *didn't* try to confirm the subscription:
        self.assertEqual(self.mock_client_instance.confirm_subscription.call_count, 0)
        # didn't notify receivers:
        self.assertEqual(self.tracking_handler.call_count, 0)
        self.assertEqual(self.inbound_handler.call_count, 0)

    def test_sns_confirmation_success_notification(self):
        """Anymail ignores the 'Successfully validated' notification after confirming an SNS subscription"""
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', {
            "Type": "Notification",
            "MessageId": "7fbca0d9-eeab-5285-ae27-f3f57f2e84b0",
            "TopicArn": "arn:aws:sns:us-west-2:123456789012:SES_Notifications",
            "Message": "Successfully validated SNS topic for Amazon SES event publishing.",
            "Timestamp": "2018-03-21T16:58:45.077Z",
            "SignatureVersion": "1",
            "Signature": "EXAMPLE_SIGNATURE==",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-12345abcde.pem",
            "UnsubscribeURL": "https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe...",
        })
        self.assertEqual(response.status_code, 200)
        # didn't notify receivers:
        self.assertEqual(self.tracking_handler.call_count, 0)
        self.assertEqual(self.inbound_handler.call_count, 0)

    def test_sns_unsubscribe_confirmation(self):
        """Anymail ignores the UnsubscribeConfirmation SNS message after deleting a subscription"""
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', {
            "Type": "UnsubscribeConfirmation",
            "MessageId": "47138184-6831-46b8-8f7c-afc488602d7d",
            "Token": "EXAMPLE_TOKEN",
            "TopicArn": "arn:aws:sns:us-west-2:123456789012:SES_Notifications",
            "Message": "You have chosen to deactivate subscription ...\nTo cancel ... visit the SubscribeURL...",
            "SubscribeURL": "https://sns.us-west-2.amazonaws.com/?Action=ConfirmSubscription&TopicArn=...",
            "Timestamp": "2012-04-26T20:06:41.581Z",
            "SignatureVersion": "1",
            "Signature": "EXAMPLE_SIGNATURE==",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-12345abcde.pem",
        })
        self.assertEqual(response.status_code, 200)
        # *didn't* try to use the Token to re-enable the subscription:
        self.assertEqual(self.mock_client_instance.confirm_subscription.call_count, 0)
        # didn't notify receivers:
        self.assertEqual(self.tracking_handler.call_count, 0)
        self.assertEqual(self.inbound_handler.call_count, 0)

    @override_settings(ANYMAIL_AMAZON_SES_AUTO_CONFIRM_SNS_SUBSCRIPTIONS=False)
    def test_disable_auto_confirmation(self):
        """The ANYMAIL setting AMAZON_SES_AUTO_CONFIRM_SNS_SUBSCRIPTIONS will disable this feature"""
        response = self.post_from_sns('/anymail/amazon_ses/tracking/', self.SNS_SUBSCRIPTION_CONFIRMATION)
        self.assertEqual(response.status_code, 200)
        # *didn't* try to subscribe:
        self.assertEqual(self.mock_session.call_count, 0)
        self.assertEqual(self.mock_client.call_count, 0)
        # didn't notify receivers:
        self.assertEqual(self.tracking_handler.call_count, 0)
        self.assertEqual(self.inbound_handler.call_count, 0)
