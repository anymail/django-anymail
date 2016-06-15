# -*- coding: utf-8 -*-

from __future__ import unicode_literals

from base64 import b64encode
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test.utils import override_settings

from anymail.exceptions import (AnymailAPIError, AnymailSerializationError,
                                AnymailUnsupportedFeature, AnymailRecipientsRefused)
from anymail.message import attach_inline_image_file

from .mock_requests_backend import RequestsBackendMockAPITestCase, SessionSharingTestCasesMixin
from .utils import sample_image_content, sample_image_path, SAMPLE_IMAGE_FILENAME, AnymailTestMixin, decode_att


@override_settings(EMAIL_BACKEND='anymail.backends.postmark.PostmarkBackend',
                   ANYMAIL={'POSTMARK_SERVER_TOKEN': 'test_server_token'})
class PostmarkBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "To": "to@example.com",
        "SubmittedAt": "2016-03-12T15:27:50.4468803-05:00",
        "MessageID": "b4007d94-33f1-4e78-a783-97417d6c80e6",
        "ErrorCode":0,
        "Message":"OK"
    }"""

    def setUp(self):
        super(PostmarkBackendMockAPITestCase, self).setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives('Subject', 'Text Body', 'from@example.com', ['to@example.com'])


class PostmarkBackendStandardEmailTests(PostmarkBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail('Subject here', 'Here is the message.',
                       'from@sender.example.com', ['to@example.com'], fail_silently=False)
        self.assert_esp_called('/email')
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-Postmark-Server-Token"], "test_server_token")
        data = self.get_api_call_json()
        self.assertEqual(data['Subject'], "Subject here")
        self.assertEqual(data['TextBody'], "Here is the message.")
        self.assertEqual(data['From'], "from@sender.example.com")
        self.assertEqual(data['To'], "to@example.com")

    def test_name_addr(self):
        """Make sure RFC2822 name-addr format (with display-name) is allowed

        (Test both sender and recipient addresses)
        """
        msg = mail.EmailMessage(
            'Subject', 'Message', 'From Name <from@example.com>',
            ['Recipient #1 <to1@example.com>', 'to2@example.com'],
            cc=['Carbon Copy <cc1@example.com>', 'cc2@example.com'],
            bcc=['Blind Copy <bcc1@example.com>', 'bcc2@example.com'])
        msg.send()
        data = self.get_api_call_json()
        self.assertEqual(data['From'], 'From Name <from@example.com>')
        self.assertEqual(data['To'], 'Recipient #1 <to1@example.com>, to2@example.com')
        self.assertEqual(data['Cc'], 'Carbon Copy <cc1@example.com>, cc2@example.com')
        self.assertEqual(data['Bcc'], 'Blind Copy <bcc1@example.com>, bcc2@example.com')

    def test_email_message(self):
        email = mail.EmailMessage(
            'Subject', 'Body goes here', 'from@example.com',
            ['to1@example.com', 'Also To <to2@example.com>'],
            bcc=['bcc1@example.com', 'Also BCC <bcc2@example.com>'],
            cc=['cc1@example.com', 'Also CC <cc2@example.com>'],
            headers={'Reply-To': 'another@example.com',
                     'X-MyHeader': 'my value',
                     'Message-ID': 'mycustommsgid@sales.example.com'})  # should override backend msgid
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data['Subject'], "Subject")
        self.assertEqual(data['TextBody'], "Body goes here")
        self.assertEqual(data['From'], "from@example.com")
        self.assertEqual(data['To'], 'to1@example.com, Also To <to2@example.com>')
        self.assertEqual(data['Bcc'], 'bcc1@example.com, Also BCC <bcc2@example.com>')
        self.assertEqual(data['Cc'], 'cc1@example.com, Also CC <cc2@example.com>')
        self.assertCountEqual(data['Headers'], [
            {'Name': 'Message-ID', 'Value': 'mycustommsgid@sales.example.com'},
            {'Name': 'Reply-To', 'Value': 'another@example.com'},
            {'Name': 'X-MyHeader', 'Value': 'my value'},
        ])

    def test_html_message(self):
        text_content = 'This is an important message.'
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMultiAlternatives('Subject', text_content,
                                            'from@example.com', ['to@example.com'])
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data['TextBody'], text_content)
        self.assertEqual(data['HtmlBody'], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn('Attachments', data)

    def test_html_only_message(self):
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMessage('Subject', html_content, 'from@example.com', ['to@example.com'])
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        data = self.get_api_call_json()
        self.assertNotIn('TextBody', data)
        self.assertEqual(data['HtmlBody'], html_content)

    def test_extra_headers(self):
        self.message.extra_headers = {'X-Custom': 'string', 'X-Num': 123}
        self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(data['Headers'], [
            {'Name': 'X-Custom', 'Value': 'string'},
            {'Name': 'X-Num', 'Value': 123}
        ])

    def test_extra_headers_serialization_error(self):
        self.message.extra_headers = {'X-Custom': Decimal(12.5)}
        with self.assertRaisesMessage(AnymailSerializationError, "Decimal('12.5')"):
            self.message.send()

    def test_reply_to(self):
        email = mail.EmailMessage('Subject', 'Body goes here', 'from@example.com', ['to1@example.com'],
                                  reply_to=['reply@example.com', 'Other <reply2@example.com>'],
                                  headers={'X-Other': 'Keep'})
        email.send()
        data = self.get_api_call_json()
        self.assertEqual(data['ReplyTo'], 'reply@example.com, Other <reply2@example.com>')
        self.assertEqual(data['Headers'], [{'Name': 'X-Other', 'Value': 'Keep'}])  # don't lose other headers

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(filename="test.txt", content=text_content, mimetype="text/plain")

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        # Should work with a MIMEBase object (also tests no filename)...
        pdf_content = b"PDF\xb4 pretend this is valid pdf data"
        mimeattachment = MIMEBase('application', 'pdf')
        mimeattachment.set_payload(pdf_content)
        self.message.attach(mimeattachment)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data['Attachments']
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["Name"], "test.txt")
        self.assertEqual(attachments[0]["ContentType"], "text/plain")
        self.assertEqual(decode_att(attachments[0]["Content"]).decode('ascii'), text_content)
        self.assertNotIn('ContentID', attachments[0])

        self.assertEqual(attachments[1]["ContentType"], "image/png")  # inferred from filename
        self.assertEqual(attachments[1]["Name"], "test.png")
        self.assertEqual(decode_att(attachments[1]["Content"]), png_content)
        self.assertNotIn('ContentID', attachments[1])  # make sure image not treated as inline

        self.assertEqual(attachments[2]["ContentType"], "application/pdf")
        self.assertEqual(attachments[2]["Name"], "")  # none
        self.assertEqual(decode_att(attachments[2]["Content"]), pdf_content)
        self.assertNotIn('ContentID', attachments[2])

    def test_unicode_attachment_correctly_decoded(self):
        # Slight modification from the Django unicode docs:
        # https://django.readthedocs.io/en/latest/ref/unicode.html#email
        self.message.attach("Une pièce jointe.html", '<p>\u2019</p>', mimetype='text/html')
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data['Attachments'], [{
            'Name': 'Une pièce jointe.html',
            'ContentType': 'text/html',
            'Content': b64encode('<p>\u2019</p>'.encode('utf-8')).decode('ascii')
        }])

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)  # Read from a png file
        html_content = '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data['HtmlBody'], html_content)

        attachments = data['Attachments']
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['Name'], image_filename)
        self.assertEqual(attachments[0]['ContentType'], 'image/png')
        self.assertEqual(decode_att(attachments[0]["Content"]), image_data)
        self.assertEqual(attachments[0]["ContentID"], 'cid:%s' % cid)

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        self.message.attach_file(image_path)  # option 1: attach as a file

        image = MIMEImage(image_data)  # option 2: construct the MIMEImage and attach it directly
        self.message.attach(image)

        image_data_b64 = b64encode(image_data).decode('ascii')

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data['Attachments'], [
            {
                'Name': image_filename,  # the named one
                'ContentType': 'image/png',
                'Content': image_data_b64,
            },
            {
                'Name': '',  # the unnamed one
                'ContentType': 'image/png',
                'Content': image_data_b64,
            },
        ])

    def test_multiple_html_alternatives(self):
        # Multiple alternatives not allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>But not second html</p>", "text/html")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_html_alternative(self):
        # Only html alternatives allowed
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_alternatives_fail_silently(self):
        # Make sure fail_silently is respected
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        sent = self.message.send(fail_silently=True)
        self.assert_esp_not_called("API should not be called when send fails silently")
        self.assertEqual(sent, 0)

    def test_suppress_empty_address_lists(self):
        """Empty to, cc, bcc, and reply_to shouldn't generate empty fields"""
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn('Cc', data)
        self.assertNotIn('Bcc', data)
        self.assertNotIn('ReplyTo', data)

        # Test empty `to` -- but send requires at least one recipient somewhere (like cc)
        self.message.to = []
        self.message.cc = ['cc@example.com']
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn('To', data)

    def test_api_failure(self):
        self.set_mock_response(status_code=500)
        with self.assertRaises(AnymailAPIError):
            sent = mail.send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'])
            self.assertEqual(sent, 0)

        # Make sure fail_silently is respected
        self.set_mock_response(status_code=500)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'], fail_silently=True)
        self.assertEqual(sent, 0)

    def test_api_error_includes_details(self):
        """AnymailAPIError should include ESP's error message"""
        # JSON error response:
        error_response = b"""{
            "ErrorCode": 451,
            "Message": "Helpful explanation from Postmark."
        }"""
        self.set_mock_response(status_code=200, raw=error_response)
        with self.assertRaisesMessage(AnymailAPIError, "Helpful explanation from Postmark"):
            self.message.send()

        # Non-JSON error response:
        self.set_mock_response(status_code=500, raw=b"Ack! Bad proxy!")
        with self.assertRaisesMessage(AnymailAPIError, "Ack! Bad proxy!"):
            self.message.send()

        # No content in the error response:
        self.set_mock_response(status_code=502, raw=None)
        with self.assertRaises(AnymailAPIError):
            self.message.send()


