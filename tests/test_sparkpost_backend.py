import json
from datetime import date, datetime
from decimal import Decimal
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.text import MIMEText

from django.core import mail
from django.test import override_settings, tag
from django.utils.timezone import get_fixed_timezone, override as override_current_timezone, utc

from anymail.exceptions import (
    AnymailAPIError, AnymailConfigurationError, AnymailRecipientsRefused,
    AnymailSerializationError, AnymailUnsupportedFeature)
from anymail.message import attach_inline_image_file

from .mock_requests_backend import RequestsBackendMockAPITestCase
from .utils import SAMPLE_IMAGE_FILENAME, decode_att, sample_image_content, sample_image_path


@tag('sparkpost')
@override_settings(EMAIL_BACKEND='anymail.backends.sparkpost.EmailBackend',
                   ANYMAIL={'SPARKPOST_API_KEY': 'test_api_key'})
class SparkPostBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    """TestCase that uses SparkPostEmailBackend with a mocked transmissions.send API"""

    DEFAULT_RAW_RESPONSE = b"""{
        "results": {
            "id": "12345678901234567890",
            "total_accepted_recipients": 1,
            "total_rejected_recipients": 0
        }
    }"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives('Subject', 'Text Body',
                                                   'from@example.com', ['to@example.com'])

    def set_mock_result(self, accepted=1, rejected=0, id="12345678901234567890"):
        """Set a mock response that reflects count of accepted/rejected recipients"""
        raw = json.dumps({
            "results": {
                "id": id,
                "total_accepted_recipients": accepted,
                "total_rejected_recipients": rejected,
            }
        }).encode("utf-8")
        self.set_mock_response(raw=raw)
        return raw


@tag('sparkpost')
class SparkPostBackendStandardEmailTests(SparkPostBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail('Subject here', 'Here is the message.',
                       'from@example.com', ['to@example.com'], fail_silently=False)

        self.assert_esp_called('/api/v1/transmissions/')

        headers = self.get_api_call_headers()
        self.assertEqual("test_api_key", headers["Authorization"])

        data = self.get_api_call_json()
        self.assertEqual(data["content"]["subject"], "Subject here")
        self.assertEqual(data["content"]["text"], "Here is the message.")
        self.assertEqual(data["content"]["from"], "from@example.com")
        self.assertEqual(data['recipients'], [{
            "address": {"email": "to@example.com", "header_to": "to@example.com"}
        }])

    def test_name_addr(self):
        """Make sure RFC2822 name-addr format (with display-name) is allowed

        (Test both sender and recipient addresses)
        """
        self.set_mock_result(accepted=6)
        msg = mail.EmailMessage(
            'Subject', 'Message', 'From Name <from@example.com>',
            ['Recipient #1 <to1@example.com>', 'to2@example.com'],
            cc=['Carbon Copy <cc1@example.com>', 'cc2@example.com'],
            bcc=['Blind Copy <bcc1@example.com>', 'bcc2@example.com'])
        msg.send()

        data = self.get_api_call_json()
        self.assertEqual(data["content"]["from"], "From Name <from@example.com>")
        # This also checks recipient generation for cc and bcc. Because it's *not*
        # a batch send, each recipient should see a To header reflecting all To addresses.
        self.assertCountEqual(data["recipients"], [
            {"address": {
                "email": "to1@example.com",
                "header_to": "Recipient #1 <to1@example.com>, to2@example.com",
            }},
            {"address": {
                "email": "to2@example.com",
                "header_to": "Recipient #1 <to1@example.com>, to2@example.com",
            }},
            # cc and bcc must be explicitly specified as recipients
            {"address": {
                "email": "cc1@example.com",
                "header_to": "Recipient #1 <to1@example.com>, to2@example.com",
            }},
            {"address": {
                "email": "cc2@example.com",
                "header_to": "Recipient #1 <to1@example.com>, to2@example.com",
            }},
            {"address": {
                "email": "bcc1@example.com",
                "header_to": "Recipient #1 <to1@example.com>, to2@example.com",
            }},
            {"address": {
                "email": "bcc2@example.com",
                "header_to": "Recipient #1 <to1@example.com>, to2@example.com",
            }},
        ])
        # Make sure we added a formatted Cc header visible to recipients
        # (and not a Bcc header)
        self.assertEqual(data["content"]["headers"], {
            "Cc": "Carbon Copy <cc1@example.com>, cc2@example.com"
        })

    def test_custom_headers(self):
        self.set_mock_result(accepted=6)
        email = mail.EmailMessage(
            'Subject', 'Body goes here', 'from@example.com', ['to1@example.com'],
            cc=['cc1@example.com'],
            headers={'Reply-To': 'another@example.com',
                     'X-MyHeader': 'my value',
                     'Message-ID': 'mycustommsgid@example.com'})
        email.send()

        data = self.get_api_call_json()
        self.assertEqual(data["content"]["headers"], {
            # Reply-To moved to separate param (below)
            "X-MyHeader": "my value",
            "Message-ID": "mycustommsgid@example.com",
            "Cc": "cc1@example.com",  # Cc header added
        })
        self.assertEqual(data["content"]["reply_to"], "another@example.com")

    def test_html_message(self):
        text_content = 'This is an important message.'
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMultiAlternatives('Subject', text_content,
                                            'from@example.com', ['to@example.com'])
        email.attach_alternative(html_content, "text/html")
        email.send()

        data = self.get_api_call_json()
        self.assertEqual(data["content"]["text"], text_content)
        self.assertEqual(data["content"]["html"], html_content)
        # Don't accidentally send the html part as an attachment:
        self.assertNotIn("attachments", data["content"])

    def test_html_only_message(self):
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMessage('Subject', html_content, 'from@example.com', ['to@example.com'])
        email.content_subtype = "html"  # Main content is now text/html
        email.send()

        data = self.get_api_call_json()
        self.assertNotIn("text", data["content"])
        self.assertEqual(data["content"]["html"], html_content)

    def test_reply_to(self):
        email = mail.EmailMessage('Subject', 'Body goes here', 'from@example.com', ['to1@example.com'],
                                  reply_to=['reply@example.com', 'Other <reply2@example.com>'],
                                  headers={'X-Other': 'Keep'})
        email.send()

        data = self.get_api_call_json()
        self.assertEqual(data["content"]["reply_to"],
                         "reply@example.com, Other <reply2@example.com>")
        self.assertEqual(data["content"]["headers"], {"X-Other": "Keep"})  # don't lose other headers

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
        data = self.get_api_call_json()
        attachments = data["content"]["attachments"]
        self.assertEqual(len(attachments), 3)
        self.assertEqual(attachments[0]["type"], "text/plain")
        self.assertEqual(attachments[0]["name"], "test.txt")
        self.assertEqual(decode_att(attachments[0]["data"]).decode("ascii"), text_content)
        self.assertEqual(attachments[1]["type"], "image/png")  # inferred from filename
        self.assertEqual(attachments[1]["name"], "test.png")
        self.assertEqual(decode_att(attachments[1]["data"]), png_content)
        self.assertEqual(attachments[2]["type"], "application/pdf")
        self.assertEqual(attachments[2]["name"], "")  # none
        self.assertEqual(decode_att(attachments[2]["data"]), pdf_content)
        # Make sure the image attachment is not treated as embedded:
        self.assertNotIn("inline_images", data["content"])

    def test_unicode_attachment_correctly_decoded(self):
        # Slight modification from the Django unicode docs:
        # http://django.readthedocs.org/en/latest/ref/unicode.html#email
        self.message.attach("Une pièce jointe.html", '<p>\u2019</p>', mimetype='text/html')
        self.message.send()
        data = self.get_api_call_json()
        attachments = data["content"]["attachments"]
        self.assertEqual(len(attachments), 1)

    def test_attachment_charset(self):
        # SparkPost allows charset param in attachment type
        self.message.attach(MIMEText("Une pièce jointe", "plain", "iso8859-1"))
        self.message.send()
        data = self.get_api_call_json()
        attachment = data["content"]["attachments"][0]
        self.assertEqual(attachment["type"], 'text/plain; charset="iso8859-1"')
        self.assertEqual(decode_att(attachment["data"]), "Une pièce jointe".encode("iso8859-1"))

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)
        html_content = '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["content"]["html"], html_content)

        self.assertEqual(len(data["content"]["inline_images"]), 1)
        self.assertEqual(data["content"]["inline_images"][0]["type"], "image/png")
        self.assertEqual(data["content"]["inline_images"][0]["name"], cid)
        self.assertEqual(decode_att(data["content"]["inline_images"][0]["data"]), image_data)
        # Make sure neither the html nor the inline image is treated as an attachment:
        self.assertNotIn("attachments", data["content"])

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        self.message.attach_file(image_path)  # option 1: attach as a file

        image = MIMEImage(image_data)  # option 2: construct the MIMEImage and attach it directly
        self.message.attach(image)

        self.message.send()
        data = self.get_api_call_json()
        attachments = data["content"]["attachments"]
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0]["type"], "image/png")
        self.assertEqual(attachments[0]["name"], image_filename)
        self.assertEqual(decode_att(attachments[0]["data"]), image_data)
        self.assertEqual(attachments[1]["type"], "image/png")
        self.assertEqual(attachments[1]["name"], "")  # unknown -- not attached as file
        self.assertEqual(decode_att(attachments[1]["data"]), image_data)
        # Make sure the image attachments are not treated as embedded:
        self.assertNotIn("inline_images", data["content"])

    def test_multiple_html_alternatives(self):
        # Multiple text/html alternatives not allowed
        self.message.attach_alternative("<p>First html is OK</p>", "text/html")
        self.message.attach_alternative("<p>But not second html</p>", "text/html")
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    def test_amp_html_alternative(self):
        # SparkPost *does* support text/x-amp-html alongside text/html
        self.message.attach_alternative("<p>HTML</p>", "text/html")
        self.message.attach_alternative("<p>And AMP HTML</p>", "text/x-amp-html")
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["content"]["html"], "<p>HTML</p>")
        self.assertEqual(data["content"]["amp_html"], "<p>And AMP HTML</p>")

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
        data = self.get_api_call_json()
        self.assertNotIn("headers", data["content"])  # No Cc, Bcc or Reply-To header
        self.assertNotIn("reply_to", data["content"])

    def test_empty_to(self):
        # Test empty `to` -- but send requires at least one recipient somewhere (like cc)
        self.message.to = []
        self.message.cc = ["cc@example.com"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["recipients"], [{
            "address": {
                "email": "cc@example.com",
                # This results in a message with an empty To header, as desired:
                "header_to": "",
            },
        }])

    def test_api_failure(self):
        self.set_mock_response(status_code=400)
        with self.assertRaisesMessage(AnymailAPIError, "SparkPost API response 400"):
            self.message.send()

    def test_api_failure_fail_silently(self):
        # Make sure fail_silently is respected
        self.set_mock_response(status_code=400)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)

    def test_api_error_includes_details(self):
        """AnymailAPIError should include ESP's error message"""
        failure_response = b"""{
            "errors": [{
                "message": "Helpful explanation from your ESP"
            }]
        }"""
        self.set_mock_response(status_code=400, raw=failure_response)
        with self.assertRaisesMessage(AnymailAPIError, "Helpful explanation from your ESP"):
            self.message.send()


