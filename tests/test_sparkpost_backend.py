# -*- coding: utf-8 -*-

from datetime import datetime, date
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
import os

import requests
import six
from django.core import mail
from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.utils.timezone import get_fixed_timezone, override as override_current_timezone, utc
from mock import patch
from sparkpost.exceptions import SparkPostAPIException

from anymail.exceptions import (AnymailAPIError, AnymailUnsupportedFeature, AnymailRecipientsRefused,
                                AnymailConfigurationError)
from anymail.message import attach_inline_image_file

from .utils import AnymailTestMixin, decode_att, SAMPLE_IMAGE_FILENAME, sample_image_path, sample_image_content


@override_settings(EMAIL_BACKEND='anymail.backends.sparkpost.SparkPostBackend',
                   ANYMAIL={'SPARKPOST_API_KEY': 'test_api_key'})
class SparkPostBackendMockAPITestCase(SimpleTestCase, AnymailTestMixin):
    """TestCase that uses SparkPostEmailBackend with a mocked transmissions.send API"""

    def setUp(self):
        super(SparkPostBackendMockAPITestCase, self).setUp()
        self.patch_send = patch('sparkpost.Transmissions.send', autospec=True)
        self.mock_send = self.patch_send.start()
        self.addCleanup(self.patch_send.stop)
        self.set_mock_response()

        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives('Subject', 'Text Body',
                                                   'from@example.com', ['to@example.com'])

    def set_mock_response(self, accepted=1, rejected=0, raw=None):
        # SparkPost.transmissions.send returns the parsed 'result' field
        # from the transmissions/send JSON response
        self.mock_send.return_value = raw or {
            "id": "12345678901234567890",
            "total_accepted_recipients": accepted,
            "total_rejected_recipients": rejected,
        }
        return self.mock_send.return_value

    def set_mock_failure(self, status_code=400, raw=b'{"errors":[{"message":"test error"}]}', encoding='utf-8'):
        # Need to build a real(-ish) requests.Response for SparkPostAPIException
        response = requests.Response()
        response.status_code = status_code
        response.encoding = encoding
        response.raw = six.BytesIO(raw)
        response.url = "/mock/send"
        self.mock_send.side_effect = SparkPostAPIException(response)

    def get_send_params(self):
        """Returns kwargs params passed to the mock send API.

        Fails test if API wasn't called.
        """
        if self.mock_send.call_args is None:
            raise AssertionError("API was not called")
        (args, kwargs) = self.mock_send.call_args
        return kwargs

    def get_send_api_key(self):
        """Returns api_key on SparkPost api object used for mock send

        Fails test if API wasn't called
        """
        if self.mock_send.call_args is None:
            raise AssertionError("API was not called")
        (args, kwargs) = self.mock_send.call_args
        mock_self = args[0]
        return mock_self.api_key

    def assert_esp_not_called(self, msg=None):
        if self.mock_send.called:
            raise AssertionError(msg or "ESP API was called and shouldn't have been")