class PostmarkBackendAnymailFeatureTests(PostmarkBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_metadata(self):
        self.message.metadata = {'user_id': "12345", 'items': 6}
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'metadata'):
            self.message.send()

    def test_send_at(self):
        self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'send_at'):
            self.message.send()

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data['Tag'], "receipt")

        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'multiple tags'):
            self.message.send()

    def test_track_opens(self):
        self.message.track_opens = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data['TrackOpens'], True)

    def test_track_clicks(self):
        self.message.track_clicks = True
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'track_clicks'):
            self.message.send()

    def test_template(self):
        self.message.template_id = 1234567
        # Postmark doesn't support per-recipient merge_data
        self.message.merge_global_data = {'name': "Alice", 'group': "Developers"}
        self.message.send()
        self.assert_esp_called('/email/withTemplate/')
        data = self.get_api_call_json()
        self.assertEqual(data['TemplateId'], 1234567)
        self.assertEqual(data['TemplateModel'], {'name': "Alice", 'group': "Developers"})

    def test_merge_data(self):
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
        }
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'merge_data'):
            self.message.send()

    def test_missing_subject(self):
        """Make sure a missing subject omits Subject from API call.

        (Allows use of template subject)
        """
        self.message.template_id = 1234567
        self.message.subject = None
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn('Subject', data)

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn('Tag', data)
        self.assertNotIn('TemplateId', data)
        self.assertNotIn('TemplateModel', data)
        self.assertNotIn('TrackOpens', data)

    def test_esp_extra(self):
        self.message.esp_extra = {
            'FuturePostmarkOption': 'some-value',
        }
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data['FuturePostmarkOption'], 'some-value')

    def test_message_server_token(self):
        # Can override server-token on a per-message basis:
        self.message.esp_extra = {
            'server_token': 'token_for_this_message_only',
        }
        self.message.send()
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-Postmark-Server-Token"], "token_for_this_message_only")
        data = self.get_api_call_json()
        self.assertNotIn('server_token', data)  # not in the json

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """ The anymail_status should be attached to the message when it is sent """
        response_content = b"""{
            "MessageID":"abcdef01-2345-6789-0123-456789abcdef",
            "ErrorCode":0,
            "Message":"OK"
        }"""
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com', ['to1@example.com'],)
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {'sent'})
        self.assertEqual(msg.anymail_status.message_id, 'abcdef01-2345-6789-0123-456789abcdef')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'sent')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].message_id,
                         'abcdef01-2345-6789-0123-456789abcdef')
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    # noinspection PyUnresolvedReferences
    def test_send_failed_anymail_status(self):
        """ If the send fails, anymail_status should contain initial values"""
        self.set_mock_response(status_code=500)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertIsNone(self.message.anymail_status.esp_response)

    # noinspection PyUnresolvedReferences
    def test_send_unparsable_response(self):
        """If the send succeeds, but a non-JSON API response, should raise an API exception"""
        mock_response = self.set_mock_response(status_code=200,
                                               raw=b"yikes, this isn't a real response")
        with self.assertRaises(AnymailAPIError):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(self.message.anymail_status.esp_response, mock_response)

    def test_json_serialization_errors(self):
        """Try to provide more information about non-json-serializable data"""
        self.message.tags = [Decimal('19.99')]  # yeah, don't do this
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
            print(self.get_api_call_json())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        self.assertIn("Don't know how to send this data to Postmark", str(err))  # our added context
        self.assertIn("Decimal('19.99') is not JSON serializable", str(err))  # original message