@tag('sparkpost')
class SparkPostBackendAnymailFeatureTests(SparkPostBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_envelope_sender(self):
        self.message.envelope_sender = "bounce-handler@bounces.example.com"
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["return_path"], "bounce-handler@bounces.example.com")

    def test_metadata(self):
        self.message.metadata = {'user_id': "12345", 'items': 'spark, post'}
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["metadata"], {'user_id': "12345", 'items': 'spark, post'})

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        # SparkPost expects ISO-8601 YYYY-MM-DDTHH:MM:SS+-HH:MM
        with override_current_timezone(utc_plus_6):
            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["options"]["start_time"], "2016-03-04T05:06:07-08:00")

            # Explicit UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["options"]["start_time"], "2016-03-04T05:06:07+00:00")

            # Timezone-naive datetime assumed to be Django current_timezone
            # (also checks stripping microseconds)
            self.message.send_at = datetime(2022, 10, 11, 12, 13, 14, 567)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["options"]["start_time"], "2022-10-11T12:13:14+06:00")

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["options"]["start_time"], "2022-10-22T00:00:00+06:00")

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["options"]["start_time"], "2022-05-06T07:08:09+00:00")

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "2022-10-13T18:02:00-11:30"
            self.message.send()
            data = self.get_api_call_json()
            self.assertEqual(data["options"]["start_time"], "2022-10-13T18:02:00-11:30")

    def test_tags(self):
        self.message.tags = ["receipt"]
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["campaign_id"], "receipt")

        self.message.tags = ["receipt", "repeat-user"]
        with self.assertRaisesMessage(AnymailUnsupportedFeature, 'multiple tags'):
            self.message.send()

    def test_tracking(self):
        # Test one way...
        self.message.track_opens = True
        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["options"]["open_tracking"], True)
        self.assertEqual(data["options"]["click_tracking"], False)

        # ...and the opposite way
        self.message.track_opens = False
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["options"]["open_tracking"], False)
        self.assertEqual(data["options"]["click_tracking"], True)

    def test_template_id(self):
        message = mail.EmailMultiAlternatives(from_email='from@example.com', to=['to@example.com'])
        message.template_id = "welcome_template"
        message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["content"]["template_id"], "welcome_template")
        # SparkPost disallows all content (even empty strings) with stored template:
        self.assertNotIn("subject", data["content"])
        self.assertNotIn("text", data["content"])
        self.assertNotIn("html", data["content"])

    def test_merge_data(self):
        self.set_mock_result(accepted=4)  # two 'to' plus one 'cc' for each 'to'
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.cc = ['cc@example.com']
        self.message.body = "Hi {{address.name}}. Welcome to {{group}} at {{site}}."
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},  # and leave group undefined
            'nobody@example.com': {'name': "Not a recipient for this message"},
        }
        self.message.merge_global_data = {'group': "Users", 'site': "ExampleCo"}

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual({"group": "Users", "site": "ExampleCo"}, data["substitution_data"])
        self.assertEqual([{
            "address": {"email": "alice@example.com", "header_to": "alice@example.com"},
            "substitution_data": {"name": "Alice", "group": "Developers"},
        }, {
            "address": {"email": "bob@example.com", "header_to": "Bob <bob@example.com>"},
            "substitution_data": {"name": "Bob"},
        }, {  # duplicated for cc recipients...
            "address": {"email": "cc@example.com", "header_to": "alice@example.com"},
            "substitution_data": {"name": "Alice", "group": "Developers"},
        }, {
            "address": {"email": "cc@example.com", "header_to": "Bob <bob@example.com>"},
            "substitution_data": {"name": "Bob"},
        }], data["recipients"])

    def test_merge_metadata(self):
        self.set_mock_result(accepted=2)
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.merge_metadata = {
            'alice@example.com': {'order_id': 123},
            'bob@example.com': {'order_id': 678, 'tier': 'premium'},
        }
        self.message.metadata = {'notification_batch': 'zx912'}

        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual([{
            "address": {"email": "alice@example.com", "header_to": "alice@example.com"},
            "metadata": {"order_id": 123},
        }, {
            "address": {"email": "bob@example.com", "header_to": "Bob <bob@example.com>"},
            "metadata": {"order_id": 678, "tier": "premium"}
        }], data["recipients"])
        self.assertEqual(data["metadata"], {"notification_batch": "zx912"})

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("campaign_id", data)
        self.assertNotIn("metadata", data)
        self.assertNotIn("options", data)  # covers start_time, click_tracking, open_tracking
        self.assertNotIn("substitution_data", data)
        self.assertNotIn("template_id", data["content"])

    def test_esp_extra(self):
        self.message.esp_extra = {
            "description": "The description",
            "options": {
                "transactional": True,
            },
            "content": {
                "use_draft_template": True,
                "ab_test_id": "highlight_support_links",
            },
        }
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["description"], "The description")
        self.assertEqual(data["options"], {
            "transactional": True,
            "click_tracking": True,  # deep merge
        })
        self.assertDictMatches({
            "use_draft_template": True,
            "ab_test_id": "highlight_support_links",
            "text": "Text Body",  # deep merge
            "subject": "Subject",  # deep merge
        }, data["content"])

    def test_send_attaches_anymail_status(self):
        """The anymail_status should be attached to the message when it is sent """
        response_content = self.set_mock_result(accepted=1, rejected=0, id="9876543210")
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com', ['to1@example.com'],)
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {'queued'})
        self.assertEqual(msg.anymail_status.message_id, '9876543210')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'queued')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].message_id, '9876543210')
        self.assertEqual(msg.anymail_status.esp_response.content, response_content)

    @override_settings(ANYMAIL_IGNORE_RECIPIENT_STATUS=True)  # exception is tested later
    def test_send_all_rejected(self):
        """The anymail_status should be 'rejected' when all recipients rejected"""
        self.set_mock_result(accepted=0, rejected=2)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com',
                                ['to1@example.com', 'to2@example.com'],)
        msg.send()
        self.assertEqual(msg.anymail_status.status, {'rejected'})
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'rejected')
        self.assertEqual(msg.anymail_status.recipients['to2@example.com'].status, 'rejected')

    def test_send_some_rejected(self):
        """The anymail_status should be 'unknown' when some recipients accepted and some rejected"""
        self.set_mock_result(accepted=1, rejected=1)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com',
                                ['to1@example.com', 'to2@example.com'],)
        msg.send()
        self.assertEqual(msg.anymail_status.status, {'unknown'})
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'unknown')
        self.assertEqual(msg.anymail_status.recipients['to2@example.com'].status, 'unknown')

    def test_send_unexpected_count(self):
        """The anymail_status should be 'unknown' when the total result count
           doesn't match the number of recipients"""
        self.set_mock_result(accepted=3, rejected=0)  # but only 2 in the to-list
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com',
                                ['to1@example.com', 'to2@example.com'],)
        msg.send()
        self.assertEqual(msg.anymail_status.status, {'unknown'})
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'unknown')
        self.assertEqual(msg.anymail_status.recipients['to2@example.com'].status, 'unknown')

    # noinspection PyUnresolvedReferences
    def test_send_failed_anymail_status(self):
        """ If the send fails, anymail_status should contain initial values"""
        self.set_mock_response(status_code=400)
        sent = self.message.send(fail_silently=True)
        self.assertEqual(sent, 0)
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertIsNone(self.message.anymail_status.esp_response)

    # noinspection PyUnresolvedReferences
    def test_send_unparsable_response(self):
        """If the send succeeds, but result is unexpected format, should raise an API exception"""
        response_content = b"""{"wrong": "format"}"""
        self.set_mock_response(raw=response_content)
        with self.assertRaises(AnymailAPIError):
            self.message.send()
        self.assertIsNone(self.message.anymail_status.status)
        self.assertIsNone(self.message.anymail_status.message_id)
        self.assertEqual(self.message.anymail_status.recipients, {})
        self.assertEqual(self.message.anymail_status.esp_response.content, response_content)

    def test_json_serialization_errors(self):
        """Try to provide more information about non-json-serializable data"""
        self.message.tags = [Decimal('19.99')]  # yeah, don't do this
        with self.assertRaises(AnymailSerializationError) as cm:
            self.message.send()
            print(self.get_api_call_json())
        err = cm.exception
        self.assertIsInstance(err, TypeError)  # compatibility with json.dumps
        self.assertIn("Don't know how to send this data to SparkPost", str(err))  # our added context
        self.assertRegex(str(err), r"Decimal.*is not JSON serializable")  # original message