class SparkPostBackendStandardEmailTests(SparkPostBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail('Subject here', 'Here is the message.',
                       'from@example.com', ['to@example.com'], fail_silently=False)
        params = self.get_send_params()
        self.assertEqual(params['subject'], "Subject here")
        self.assertEqual(params['text'], "Here is the message.")
        self.assertEqual(params['from_email'], "from@example.com")
        self.assertEqual(params['recipients'], ["to@example.com"])

        self.assertEqual(self.get_send_api_key(), 'test_api_key')

    def test_name_addr(self):
        """Make sure RFC2822 name-addr format (with display-name) is allowed

        (Test both sender and recipient addresses)
        """
        self.set_mock_response(accepted=6)
        msg = mail.EmailMessage(
            'Subject', 'Message', 'From Name <from@example.com>',
            ['Recipient #1 <to1@example.com>', 'to2@example.com'],
            cc=['Carbon Copy <cc1@example.com>', 'cc2@example.com'],
            bcc=['Blind Copy <bcc1@example.com>', 'bcc2@example.com'])
        msg.send()
        params = self.get_send_params()
        self.assertEqual(params['from_email'], "From Name <from@example.com>")
        # We pre-parse the to-field emails (merge_data also gets attached there):
        self.assertEqual(params['recipients'], ['Recipient #1 <to1@example.com>', 'to2@example.com'])
        # We let python-sparkpost parse the other email fields:
        self.assertEqual(params['cc'], ['Carbon Copy <cc1@example.com>', 'cc2@example.com'])
        self.assertEqual(params['bcc'], ['Blind Copy <bcc1@example.com>', 'bcc2@example.com'])

    def test_email_message(self):
        self.set_mock_response(accepted=6)
        email = mail.EmailMessage(
            'Subject', 'Body goes here', 'from@example.com',
            ['to1@example.com', 'Also To <to2@example.com>'],
            bcc=['bcc1@example.com', 'Also BCC <bcc2@example.com>'],
            cc=['cc1@example.com', 'Also CC <cc2@example.com>'],
            headers={'Reply-To': 'another@example.com',
                     'X-MyHeader': 'my value',
                     'Message-ID': 'mycustommsgid@example.com'})
        email.send()
        params = self.get_send_params()
        self.assertEqual(params['subject'], "Subject")
        self.assertEqual(params['text'], "Body goes here")
        self.assertEqual(params['from_email'], "from@example.com")
        self.assertEqual(params['recipients'], ['to1@example.com', 'Also To <to2@example.com>'])
        self.assertEqual(params['bcc'], ['bcc1@example.com', 'Also BCC <bcc2@example.com>'])
        self.assertEqual(params['cc'], ['cc1@example.com', 'Also CC <cc2@example.com>'])
        self.assertEqual(params['custom_headers'], {
            'Reply-To': 'another@example.com',
            'X-MyHeader': 'my value',
            'Message-ID': 'mycustommsgid@example.com'})

    def test_html_message(self):
        text_content = 'This is an important message.'
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMultiAlternatives('Subject', text_content,
                                            'from@example.com', ['to@example.com'])
        email.attach_alternative(html_content, "text/html")
        email.send()
        params = self.get_send_params()
        self.assertEqual(params['text'], text_content)
        self.assertEqual(params['html'], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn('attachments', params)

    def test_html_only_message(self):
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMessage('Subject', html_content, 'from@example.com', ['to@example.com'])
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        params = self.get_send_params()
        self.assertNotIn('text', params)
        self.assertEqual(params['html'], html_content)

    def test_reply_to(self):
        email = mail.EmailMessage('Subject', 'Body goes here', 'from@example.com', ['to1@example.com'],
                                  reply_to=['reply@example.com', 'Other <reply2@example.com>'],
                                  headers={'X-Other': 'Keep'})
        email.send()
        params = self.get_send_params()
        self.assertEqual(params['reply_to'], 'reply@example.com, Other <reply2@example.com>')
        self.assertEqual(params['custom_headers'], {'X-Other': 'Keep'})  # don't lose other headers

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(filename="test.txt", content=text_content, mimetype="text/plain")

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        # Should work with a MIMEBase object (also tests no filename)...
        pdf_content = b"PDF\xb4 pretend this is valid pdf params"
        mimeattachment = MIMEBase('application', 'pdf')
        mimeattachment.set_payload(pdf_content)
        self.message.attach(mimeattachment)

        self.message.send()
        params = self.get_send_params()
        attachments = params['attachments']
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]['type'], 'text/plain')
        self.assertEqual(attachments[0]['name'], 'test.txt')
        self.assertEqual(decode_att(attachments[0]['data']).decode('ascii'), text_content)
        self.assertEqual(attachments[1]['type'], 'image/png')  # inferred from filename
        self.assertEqual(attachments[1]['name'], 'test.png')
        self.assertEqual(decode_att(attachments[1]['data']), png_content)
        self.assertEqual(attachments[2]['type'], 'application/pdf')
        self.assertEqual(attachments[2]['name'], '')  # none
        self.assertEqual(decode_att(attachments[2]['data']), pdf_content)
        # Make sure the image attachment is not treated as embedded:
        self.assertNotIn('inline_images', params)

    def test_unicode_attachment_correctly_decoded(self):
        # Slight modification from the Django unicode docs:
        # http://django.readthedocs.org/en/latest/ref/unicode.html#email
        self.message.attach(u"Une pièce jointe.html", u'<p>\u2019</p>', mimetype='text/html')
        self.message.send()
        params = self.get_send_params()
        attachments = params['attachments']
        self.assertEqual(len(attachments), 1)

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)
        html_content = '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['html'], html_content)

        self.assertEqual(len(params['inline_images']), 1)
        self.assertEqual(params['inline_images'][0]["type"], "image/png")
        self.assertEqual(params['inline_images'][0]["name"], cid)
        self.assertEqual(decode_att(params['inline_images'][0]["data"]), image_data)
        # Make sure neither the html nor the inline image is treated as an attachment:
        self.assertNotIn('attachments', params)

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        self.message.attach_file(image_path)  # option 1: attach as a file

        image = MIMEImage(image_data)  # option 2: construct the MIMEImage and attach it directly
        self.message.attach(image)

        self.message.send()
        params = self.get_send_params()
        attachments = params['attachments']
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["type"], "image/png")
        self.assertEqual(attachments[0]["name"], image_filename)
        self.assertEqual(decode_att(attachments[0]["data"]), image_data)
        self.assertEqual(attachments[1]["type"], "image/png")
        self.assertEqual(attachments[1]["name"], "")  # unknown -- not attached as file
        self.assertEqual(decode_att(attachments[1]["data"]), image_data)
        # Make sure the image attachments are not treated as embedded:
        self.assertNotIn('inline_images', params)

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
        """Empty to, cc, bcc, and reply_to shouldn't generate empty headers"""
        self.message.send()
        params = self.get_send_params()
        self.assertNotIn('cc', params)
        self.assertNotIn('bcc', params)
        self.assertNotIn('reply_to', params)

        # Test empty `to` -- but send requires at least one recipient somewhere (like cc)
        self.message.to = []
        self.message.cc = ['cc@example.com']
        self.message.send()
        params = self.get_send_params()
        self.assertNotIn('recipients', params)

    def test_api_failure(self):
        failure_response = b"""{ "errors": [ {
            "message": "Something went wrong",
            "description": "Helpful explanation from your ESP"
        } ] }"""
        self.set_mock_failure(raw=failure_response)
        with self.assertRaisesMessage(AnymailAPIError, "Helpful explanation from your ESP"):
            self.message.send()

    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        self.set_mock_failure()
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)


