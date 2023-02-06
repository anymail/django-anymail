import json
from base64 import b64encode
from datetime import datetime, timezone
from textwrap import dedent
from unittest.mock import ANY, patch

from django.test import tag

from anymail.exceptions import AnymailAPIError, AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.webhooks.amazon_ses import AmazonSESInboundWebhookView

from .test_amazon_ses_webhooks import AmazonSESWebhookTestsMixin
from .webhook_cases import WebhookTestCase


@tag("amazon_ses")
class AmazonSESInboundTests(WebhookTestCase, AmazonSESWebhookTestsMixin):
    def setUp(self):
        super().setUp()
        # Mock boto3.session.Session().client('s3').download_fileobj. (We could also
        # use botocore.stub.Stubber, but mock works well with our test structure.)
        self.patch_boto3_session = patch(
            "anymail.webhooks.amazon_ses.boto3.session.Session", autospec=True
        )
        self.mock_session = self.patch_boto3_session.start()  # boto3.session.Session
        self.addCleanup(self.patch_boto3_session.stop)

        def mock_download_fileobj(bucket, key, fileobj):
            fileobj.write(self.mock_s3_downloadables[bucket][key])

        self.mock_s3_downloadables = {}  #: bucket: key: bytes
        #: boto3.session.Session().client
        self.mock_client = self.mock_session.return_value.client
        #: boto3.session.Session().client('s3', ...)
        self.mock_s3 = self.mock_client.return_value
        self.mock_s3.download_fileobj.side_effect = mock_download_fileobj

    TEST_MIME_MESSAGE = dedent(
        """\
        Return-Path: <bounce-handler@mail.example.org>
        Received: from mail.example.org by inbound-smtp.us-east-1.amazonaws.com...
        MIME-Version: 1.0
        Received: by 10.1.1.1 with HTTP; Fri, 30 Mar 2018 10:21:49 -0700 (PDT)
        From: "Sender, Inc." <from@example.org>
        Date: Fri, 30 Mar 2018 10:21:50 -0700
        Message-ID: <CAEPk3RKsi@mail.example.org>
        Subject: Test inbound message
        To: Recipient <inbound@example.com>, someone-else@example.org
        Content-Type: multipart/alternative; boundary="94eb2c05e174adb140055b6339c5"

        --94eb2c05e174adb140055b6339c5
        Content-Type: text/plain; charset="UTF-8"
        Content-Transfer-Encoding: quoted-printable

        It's a body=E2=80=A6

        --94eb2c05e174adb140055b6339c5
        Content-Type: text/html; charset="UTF-8"
        Content-Transfer-Encoding: quoted-printable

        <div dir=3D"ltr">It's a body=E2=80=A6</div>

        --94eb2c05e174adb140055b6339c5--
        """
    ).replace("\n", "\r\n")

    def test_inbound_sns_utf8(self):
        raw_ses_event = {
            "notificationType": "Received",
            "mail": {
                "timestamp": "2018-03-30T17:21:51.636Z",
                "source": "envelope-from@example.org",
                # messageId is assigned by Amazon SES:
                "messageId": "jili9m351il3gkburn7o2f0u6788stij94c8ld01",
                "destination": ["inbound@example.com", "someone-else@example.org"],
                "headersTruncated": False,
                "headers": [
                    # (omitting a few headers that Amazon SES adds on receipt)
                    {
                        "name": "Return-Path",
                        "value": "<bounce-handler@mail.example.org>",
                    },
                    {
                        "name": "Received",
                        "value": "from mail.example.org by"
                        " inbound-smtp.us-east-1.amazonaws.com...",
                    },
                    {"name": "MIME-Version", "value": "1.0"},
                    {
                        "name": "Received",
                        "value": "by 10.1.1.1 with HTTP;"
                        " Fri, 30 Mar 2018 10:21:49 -0700 (PDT)",
                    },
                    {"name": "From", "value": '"Sender, Inc." <from@example.org>'},
                    {"name": "Date", "value": "Fri, 30 Mar 2018 10:21:50 -0700"},
                    {"name": "Message-ID", "value": "<CAEPk3RKsi@mail.example.org>"},
                    {"name": "Subject", "value": "Test inbound message"},
                    {
                        "name": "To",
                        "value": "Recipient <inbound@example.com>,"
                        " someone-else@example.org",
                    },
                    {
                        "name": "Content-Type",
                        "value": "multipart/alternative;"
                        ' boundary="94eb2c05e174adb140055b6339c5"',
                    },
                ],
                "commonHeaders": {
                    "returnPath": "bounce-handler@mail.example.org",
                    "from": ['"Sender, Inc." <from@example.org>'],
                    "date": "Fri, 30 Mar 2018 10:21:50 -0700",
                    "to": [
                        "Recipient <inbound@example.com>",
                        "someone-else@example.org",
                    ],
                    "messageId": "<CAEPk3RKsi@mail.example.org>",
                    "subject": "Test inbound message",
                },
            },
            "receipt": {
                "timestamp": "2018-03-30T17:21:51.636Z",
                "processingTimeMillis": 357,
                "recipients": ["inbound@example.com"],
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
                "spfVerdict": {"status": "PASS"},
                "dkimVerdict": {"status": "PASS"},
                "dmarcVerdict": {"status": "PASS"},
                "action": {
                    "type": "SNS",
                    "topicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
                    "encoding": "UTF8",
                },
            },
            "content": self.TEST_MIME_MESSAGE,
        }

        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Subject": "Amazon SES Email Receipt Notification",
            "Message": json.dumps(raw_ses_event),
            "Timestamp": "2018-03-30T17:17:36.516Z",
            "SignatureVersion": "1",
            "Signature": "EXAMPLE_SIGNATURE==",
            "SigningCertURL": "https://sns.us-east-1.amazonaws.com"
            "/SimpleNotificationService-12345abcde.pem",
            "UnsubscribeURL": "https://sns.us-east-1.amazonaws.com"
            "/?Action=Unsubscribe&SubscriptionArn=arn...",
        }

        response = self.post_from_sns("/anymail/amazon_ses/inbound/", raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=AmazonSESInboundWebhookView,
            event=ANY,
            esp_name="Amazon SES",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            datetime(2018, 3, 30, 17, 21, 51, microsecond=636000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.event_id, "jili9m351il3gkburn7o2f0u6788stij94c8ld01")
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_ses_event)

        message = event.message
        self.assertIsInstance(message, AnymailInboundMessage)
        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "inbound@example.com")
        self.assertEqual(str(message.from_email), '"Sender, Inc." <from@example.org>')
        self.assertEqual(
            [str(to) for to in message.to],
            ["Recipient <inbound@example.com>", "someone-else@example.org"],
        )
        self.assertEqual(message.subject, "Test inbound message")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\r\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\r\n""",
        )
        self.assertIs(message.spam_detected, False)

    def test_inbound_sns_base64(self):
        """Should handle 'Base 64' content option on received email SNS action"""
        raw_ses_event = {
            # (omitting some fields that aren't used by Anymail)
            "notificationType": "Received",
            "mail": {
                "source": "envelope-from@example.org",
                "timestamp": "2018-03-30T17:21:51.636Z",
                # messageId is assigned by Amazon SES
                "messageId": "jili9m351il3gkburn7o2f0u6788stij94c8ld01",
                "destination": ["inbound@example.com", "someone-else@example.org"],
            },
            "receipt": {
                "recipients": ["inbound@example.com"],
                "action": {
                    "type": "SNS",
                    "topicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
                    "encoding": "BASE64",
                },
                "spamVerdict": {"status": "FAIL"},
            },
            "content": b64encode(self.TEST_MIME_MESSAGE.encode("ascii")).decode(
                "ascii"
            ),
        }

        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Message": json.dumps(raw_ses_event),
        }

        response = self.post_from_sns("/anymail/amazon_ses/inbound/", raw_sns_message)
        self.assertEqual(response.status_code, 200)
        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=AmazonSESInboundWebhookView,
            event=ANY,
            esp_name="Amazon SES",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            datetime(2018, 3, 30, 17, 21, 51, microsecond=636000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.event_id, "jili9m351il3gkburn7o2f0u6788stij94c8ld01")
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_ses_event)

        message = event.message
        self.assertIsInstance(message, AnymailInboundMessage)
        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "inbound@example.com")
        self.assertEqual(str(message.from_email), '"Sender, Inc." <from@example.org>')
        self.assertEqual(
            [str(to) for to in message.to],
            ["Recipient <inbound@example.com>", "someone-else@example.org"],
        )
        self.assertEqual(message.subject, "Test inbound message")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\r\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\r\n""",
        )
        self.assertIs(message.spam_detected, True)

    def test_inbound_s3(self):
        """Should handle 'S3' receipt action"""

        self.mock_s3_downloadables["InboundEmailBucket-KeepPrivate"] = {
            "inbound/fqef5sop459utgdf4o9lqbsv7jeo73pejig34301": (
                self.TEST_MIME_MESSAGE.encode("ascii")
            )
        }

        raw_ses_event = {
            # (omitting some fields that aren't used by Anymail)
            "notificationType": "Received",
            "mail": {
                "source": "envelope-from@example.org",
                "timestamp": "2018-03-30T17:21:51.636Z",
                # messageId is assigned by Amazon SES
                "messageId": "fqef5sop459utgdf4o9lqbsv7jeo73pejig34301",
                "destination": ["inbound@example.com", "someone-else@example.org"],
            },
            "receipt": {
                "recipients": ["inbound@example.com"],
                "action": {
                    "type": "S3",
                    "topicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
                    "bucketName": "InboundEmailBucket-KeepPrivate",
                    "objectKeyPrefix": "inbound",
                    "objectKey": "inbound/fqef5sop459utgdf4o9lqbsv7jeo73pejig34301",
                },
                "spamVerdict": {"status": "GRAY"},
            },
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Message": json.dumps(raw_ses_event),
        }
        response = self.post_from_sns("/anymail/amazon_ses/inbound/", raw_sns_message)
        self.assertEqual(response.status_code, 200)

        self.mock_client.assert_called_once_with("s3", config=ANY)
        self.mock_s3.download_fileobj.assert_called_once_with(
            "InboundEmailBucket-KeepPrivate",
            "inbound/fqef5sop459utgdf4o9lqbsv7jeo73pejig34301",
            ANY,
        )

        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=AmazonSESInboundWebhookView,
            event=ANY,
            esp_name="Amazon SES",
        )
        event = kwargs["event"]
        self.assertIsInstance(event, AnymailInboundEvent)
        self.assertEqual(event.event_type, "inbound")
        self.assertEqual(
            event.timestamp,
            datetime(2018, 3, 30, 17, 21, 51, microsecond=636000, tzinfo=timezone.utc),
        )
        self.assertEqual(event.event_id, "fqef5sop459utgdf4o9lqbsv7jeo73pejig34301")
        self.assertIsInstance(event.message, AnymailInboundMessage)
        self.assertEqual(event.esp_event, raw_ses_event)

        message = event.message
        self.assertIsInstance(message, AnymailInboundMessage)
        self.assertEqual(message.envelope_sender, "envelope-from@example.org")
        self.assertEqual(message.envelope_recipient, "inbound@example.com")
        self.assertEqual(str(message.from_email), '"Sender, Inc." <from@example.org>')
        self.assertEqual(
            [str(to) for to in message.to],
            ["Recipient <inbound@example.com>", "someone-else@example.org"],
        )
        self.assertEqual(message.subject, "Test inbound message")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""",
        )
        self.assertIsNone(message.spam_detected)

    def test_inbound_s3_failure_message(self):
        """Issue a helpful error when S3 download fails"""
        # Boto's error:
        # "An error occurred (403) when calling the HeadObject operation: Forbidden"
        from botocore.exceptions import ClientError

        self.mock_s3.download_fileobj.side_effect = ClientError(
            {"Error": {"Code": 403, "Message": "Forbidden"}},
            operation_name="HeadObject",
        )

        raw_ses_event = {
            "notificationType": "Received",
            "receipt": {
                "action": {
                    "type": "S3",
                    "bucketName": "YourBucket",
                    "objectKey": "inbound/the_object_key",
                }
            },
        }
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:aws:sns:us-east-1:111111111111:SES_Inbound",
            "Message": json.dumps(raw_ses_event),
        }
        with self.assertRaisesMessage(
            AnymailAPIError,
            "Anymail AmazonSESInboundWebhookView couldn't download"
            " S3 object 'YourBucket:inbound/the_object_key'",
        ) as cm:
            self.post_from_sns("/anymail/amazon_ses/inbound/", raw_sns_message)
        # both Boto and Anymail exception class:
        self.assertIsInstance(cm.exception, ClientError)
        # original Boto message included:
        self.assertIn(
            "ClientError: An error occurred (403) when calling"
            " the HeadObject operation: Forbidden",
            str(cm.exception),
        )

    def test_incorrect_tracking_event(self):
        """The inbound webhook should warn if it receives tracking events"""
        raw_sns_message = {
            "Type": "Notification",
            "MessageId": "8f6dee70-c885-558a-be7d-bd48bbf5335e",
            "TopicArn": "arn:...:111111111111:SES_Tracking",
            "Message": '{"notificationType": "Delivery"}',
        }

        with self.assertRaisesMessage(
            AnymailConfigurationError,
            "You seem to have set an Amazon SES *sending* event or notification"
            " to publish to an SNS Topic that posts to Anymail's *inbound* webhook URL."
            " (SNS TopicArn arn:...:111111111111:SES_Tracking)",
        ):
            self.post_from_sns("/anymail/amazon_ses/inbound/", raw_sns_message)