@tag('sparkpost')
class SparkPostBackendRecipientsRefusedTests(SparkPostBackendMockAPITestCase):
    """Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid"""

    def test_recipients_refused(self):
        self.set_mock_result(accepted=0, rejected=2)
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                ['invalid@localhost', 'reject@example.com'])
        with self.assertRaises(AnymailRecipientsRefused):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_result(accepted=0, rejected=2)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com',
                              ['invalid@localhost', 'reject@example.com'],
                              fail_silently=True)
        self.assertEqual(sent, 0)

    def test_mixed_response(self):
        """If *any* recipients are valid or queued, no exception is raised"""
        self.set_mock_result(accepted=2, rejected=2)
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
        self.set_mock_result(accepted=0, rejected=2)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com',
                              ['invalid@localhost', 'reject@example.com'])
        self.assertEqual(sent, 1)  # refused message is included in sent count


@tag('sparkpost')
class SparkPostBackendConfigurationTests(SparkPostBackendMockAPITestCase):
    """Test various SparkPost client options"""

    @override_settings(ANYMAIL={})  # clear SPARKPOST_API_KEY from SparkPostBackendMockAPITestCase
    def test_missing_api_key(self):
        with self.assertRaises(AnymailConfigurationError) as cm:
            mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'])
        errmsg = str(cm.exception)
        # Make sure the error mentions the different places to set the key
        self.assertRegex(errmsg, r'\bSPARKPOST_API_KEY\b')
        self.assertRegex(errmsg, r'\bANYMAIL_SPARKPOST_API_KEY\b')

    @override_settings(ANYMAIL={
        "SPARKPOST_API_URL": "https://api.eu.sparkpost.com/api/v1",
        "SPARKPOST_API_KEY": "test_api_key",
    })
    def test_sparkpost_api_url(self):
        mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'])
        self.assert_esp_called("https://api.eu.sparkpost.com/api/v1/transmissions/")

        # can also override on individual connection (and even use non-versioned labs endpoint)
        connection = mail.get_connection(api_url="https://api.sparkpost.com/api/labs")
        mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'],
                       connection=connection)
        self.assert_esp_called("https://api.sparkpost.com/api/labs/transmissions/")

    def test_subaccount(self):
        # A likely use case is supplying subaccount for a particular message.
        # (For all messages, just set SPARKPOST_SUBACCOUNT in ANYMAIL settings.)
        connection = mail.get_connection(subaccount=123)
        mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'],
                       connection=connection)
        headers = self.get_api_call_headers()
        self.assertEqual(headers["X-MSYS-SUBACCOUNT"], 123)

        # Make sure we're not setting the header on non-subaccount sends
        mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'])
        headers = self.get_api_call_headers()
        self.assertNotIn("X-MSYS-SUBACCOUNT", headers)