class SparkPostBackendAnymailFeatureTests(SparkPostBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_metadata(self):
        self.message.metadata = {'user_id': "12345", 'items': 'spark, post'}
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['metadata'], {'user_id': "12345", 'items': 'spark, post'})

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        # SparkPost expects ISO-8601 YYYY-MM-DDTHH:MM:SS+-HH:MM
        with override_current_timezone(utc_plus_6):
            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            params = self.get_send_params()
            self.assertEqual(params['start_time'], "2016-03-04T05:06:07-08:00")

            # Explicit UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc)
            self.message.send()
            params = self.get_send_params()
            self.assertEqual(params['start_time'], "2016-03-04T05:06:07+00:00")

            # Timezone-naive datetime assumed to be Django current_timezone
            # (also checks stripping microseconds)
            self.message.send_at = datetime(2022, 10, 11, 12, 13, 14, 567)
            self.message.send()
            params = self.get_send_params()
            self.assertEqual(params['start_time'], "2022-10-11T12:13:14+06:00")

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            params = self.get_send_params()
            self.assertEqual(params['start_time'], "2022-10-22T00:00:00+06:00")

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            params = self.get_send_params()
            self.assertEqual(params['start_time'], "2022-05-06T07:08:09+00:00")

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "2022-10-13T18:02:00-11:30"
            self.message.send()
            params = self.get_send_params()
            self.assertEqual(params['start_time'], "2022-10-13T18:02:00-11:30")

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['campaign'], "receipt")

        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'multiple tags'):
            self.message.send()

    def test_tracking(self):
        # Test one way...
        self.message.track_opens = True
        self.message.track_clicks = False
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['track_opens'], True)
        self.assertEqual(params['track_clicks'], False)

        # ...and the opposite way
        self.message.track_opens = False
        self.message.track_clicks = True
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['track_opens'], False)
        self.assertEqual(params['track_clicks'], True)

    def test_template_id(self):
        message = mail.EmailMultiAlternatives(from_email='from@example.com', to=['to@example.com'])
        message.template_id = "welcome_template"
        message.send()
        params = self.get_send_params()
        self.assertEqual(params['template'], "welcome_template")
        # SparkPost disallows all content (even empty strings) with stored template:
        self.assertNotIn('subject', params)
        self.assertNotIn('text', params)
        self.assertNotIn('html', params)

    def test_merge_data(self):
        self.set_mock_response(accepted=2)
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.body = "Hi %recipient.name%. Welcome to %recipient.group% at %recipient.site%."
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},  # and leave group undefined
            'nobody@example.com': {'name': "Not a recipient for this message"},
        }
        self.message.merge_global_data = {'group': "Users", 'site': "ExampleCo"}
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['recipients'], [
            {'address': {'email': 'alice@example.com'},
             'substitution_data': {'name': "Alice", 'group': "Developers"}},
            {'address': {'email': 'bob@example.com', 'name': 'Bob'},
             'substitution_data': {'name': "Bob"}}
        ])
        self.assertEqual(params['substitution_data'], {'group': "Users", 'site': "ExampleCo"})

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        params = self.get_send_params()
        self.assertNotIn('campaign', params)
        self.assertNotIn('metadata', params)
        self.assertNotIn('start_time', params)
        self.assertNotIn('substitution_data', params)
        self.assertNotIn('template', params)
        self.assertNotIn('track_clicks', params)
        self.assertNotIn('track_opens', params)

    def test_esp_extra(self):
        self.message.esp_extra = {
            'future_sparkpost_send_param': 'some-value',
        }
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['future_sparkpost_send_param'], 'some-value')

    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent """
        response_content = {
            'id': '9876543210',
            'total_accepted_recipients': 1,
            'total_rejected_recipients': 0,
        }
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com', ['to1@example.com'],)
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {'queued'})
        self.assertEqual(msg.anymail_status.message_id, '9876543210')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'queued')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].message_id, '9876543210')
        self.assertEqual(msg.anymail_status.esp_response, response_content)

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)  # exception is tested later
    def test_send_all_rejected(self):
        """The anymail_status should be 'rejected' when all recipients rejected"""
        self.set_mock_response(accepted=0, rejected=2)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com',
                                ['to1@example.com', 'to2@example.com'],)
        msg.send()
        self.assertEqual(msg.anymail_status.status, {'rejected'})
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'rejected')
        self.assertEqual(msg.anymail_status.recipients['to2@example.com'].status, 'rejected')

    def test_send_some_rejected(self):
        """The anymail_status should be 'unknown' when some recipients accepted and some rejected"""
        self.set_mock_response(accepted=1, rejected=1)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com',
                                ['to1@example.com', 'to2@example.com'],)
        msg.send()
        self.assertEqual(msg.anymail_status.status, {'unknown'})
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'unknown')
        self.assertEqual(msg.anymail_status.recipients['to2@example.com'].status, 'unknown')

    def test_send_unexpected_count(self):
        """The anymail_status should be 'unknown' when the total result count
           doesn't match the number of recipients"""
        self.set_mock_response(accepted=3, rejected=0)  # but only 2 in the to-list
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com',
                                ['to1@example.com', 'to2@example.com'],)
        msg.send()
        self.assertEqual(msg.anymail_status.status, {'unknown'})
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'unknown')
        self.assertEqual(msg.anymail_status.recipients['to2@example.com'].status, 'unknown')

    # noinspection PyUnresolvedReferences
    def test_send_failed_anymail_status(self):
        """ If the send fails, anymail_status should contain initial values"""
        self.set_mock_failure()
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertIsNone(self.message.anymail_status.esp_response)

    # noinspection PyUnresolvedReferences
    def test_send_unparsable_response(self):
        """If the send succeeds, but result is unexpected format, should raise an API exception"""
        response_content = {'wrong': 'format'}
        self.set_mock_response(raw=response_content)
        with self.assertRaises(AnymailAPIError):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(self.message.anymail_status.esp_response, response_content)

    # test_json_serialization_errors:
    #   Although SparkPost will raise JSON serialization errors, they're coming
    #   from deep within the python-sparkpost implementation. Since it's an
    #   implementation detail of that package, Anymail doesn't try to catch or
    #   modify those errors.