class PostmarkBackendRecipientsRefusedTests(PostmarkBackendMockAPITestCase):
    """Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid"""

    def test_recipients_inactive(self):
        self.set_mock_response(
            status_code=422,
            raw=b'{"ErrorCode":406,'
                b'"Message":"You tried to send to a recipient that has been marked as inactive.\\n'
                b'Found inactive addresses: hardbounce@example.com, spam@example.com.\\n'
                b'Inactive recipients are ones that have generated a hard bounce or a spam complaint."}'
        )
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['hardbounce@example.com', 'Hates Spam <spam@example.com>'])
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients['hardbounce@example.com'].status, 'rejected')
        self.assertEqual(status.recipients['spam@example.com'].status, 'rejected')

    def test_recipients_invalid(self):
        self.set_mock_response(
            status_code=422,
            raw=b"""{"ErrorCode":300,"Message":"Invalid 'To' address: 'invalid@localhost'."}"""
        )
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com', ['invalid@localhost'])
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients['invalid@localhost'].status, 'invalid')

    def test_from_email_invalid(self):
        # Invalid 'From' address generates same Postmark ErrorCode 300 as invalid 'To',
        # but should raise a different Anymail error
        self.set_mock_response(
            status_code=422,
            raw=b"""{"ErrorCode":300,"Message":"Invalid 'From' address: 'invalid@localhost'."}"""
        )
        msg = mail.EmailMessage('Subject', 'Body', 'invalid@localhost', ['to@example.com'])
        with self.assertRaises(AnymailAPIError):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_response(
            status_code=422,
            raw=b'{"ErrorCode":406,'
                b'"Message":"You tried to send to a recipient that has been marked as inactive.\\n'
                b'Found inactive addresses: hardbounce@example.com, spam@example.com.\\n'
                b'Inactive recipients are ones that have generated a hard bounce or a spam complaint."}'
        )
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['hardbounce@example.com', 'Hates Spam <spam@example.com>'])
        msg.send(fail_silently=True)
        status = msg.anymail_status
        self.assertEqual(status.recipients['hardbounce@example.com'].status, 'rejected')
        self.assertEqual(status.recipients['spam@example.com'].status, 'rejected')

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)
    def test_ignore_recipient_status(self):
        self.set_mock_response(
            status_code=422,
            raw=b'{"ErrorCode":406,'
                b'"Message":"You tried to send to a recipient that has been marked as inactive.\\n'
                b'Found inactive addresses: hardbounce@example.com, spam@example.com.\\n'
                b'Inactive recipients are ones that have generated a hard bounce or a spam complaint. "}'
        )
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['hardbounce@example.com', 'Hates Spam <spam@example.com>'])
        msg.send()
        status = msg.anymail_status
        self.assertEqual(status.recipients['hardbounce@example.com'].status, 'rejected')
        self.assertEqual(status.recipients['spam@example.com'].status, 'rejected')

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        self.set_mock_response(
            status_code=200,
            raw=b'{"To":"hardbounce@example.com, valid@example.com, Hates Spam <spam@example.com>",'
                b'"SubmittedAt":"2016-03-12T22:59:06.2505871-05:00",'
                b'"MessageID":"089dce03-feee-408e-9f0c-ee69bf1c5f35",'
                b'"ErrorCode":0,'
                b'"Message":"Message OK, but will not deliver to these inactive addresses:'
                b' hardbounce@example.com, spam@example.com.'
                b' Inactive recipients are ones that have generated a hard bounce or a spam complaint."}'
        )
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['hardbounce@example.com', 'valid@example.com', 'Hates Spam <spam@example.com>'])
        sent = msg.send()
        self.assertEqual(sent, 1)  # one message sent, successfully, to 1 of 3 recipients
        status = msg.anymail_status
        self.assertEqual(status.recipients['hardbounce@example.com'].status, 'rejected')
        self.assertEqual(status.recipients['valid@example.com'].status, 'sent')
        self.assertEqual(status.recipients['spam@example.com'].status, 'rejected')


class PostmarkBackendSessionSharingTestCase(SessionSharingTestCasesMixin, PostmarkBackendMockAPITestCase):
    """Requests session sharing tests"""
    pass  # tests are defined in the mixin


@override_settings(EMAIL_BACKEND="anymail.backends.postmark.PostmarkBackend")
class PostmarkBackendImproperlyConfiguredTests(SimpleTestCase, AnymailTestMixin):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'])
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r'\bPOSTMARK_SERVER_TOKEN\b')
        self.assertRegex(errmsg, r'\bANYMAIL_POSTMARK_SERVER_TOKEN\b')
