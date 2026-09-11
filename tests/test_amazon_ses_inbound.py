import json
from base64 import b64encode
from datetime import datetime, timezone
from textwrap import dedent
from unittest.mock import ANY, MagicMock, call, patch

from django.test import override_settings, tag

from anymail.exceptions import AnymailAPIError, AnymailConfigurationError
from anymail.inbound import AnymailInboundMessage
from anymail.signals import AnymailInboundEvent
from anymail.utils import DEFAULT_DOWNLOAD_CHUNK_SIZE
from anymail.webhooks.amazon_ses import AmazonSESInboundWebhookView

from .test_amazon_ses_webhooks import AmazonSESWebhookTestsMixin
from .webhook_cases import WebhookTestCase


@tag("amazon_ses")
class AmazonSESInboundTests(WebhookTestCase, AmazonSESWebhookTestsMixin):
    def setUp(self):
        super().setUp()
        # Mock boto3.session.Session().client('s3').get_object. (We could also
        # use botocore.stub.Stubber, but mock works well with our test structure.)
        self.patch_boto3_session = patch(
            "anymail.webhooks.amazon_ses.boto3.session.Session", autospec=True
        )
        self.mock_session = self.patch_boto3_session.start()  # boto3.session.Session
        self.addCleanup(self.patch_boto3_session.stop)

        def mock_get_object(*, Bucket, Key):
            stream = MagicMock()
            stream.iter_chunks.return_value = iter(
                [self.mock_s3_downloadables[Bucket][Key]]
            )
            self.mock_s3_streams.append(stream)
            return {"Body": stream}

        self.mock_s3_downloadables = {}  #: bucket: key: bytes
        self.mock_s3_streams = []
        #: boto3.session.Session().client
        self.mock_client = self.mock_session.return_value.client
        #: boto3.session.Session().client('s3', ...)
        self.mock_s3 = self.mock_client.return_value
        #: boto3.session.Session().client('kms', ...)
        self.mock_kms = MagicMock()

        def mock_get_boto_client(service_name, **kwargs):
            return {"s3": self.mock_s3, "kms": self.mock_kms}[service_name]

        self.mock_client.side_effect = mock_get_boto_client
        self.mock_s3.get_object.side_effect = mock_get_object

        self.patch_encryption_client = patch(
            "anymail.webhooks.amazon_ses.S3EncryptionClient", autospec=True
        )
        self.mock_encryption_client = self.patch_encryption_client.start()
        self.addCleanup(self.patch_encryption_client.stop)
        self.patch_encryption_config = patch(
            "anymail.webhooks.amazon_ses.S3EncryptionClientConfig", autospec=True
        )
        self.mock_encryption_config = self.patch_encryption_config.start()
        self.addCleanup(self.patch_encryption_config.stop)
        self.patch_keyring = patch(
            "anymail.webhooks.amazon_ses.KmsKeyring", autospec=True
        )
        self.mock_keyring = self.patch_keyring.start()
        self.addCleanup(self.patch_keyring.stop)
        self.patch_commitment_policy = patch(
            "anymail.webhooks.amazon_ses.CommitmentPolicy", autospec=True
        )
        self.mock_commitment_policy = self.patch_commitment_policy.start()
        self.addCleanup(self.patch_commitment_policy.stop)

    TEST_MIME_MESSAGE = dedent("""\
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
        """).replace("\n", "\r\n")

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
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""",
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
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")
        self.assertEqual(
            message.html,
            """<div dir="ltr">It's a body\N{HORIZONTAL ELLIPSIS}</div>\n""",
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
        self.mock_s3.get_object.assert_called_once_with(
            Bucket="InboundEmailBucket-KeepPrivate",
            Key="inbound/fqef5sop459utgdf4o9lqbsv7jeo73pejig34301",
        )
        self.mock_s3_streams[0].iter_chunks.assert_called_once_with(
            DEFAULT_DOWNLOAD_CHUNK_SIZE
        )
        self.mock_s3_streams[0].close.assert_called_once_with()
        self.mock_s3.close.assert_called_once_with()

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

        self.mock_s3.get_object.side_effect = ClientError(
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
        self.mock_s3.close.assert_called_once_with()

    @override_settings(
        ANYMAIL_AMAZON_SES_INBOUND_KMS_KEY_ID="arn:aws:kms:us-east-1:111111111111:alias/aws/ses"
    )
    def test_inbound_s3_encrypted(self):
        """Should decrypt an encrypted S3 receipt object before parsing it"""
        decrypted_body = (
            self.mock_encryption_client.return_value.get_object.return_value["Body"]
        )
        decrypted_body.iter_chunks.return_value = iter(
            [self.TEST_MIME_MESSAGE.encode("ascii")]
        )

        raw_ses_event = {
            "notificationType": "Received",
            "mail": {
                "source": "envelope-from@example.org",
                "timestamp": "2018-03-30T17:21:51.636Z",
                "messageId": "encrypted-message-id",
            },
            "receipt": {
                "recipients": ["inbound@example.com"],
                "action": {
                    "type": "S3",
                    "bucketName": "InboundEmailBucket-KeepPrivate",
                    "objectKey": "inbound/encrypted-message-id",
                },
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
        self.mock_client.assert_has_calls(
            [call("s3", config=ANY), call("kms", config=ANY)]
        )
        self.mock_keyring.assert_called_once_with(
            self.mock_kms,
            "arn:aws:kms:us-east-1:111111111111:alias/aws/ses",
            enable_legacy_wrapping_algorithms=True,
        )
        self.mock_encryption_config.assert_called_once_with(
            self.mock_keyring.return_value,
            commitment_policy=self.mock_commitment_policy.REQUIRE_ENCRYPT_ALLOW_DECRYPT,
            enable_delayed_authentication=True,
        )
        self.mock_encryption_client.assert_called_once_with(
            self.mock_s3, self.mock_encryption_config.return_value
        )
        self.mock_encryption_client.return_value.get_object.assert_called_once_with(
            Bucket="InboundEmailBucket-KeepPrivate", Key="inbound/encrypted-message-id"
        )
        decrypted_body.iter_chunks.assert_called_once_with(DEFAULT_DOWNLOAD_CHUNK_SIZE)
        decrypted_body.close.assert_called_once_with()
        self.mock_s3.close.assert_called_once_with()
        self.mock_kms.close.assert_called_once_with()

        kwargs = self.assert_handler_called_once_with(
            self.inbound_handler,
            sender=AmazonSESInboundWebhookView,
            event=ANY,
            esp_name="Amazon SES",
        )
        message = kwargs["event"].message
        self.assertEqual(message.subject, "Test inbound message")
        self.assertEqual(message.text, "It's a body\N{HORIZONTAL ELLIPSIS}\n")

    @override_settings(
        ANYMAIL_AMAZON_SES_INBOUND_KMS_KEY_ID="arn:aws:kms:us-east-1:111111111111:alias/aws/ses"
    )
    def test_inbound_s3_encrypted_client_error(self):
        """Issue a helpful error when encrypted S3 download fails"""
        from botocore.exceptions import ClientError

        self.mock_encryption_client.return_value.get_object.side_effect = ClientError(
            {"Error": {"Code": 403, "Message": "Forbidden"}},
            operation_name="GetObject",
        )

        view = AmazonSESInboundWebhookView()
        with self.assertRaisesMessage(
            AnymailAPIError,
            "Anymail AmazonSESInboundWebhookView couldn't download"
            " S3 object 'YourBucket:inbound/the_object_key'",
        ) as cm:
            list(view.fetch_s3_chunks("YourBucket", "inbound/the_object_key"))

        self.assertIsInstance(cm.exception, ClientError)
        self.assertIn(
            "ClientError: An error occurred (403) when calling"
            " the GetObject operation: Forbidden",
            str(cm.exception),
        )
        self.mock_s3.close.assert_called_once_with()
        self.mock_kms.close.assert_called_once_with()

    @override_settings(
        ANYMAIL_AMAZON_SES_INBOUND_KMS_KEY_ID="arn:aws:kms:us-east-1:111111111111:alias/aws/ses"
    )
    def test_inbound_s3_encrypted_decryption_error(self):
        """Issue a helpful error when encrypted S3 object verification fails"""
        from s3_encryption.exceptions import S3EncryptionClientSecurityError

        def mock_iter_chunks(chunk_size):
            # Delayed authentication yields unverified plaintext, then reports an
            # invalid authentication tag when the stream is read to completion.
            yield b"unverified plaintext"
            raise S3EncryptionClientSecurityError(
                "Authentication tag verification failed"
            )

        decrypted_body = (
            self.mock_encryption_client.return_value.get_object.return_value["Body"]
        )
        decrypted_body.iter_chunks.side_effect = mock_iter_chunks

        view = AmazonSESInboundWebhookView()
        with self.assertRaisesMessage(
            AnymailAPIError,
            "Anymail AmazonSESInboundWebhookView failed decrypting"
            " S3 object 'YourBucket:inbound/the_object_key'",
        ) as cm:
            list(view.fetch_s3_chunks("YourBucket", "inbound/the_object_key"))

        self.assertIsInstance(cm.exception, S3EncryptionClientSecurityError)
        self.assertIn("Authentication tag verification failed", str(cm.exception))
        decrypted_body.iter_chunks.assert_called_once_with(DEFAULT_DOWNLOAD_CHUNK_SIZE)
        decrypted_body.close.assert_called_once_with()
        self.mock_s3.close.assert_called_once_with()
        self.mock_kms.close.assert_called_once_with()

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