class SparkPostBackendRecipientsRefusedTests(SparkPostBackendMockAPITestCase):
    """Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid"""

    def test_recipients_refused(self):
        self.set_mock_response(accepted=0, rejected=2)
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['invalid@localhost', 'reject@example.com'])
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_response(accepted=0, rejected=2)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com',
                              ['invalid@localhost', 'reject@example.com'],
                              fail_silently=True)
        self.assertEqual(sent, 0)

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        self.set_mock_response(accepted=2, rejected=2)
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['invalid@localhost', 'valid@example.com',
                                 'reject@example.com', 'also.valid@example.com'])
        sent = msg.send()
        self.assertEqual(sent, 1)  # one message sent, successfully, to 2 of 4 recipients
        status = msg.anymail_status
        # We don't know which recipients were rejected
        self.assertEqual(status.recipients['invalid@localhost'].status, 'unknown')
        self.assertEqual(status.recipients['valid@example.com'].status, 'unknown')
        self.assertEqual(status.recipients['reject@example.com'].status, 'unknown')
        self.assertEqual(status.recipients['also.valid@example.com'].status, 'unknown')

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)
    def test_settings_override(self):
        """No exception with ignore setting"""
        self.set_mock_response(accepted=0, rejected=2)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com',
                              ['invalid@localhost', 'reject@example.com'])
        self.assertEqual(sent, 1)  # refused message is included in sent count


@override_settings(EMAIL_BACKEND="anymail.backends.sparkpost.SparkPostBackend")
class SparkPostBackendImproperlyConfiguredTests(SimpleTestCase, AnymailTestMixin):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(AnymailConfigurationError) as cm:
            mail.get_connection()  # this init's SparkPost without actually trying to send anything
        errmsg = str(cm.exception)
        # Make sure the error mentions the different places to set the key
        self.assertRegex(errmsg, r'\bSPARKPOST_API_KEY\b')
        self.assertRegex(errmsg, r'\bANYMAIL_SPARKPOST_API_KEY\b')

    def test_api_key_in_env(self):
        """SparkPost package allows API key in env var; make sure Anymail works with that"""
        with patch.dict(
                os.environ,
                {'SPARKPOST_API_KEY': 'key_from_environment'}):
            conn = mail.get_connection()
            # Poke into implementation details to verify:
            self.assertIsNone(conn.api_key)  # Anymail prop
            self.assertEqual(conn.sp.api_key, 'key_from_environment')  # SparkPost prop
