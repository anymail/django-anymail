from datetime import date, datetime
from textwrap import dedent

from email import message_from_bytes
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage

from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings, tag
from django.utils.timezone import get_fixed_timezone, override as override_current_timezone

from anymail.exceptions import (
    AnymailError, AnymailAPIError, AnymailInvalidAddress,
    AnymailRequestsAPIError, AnymailUnsupportedFeature)
from anymail.message import attach_inline_image_file

from .mock_requests_backend import RequestsBackendMockAPITestCase, SessionSharingTestCases
from .utils import (AnymailTestMixin, sample_email_content,
                    sample_image_content, sample_image_path, SAMPLE_IMAGE_FILENAME)


@tag('mailgun')
@override_settings(EMAIL_BACKEND='anymail.backends.mailgun.EmailBackend',
                   ANYMAIL={'MAILGUN_API_KEY': 'test_api_key'})
class MailgunBackendMockAPITestCase(RequestsBackendMockAPITestCase):
    DEFAULT_RAW_RESPONSE = b"""{
        "id": "<20160306015544.116301.25145@example.com>",
        "message": "Queued. Thank you."
    }"""

    def setUp(self):
        super().setUp()
        # Simple message useful for many tests
        self.message = mail.EmailMultiAlternatives('Subject', 'Text Body', 'from@example.com', ['to@example.com'])


@tag('mailgun')
class MailgunBackendStandardEmailTests(MailgunBackendMockAPITestCase):
    """Test backend support for Django standard email features"""

    def test_send_mail(self):
        """Test basic API for simple send"""
        mail.send_mail('Subject here', 'Here is the message.',
                       'from@example.com', ['to@example.com'], fail_silently=False)
        self.assert_esp_called('/example.com/messages')
        auth = self.get_api_call_auth()
        self.assertEqual(auth, ('api', 'test_api_key'))
        data = self.get_api_call_data()
        self.assertEqual(data['subject'], "Subject here")
        self.assertEqual(data['text'], "Here is the message.")
        self.assertEqual(data['from'], ["from@example.com"])
        self.assertEqual(data['to'], ["to@example.com"])

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
        data = self.get_api_call_data()
        self.assertEqual(data['from'], ["From Name <from@example.com>"])
        self.assertEqual(data['to'], ['Recipient #1 <to1@example.com>', 'to2@example.com'])
        self.assertEqual(data['cc'], ['Carbon Copy <cc1@example.com>', 'cc2@example.com'])
        self.assertEqual(data['bcc'], ['Blind Copy <bcc1@example.com>', 'bcc2@example.com'])

    def test_email_message(self):
        email = mail.EmailMessage(
            'Subject', 'Body goes here', 'from@example.com',
            ['to1@example.com', 'Also To <to2@example.com>'],
            bcc=['bcc1@example.com', 'Also BCC <bcc2@example.com>'],
            cc=['cc1@example.com', 'Also CC <cc2@example.com>'],
            headers={'Reply-To': 'another@example.com',
                     'X-MyHeader': 'my value',
                     'Message-ID': 'mycustommsgid@example.com'})
        email.send()
        data = self.get_api_call_data()
        self.assertEqual(data['subject'], "Subject")
        self.assertEqual(data['text'], "Body goes here")
        self.assertEqual(data['from'], ["from@example.com"])
        self.assertEqual(data['to'], ['to1@example.com', 'Also To <to2@example.com>'])
        self.assertEqual(data['bcc'], ['bcc1@example.com', 'Also BCC <bcc2@example.com>'])
        self.assertEqual(data['cc'], ['cc1@example.com', 'Also CC <cc2@example.com>'])
        self.assertEqual(data['h:Reply-To'], "another@example.com")
        self.assertEqual(data['h:X-MyHeader'], 'my value')
        self.assertEqual(data['h:Message-ID'], 'mycustommsgid@example.com')
        self.assertNotIn('recipient-variables', data)  # multiple recipients, but not a batch send

    def test_html_message(self):
        text_content = 'This is an important message.'
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMultiAlternatives('Subject', text_content,
                                            'from@example.com', ['to@example.com'])
        email.attach_alternative(html_content, "text/html")
        email.send()
        data = self.get_api_call_data()
        self.assertEqual(data['text'], text_content)
        self.assertEqual(data['html'], html_content)
        # Don't accidentally send the html part as an attachment:
        files = self.get_api_call_files(required=False)
        self.assertFalse(files)

    def test_html_only_message(self):
        html_content = '<p>This is an <strong>important</strong> message.</p>'
        email = mail.EmailMessage('Subject', html_content, 'from@example.com', ['to@example.com'])
        email.content_subtype = "html"  # Main content is now text/html
        email.send()
        data = self.get_api_call_data()
        self.assertNotIn('text', data)
        self.assertEqual(data['html'], html_content)

    def test_reply_to(self):
        email = mail.EmailMessage('Subject', 'Body goes here', 'from@example.com', ['to1@example.com'],
                                  reply_to=['reply@example.com', 'Other <reply2@example.com>'],
                                  headers={'X-Other': 'Keep'})
        email.send()
        data = self.get_api_call_data()
        self.assertEqual(data['h:Reply-To'], 'reply@example.com, Other <reply2@example.com>')
        self.assertEqual(data['h:X-Other'], 'Keep')  # don't lose other headers

    def test_attachments(self):
        text_content = "* Item one\n* Item two\n* Item three"
        self.message.attach(filename="test.txt", content=text_content, mimetype="text/plain")

        # Should guess mimetype if not provided...
        png_content = b"PNG\xb4 pretend this is the contents of a png file"
        self.message.attach(filename="test.png", content=png_content)

        # Should work with a MIMEBase object...
        pdf_content = b"PDF\xb4 pretend this is valid pdf data"
        mimeattachment = MIMEBase('application', 'pdf')
        mimeattachment.set_payload(pdf_content)
        mimeattachment["Content-Disposition"] = 'attachment; filename="custom filename"'  # Mailgun requires filename
        self.message.attach(mimeattachment)

        # And also with an message/rfc822 attachment
        forwarded_email_content = sample_email_content()
        forwarded_email = message_from_bytes(forwarded_email_content)
        rfcmessage = MIMEBase("message", "rfc822")
        rfcmessage.add_header("Content-Disposition", "attachment",
                              filename="forwarded message")  # Mailgun requires filename
        rfcmessage.attach(forwarded_email)
        self.message.attach(rfcmessage)

        self.message.send()
        files = self.get_api_call_files()
        attachments = [value for (field, value) in files if field == 'attachment']
        self.assertEqual(len(attachments), 4)
        self.assertEqual(attachments[0], ('test.txt', text_content, 'text/plain'))
        self.assertEqual(attachments[1], ('test.png', png_content, 'image/png'))  # type inferred from filename
        self.assertEqual(attachments[2], ("custom filename", pdf_content, 'application/pdf'))
        # Email messages can get a bit changed with respect to whitespace characters
        # in headers, without breaking the message, so we tolerate that:
        self.assertEqual(attachments[3][0], "forwarded message")
        self.assertEqualIgnoringHeaderFolding(
            attachments[3][1],
            b'Content-Type: message/rfc822\nMIME-Version: 1.0\n' +
            b'Content-Disposition: attachment; filename="forwarded message"\n' +
            b'\n' + forwarded_email_content)
        self.assertEqual(attachments[3][2], 'message/rfc822')

        # Make sure the image attachment is not treated as embedded:
        inlines = [value for (field, value) in files if field == 'inline']
        self.assertEqual(len(inlines), 0)

    def test_unicode_attachment_correctly_decoded(self):
        self.message.attach("Une pièce jointe.html", '<p>\u2019</p>', mimetype='text/html')
        self.message.send()

        # Verify the RFC 7578 compliance workaround has kicked in:
        data = self.get_api_call_data()
        if isinstance(data, dict):  # workaround not needed or used (but let's double check actual request)
            workaround = False
            prepared = self.get_api_prepared_request()
            data = prepared.body
        else:
            workaround = True
        data = data.decode("utf-8").replace("\r\n", "\n")
        self.assertNotIn("filename*=", data)  # No RFC 2231 encoding
        self.assertIn('Content-Disposition: form-data; name="attachment"; filename="Une pièce jointe.html"', data)

        if workaround:
            files = self.get_api_call_files(required=False)
            self.assertFalse(files)  # files should have been moved to formdata body

    def test_rfc_7578_compliance(self):
        # Check some corner cases in the workaround that undoes RFC 2231 multipart/form-data encoding...
        self.message.subject = "Testing for filename*=utf-8''problems"
        self.message.body = "The attached message should have an attachment named 'vedhæftet fil.txt'"
        # A forwarded message with its own attachment:
        forwarded_message = dedent("""\
            MIME-Version: 1.0
            From: sender@example.com
            Subject: This is a test message
            Content-Type: multipart/mixed; boundary="boundary"

            --boundary
            Content-Type: text/plain

            This message has an attached file with a non-ASCII filename.
            --boundary
            Content-Type: text/plain; name*=utf-8''vedh%C3%A6ftet%20fil.txt
            Content-Disposition: attachment; filename*=utf-8''vedh%C3%A6ftet%20fil.txt

            This is an attachment.
            --boundary--
            """)
        self.message.attach("besked med vedhæftede filer", forwarded_message, "message/rfc822")
        self.message.send()

        data = self.get_api_call_data()
        if isinstance(data, dict):  # workaround not needed or used (but let's double check actual request)
            prepared = self.get_api_prepared_request()
            data = prepared.body
        data = data.decode("utf-8").replace("\r\n", "\n")

        # Top-level attachment (in form-data) should have RFC 7578 filename (raw Unicode):
        self.assertIn(
            'Content-Disposition: form-data; name="attachment"; filename="besked med vedhæftede filer"', data)
        # Embedded message/rfc822 attachment should retain its RFC 2231 encoded filename:
        self.assertIn("Content-Type: text/plain; name*=utf-8''vedh%C3%A6ftet%20fil.txt", data)
        self.assertIn("Content-Disposition: attachment; filename*=utf-8''vedh%C3%A6ftet%20fil.txt", data)
        # References to RFC 2231 in message text should remain intact:
        self.assertIn("Testing for filename*=utf-8''problems", data)
        self.assertIn("The attached message should have an attachment named 'vedhæftet fil.txt'", data)

    def test_attachment_missing_filename(self):
        """Mailgun silently drops attachments without filenames, so warn the caller"""
        mimeattachment = MIMEBase('application', 'pdf')
        mimeattachment.set_payload(b"PDF\xb4 pretend this is valid pdf data")
        mimeattachment["Content-Disposition"] = 'attachment'
        self.message.attach(mimeattachment)

        with self.assertRaisesMessage(AnymailUnsupportedFeature, "attachments without filenames"):
            self.message.send()

    def test_inline_missing_contnet_id(self):
        mimeattachment = MIMEImage(b"imagedata", "x-fakeimage")
        mimeattachment["Content-Disposition"] = 'inline; filename="fakeimage.txt"'
        self.message.attach(mimeattachment)
        with self.assertRaisesMessage(AnymailUnsupportedFeature, "inline attachments without Content-ID"):
            self.message.send()

    def test_embedded_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        cid = attach_inline_image_file(self.message, image_path)
        html_content = '<p>This has an <img src="cid:%s" alt="inline" /> image.</p>' % cid
        self.message.attach_alternative(html_content, "text/html")

        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['html'], html_content)

        files = self.get_api_call_files()
        inlines = [value for (field, value) in files if field == 'inline']
        self.assertEqual(len(inlines), 1)
        self.assertEqual(inlines[0], (cid, image_data, "image/png"))  # filename is cid; type is guessed
        # Make sure neither the html nor the inline image is treated as an attachment:
        attachments = [value for (field, value) in files if field == 'attachment']
        self.assertEqual(len(attachments), 0)

    def test_attached_images(self):
        image_filename = SAMPLE_IMAGE_FILENAME
        image_path = sample_image_path(image_filename)
        image_data = sample_image_content(image_filename)

        self.message.attach_file(image_path)  # option 1: attach as a file

        image = MIMEImage(image_data)  # option 2: construct the MIMEImage and attach it directly
        image.set_param("filename", "custom-filename", "Content-Disposition")  # Mailgun requires filenames
        self.message.attach(image)

        self.message.send()
        files = self.get_api_call_files()
        attachments = [value for (field, value) in files if field == 'attachment']
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0], (image_filename, image_data, 'image/png'))
        self.assertEqual(attachments[1], ("custom-filename", image_data, 'image/png'))
        # Make sure the image attachments are not treated as inline:
        inlines = [value for (field, value) in files if field == 'inline']
        self.assertEqual(len(inlines), 0)

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

    def test_amp_html_alternative(self):
        # Mailgun *does* support text/x-amp-html alongside text/html
        self.message.attach_alternative("<p>HTML</p>", "text/html")
        self.message.attach_alternative("<p>And AMP HTML</p>", "text/x-amp-html")
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data["html"], "<p>HTML</p>")
        self.assertEqual(data["amp-html"], "<p>And AMP HTML</p>")

    def test_alternatives_fail_silently(self):
        # Make sure fail_silently is respected
        self.message.attach_alternative("{'not': 'allowed'}", "application/json")
        sent = self.message.send(fail_silently=True)
        self.assert_esp_not_called("API should not be called when send fails silently")
        self.assertEqual(sent, 0)

    def test_suppress_empty_address_lists(self):
        """Empty to, cc, bcc, and reply_to shouldn't generate empty headers"""
        self.message.send()
        data = self.get_api_call_data()
        self.assertNotIn('cc', data)
        self.assertNotIn('bcc', data)
        self.assertNotIn('h:Reply-To', data)

        # Test empty `to` -- but send requires at least one recipient somewhere (like cc)
        self.message.to = []
        self.message.cc = ['cc@example.com']
        self.message.send()
        data = self.get_api_call_data()
        self.assertNotIn('to', data)

    def test_multiple_from_emails(self):
        """Mailgun supports multiple addresses in from_email"""
        self.message.from_email = 'first@example.com, "From, also" <second@example.com>'
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['from'], ['first@example.com',
                                        '"From, also" <second@example.com>'])

        # Make sure the far-more-likely scenario of a single from_email
        # with an unquoted display-name issues a reasonable error:
        self.message.from_email = 'Unquoted, display-name <from@example.com>'
        with self.assertRaises(AnymailInvalidAddress):
            self.message.send()

    def test_api_failure(self):
        self.set_mock_response(status_code=400)
        with self.assertRaisesMessage(AnymailAPIError, "Mailgun API response 400"):
            mail.send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'])

        # Make sure fail_silently is respected
        self.set_mock_response(status_code=400)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'], fail_silently=True)
        self.assertEqual(sent, 0)

    def test_api_error_includes_details(self):
        """AnymailAPIError should include ESP's error message"""
        # JSON error response:
        error_response = b"""{"message": "Helpful explanation from your ESP"}"""
        self.set_mock_response(status_code=400, raw=error_response)
        with self.assertRaisesMessage(AnymailAPIError, "Helpful explanation from your ESP"):
            self.message.send()

        # Non-JSON error response:
        self.set_mock_response(status_code=500, raw=b"Invalid API key")
        with self.assertRaisesMessage(AnymailAPIError, "Invalid API key"):
            self.message.send()

        # No content in the error response:
        self.set_mock_response(status_code=502, raw=None)
        with self.assertRaises(AnymailAPIError):
            self.message.send()

    def test_requests_exception(self):
        """Exception during API call should be AnymailAPIError"""
        # (The post itself raises an error -- different from returning a failure response)
        from requests.exceptions import SSLError  # a low-level requests exception
        self.mock_request.side_effect = SSLError("Something bad")
        with self.assertRaisesMessage(AnymailRequestsAPIError, "Something bad") as cm:
            self.message.send()
        self.assertIsInstance(cm.exception, SSLError)  # also retains specific requests exception class

        # Make sure fail_silently is respected
        self.mock_request.side_effect = SSLError("Something bad")
        sent = mail.send_mail('Subject', 'Body', 'from@example.com', ['to@example.com'], fail_silently=True)
        self.assertEqual(sent, 0)


@tag('mailgun')
class MailgunBackendAnymailFeatureTests(MailgunBackendMockAPITestCase):
    """Test backend support for Anymail added features"""

    def test_metadata(self):
        # Each metadata value is just a string; you can serialize your own JSON if you'd like.
        # (The Mailgun docs are a little confusing on this point.)
        self.message.metadata = {'user_id': "12345", 'items': '["mail","gun"]'}
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['v:user_id'], '12345')
        self.assertEqual(data['v:items'], '["mail","gun"]')
        self.assertNotIn('recipient-variables', data)  # shouldn't be needed for non-batch

    def test_send_at(self):
        utc_plus_6 = get_fixed_timezone(6 * 60)
        utc_minus_8 = get_fixed_timezone(-8 * 60)

        with override_current_timezone(utc_plus_6):
            # Timezone-aware datetime converted to UTC:
            self.message.send_at = datetime(2016, 3, 4, 5, 6, 7, tzinfo=utc_minus_8)
            self.message.send()
            data = self.get_api_call_data()
            self.assertEqual(data['o:deliverytime'], "Fri, 04 Mar 2016 13:06:07 GMT")  # 05:06 UTC-8 == 13:06 UTC

            # Timezone-naive datetime assumed to be Django current_timezone
            self.message.send_at = datetime(2022, 10, 11, 12, 13, 14, 567)
            self.message.send()
            data = self.get_api_call_data()
            self.assertEqual(data['o:deliverytime'], "Tue, 11 Oct 2022 06:13:14 GMT")  # 12:13 UTC+6 == 06:13 UTC

            # Date-only treated as midnight in current timezone
            self.message.send_at = date(2022, 10, 22)
            self.message.send()
            data = self.get_api_call_data()
            self.assertEqual(data['o:deliverytime'], "Fri, 21 Oct 2022 18:00:00 GMT")  # 00:00 UTC+6 == 18:00-1d UTC

            # POSIX timestamp
            self.message.send_at = 1651820889  # 2022-05-06 07:08:09 UTC
            self.message.send()
            data = self.get_api_call_data()
            self.assertEqual(data['o:deliverytime'], "Fri, 06 May 2022 07:08:09 GMT")

            # String passed unchanged (this is *not* portable between ESPs)
            self.message.send_at = "Thu, 13 Oct 2022 18:02:00 GMT"
            self.message.send()
            data = self.get_api_call_data()
            self.assertEqual(data['o:deliverytime'], "Thu, 13 Oct 2022 18:02:00 GMT")

    def test_tags(self):
        self.message.tags = ["receipt", "repeat-user"]
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['o:tag'], ["receipt", "repeat-user"])

    def test_tracking(self):
        # Test one way...
        self.message.track_opens = True
        self.message.track_clicks = False
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['o:tracking-opens'], 'yes')
        self.assertEqual(data['o:tracking-clicks'], 'no')

        # ...and the opposite way
        self.message.track_opens = False
        self.message.track_clicks = True
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['o:tracking-opens'], 'no')
        self.assertEqual(data['o:tracking-clicks'], 'yes')

    def test_template_id(self):
        self.message.template_id = "welcome_template"
        self.message.send()
        data = self.get_api_call_data()
        self.assertEqual(data['template'], "welcome_template")

    def test_merge_data(self):
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.body = "Hi %recipient.name%. Welcome to %recipient.group% at %recipient.site%."
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},  # and leave group undefined
        }
        self.message.merge_global_data = {
            'group': "Users",  # default
            'site': "ExampleCo",
        }
        self.message.send()
        data = self.get_api_call_data()
        self.assertJSONEqual(data['recipient-variables'], {
            'alice@example.com': {'name': "Alice", 'group': "Developers", 'site': "ExampleCo"},
            'bob@example.com': {'name': "Bob", 'group': "Users", 'site': "ExampleCo"},
        })
        # Make sure we didn't modify original dicts on message:
        self.assertEqual(self.message.merge_data, {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},
        })
        self.assertEqual(self.message.merge_global_data, {'group': "Users", 'site': "ExampleCo"})

    def test_only_merge_global_data(self):
        # Make sure merge_global_data distributed to recipient-variables
        # even when merge_data not set
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.merge_global_data = {'test': "value"}
        self.message.send()
        data = self.get_api_call_data()
        self.assertJSONEqual(data['recipient-variables'], {
            'alice@example.com': {'test': "value"},
            'bob@example.com': {'test': "value"},
        })

    def test_merge_data_with_template(self):
        # Mailgun *stored* (handlebars) templates get their variable substitutions
        # from Mailgun's custom-data (not recipient-variables). To support batch sends
        # with stored templates, Anymail sets up custom-data to pull values from
        # recipient-variables. (Note this same Mailgun custom-data is also used for
        # webhook metadata tracking.)
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.template_id = 'welcome_template'
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},  # and leave group undefined
        }
        self.message.merge_global_data = {
            'group': "Users",  # default
            'site': "ExampleCo",
        }
        self.message.send()
        data = self.get_api_call_data()
        # custom-data variables for merge_data refer to recipient-variables:
        self.assertEqual(data['v:name'], '%recipient.name%')
        self.assertEqual(data['v:group'], '%recipient.group%')
        self.assertEqual(data['v:site'], '%recipient.site%')
        # recipient-variables populates them:
        self.assertJSONEqual(data['recipient-variables'], {
            'alice@example.com': {'name': "Alice", 'group': "Developers", 'site': "ExampleCo"},
            'bob@example.com': {'name': "Bob", 'group': "Users", 'site': "ExampleCo"},
        })

    def test_merge_metadata(self):
        # Per-recipient custom-data uses the same recipient-variables mechanism
        # as above, but prepends 'v:' to the recipient-data keys for metadata to
        # keep them separate.
        # (For on-the-fly templates -- not stored handlebars templates.)
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.merge_metadata = {
            'alice@example.com': {'order_id': 123, 'tier': 'premium'},
            'bob@example.com': {'order_id': 678},
        }
        self.message.metadata = {'tier': 'basic', 'notification_batch': 'zx912'}
        self.message.send()

        data = self.get_api_call_data()
        # custom-data variables for merge_metadata refer to recipient-variables:
        self.assertEqual(data['v:order_id'], '%recipient.v:order_id%')
        self.assertEqual(data['v:tier'], '%recipient.v:tier%')
        self.assertEqual(data['v:notification_batch'], 'zx912')  # metadata constant doesn't need var
        # recipient-variables populates them:
        self.assertJSONEqual(data['recipient-variables'], {
            'alice@example.com': {'v:order_id': 123, 'v:tier': 'premium'},
            'bob@example.com': {'v:order_id': 678, 'v:tier': 'basic'},  # tier merged from metadata default
        })

    def test_merge_data_with_merge_metadata(self):
        # merge_data and merge_metadata both use recipient-variables
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.body = "Hi %recipient.name%. Welcome to %recipient.group% at %recipient.site%."
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},  # and leave group undefined
        }
        self.message.merge_metadata = {
            'alice@example.com': {'order_id': 123, 'tier': 'premium'},
            'bob@example.com': {'order_id': 678},  # and leave tier undefined
        }
        self.message.send()

        data = self.get_api_call_data()
        self.assertJSONEqual(data['recipient-variables'], {
            'alice@example.com': {'name': "Alice", 'group': "Developers",
                                  'v:order_id': 123, 'v:tier': 'premium'},
            'bob@example.com': {'name': "Bob", 'group': '',  # undefined merge_data --> empty string
                                'v:order_id': 678, 'v:tier': ''},  # undefined metadata --> empty string
        })

    def test_merge_data_with_merge_metadata_and_template(self):
        # This case gets tricky, because when a stored template is used, the per-recipient
        # merge_metadata and merge_data both end up in the same Mailgun custom-data keys.
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.template_id = 'order_notification'
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},  # and leave group undefined
        }
        self.message.merge_metadata = {
            'alice@example.com': {'order_id': 123, 'tier': 'premium'},
            'bob@example.com': {'order_id': 678},  # and leave tier undefined
        }
        self.message.send()

        data = self.get_api_call_data()
        # custom-data covers both merge_data and merge_metadata:
        self.assertEqual(data['v:name'], '%recipient.name%')  # from merge_data
        self.assertEqual(data['v:group'], '%recipient.group%')  # from merge_data
        self.assertEqual(data['v:order_id'], '%recipient.v:order_id%')  # from merge_metadata
        self.assertEqual(data['v:tier'], '%recipient.v:tier%')  # from merge_metadata
        self.assertJSONEqual(data['recipient-variables'], {
            'alice@example.com': {'name': "Alice", 'group': "Developers",
                                  'v:order_id': 123, 'v:tier': 'premium'},
            'bob@example.com': {'name': "Bob", 'group': '',  # undefined merge_data --> empty string
                                'v:order_id': 678, 'v:tier': ''},  # undefined metadata --> empty string
        })

    def test_conflicting_merge_data_with_merge_metadata_and_template(self):
        # When a stored template is used, the same Mailgun custom-data must hold both
        # per-recipient merge_data and metadata, so there's potential for conflict.
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.template_id = 'order_notification'
        self.message.merge_data = {
            'alice@example.com': {'name': "Alice", 'group': "Developers"},
            'bob@example.com': {'name': "Bob"},
        }
        self.message.metadata = {'group': "Order processing subsystem"}
        with self.assertRaisesMessage(
            AnymailUnsupportedFeature,
            "conflicting merge_data and metadata keys ('group') when using template_id"
        ):
            self.message.send()

    def test_force_batch(self):
        # Mailgun uses presence of recipient-variables to indicate batch send
        self.message.to = ['alice@example.com', 'Bob <bob@example.com>']
        self.message.merge_data = {}
        self.message.send()
        data = self.get_api_call_data()
        self.assertJSONEqual(data['recipient-variables'], {})

    def test_sender_domain(self):
        """Mailgun send domain can come from from_email, envelope_sender, or esp_extra"""
        # You could also use MAILGUN_SENDER_DOMAIN in your ANYMAIL settings, as in the next test.
        # (The mailgun_integration_tests also do that.)
        self.message.from_email = "Test From <from@from-email.example.com>"
        self.message.send()
        self.assert_esp_called('/from-email.example.com/messages')  # API url includes the sender-domain

        self.message.from_email = "Test From <from@from-email.example.com>"
        self.message.envelope_sender = "anything@bounces.example.com"  # only the domain part is used
        self.message.send()
        self.assert_esp_called('/bounces.example.com/messages')  # overrides from_email

        self.message.from_email = "Test From <from@from-email.example.com>"
        self.message.esp_extra = {'sender_domain': 'esp-extra.example.com'}
        self.message.send()
        self.assert_esp_called('/esp-extra.example.com/messages')  # overrides from_email

    @override_settings(ANYMAIL_MAILGUN_SENDER_DOMAIN='mg.example.com')
    def test_sender_domain_setting(self):
        self.message.send()
        self.assert_esp_called('/mg.example.com/messages')  # setting overrides from_email

    def test_invalid_sender_domain(self):
        # Make sure we won't construct an invalid API endpoint like
        # `https://api.mailgun.net/v3/example.com/INVALID/messages`
        # (which returns a cryptic 200-OK "Mailgun Magnificent API" response).
        self.message.from_email = "<from@example.com/invalid>"
        with self.assertRaisesMessage(AnymailError,
                                      "Invalid '/' in sender domain 'example.com/invalid'"):
            self.message.send()

    @override_settings(ANYMAIL_MAILGUN_SENDER_DOMAIN='example.com%2Finvalid')
    def test_invalid_sender_domain_setting(self):
        # See previous test. Also, note that Mailgun unquotes % encoding *before*
        # extracting the sender domain (so %2f is just as bad as '/')
        with self.assertRaisesMessage(AnymailError,
                                      "Invalid '/' in sender domain 'example.com%2Finvalid'"):
            self.message.send()

    @override_settings(ANYMAIL_MAILGUN_SENDER_DOMAIN='example.com # oops')
    def test_encode_sender_domain(self):
        # See previous tests. For anything other than slashes, we let Mailgun detect
        # the problem (but must properly encode the domain in the API URL)
        self.message.send()
        self.assert_esp_called('/example.com%20%23%20oops/messages')

    def test_unknown_sender_domain(self):
        self.set_mock_response(raw=b"""{
            "message": "Domain not found: example.com"
        }""", status_code=404)
        with self.assertRaisesMessage(
            AnymailAPIError,
            "Unknown sender domain 'example.com'.\n"
            "Check the domain is verified with Mailgun, and that the ANYMAIL MAILGUN_API_URL"
            " setting 'https://api.mailgun.net/v3/' is the correct region."
        ):
            self.message.send()

    @override_settings(
        # This is *not* a valid MAILGUN_API_URL setting (it should end at "...v3/"):
        ANYMAIL_MAILGUN_API_URL='https://api.mailgun.net/v3/example.com/messages')
    def test_magnificent_api(self):
        # (Wouldn't a truly "magnificent API" just provide a helpful error message?)
        self.set_mock_response(raw=b"Mailgun Magnificent API", status_code=200)
        with self.assertRaisesMessage(
            AnymailAPIError,
            "Invalid Mailgun API endpoint 'https://api.mailgun.net/v3/example.com/messages/example.com/messages'.\n"
            "Check your ANYMAIL MAILGUN_SENDER_DOMAIN and MAILGUN_API_URL settings."
        ):
            self.message.send()

    def test_default_omits_options(self):
        """Make sure by default we don't send any ESP-specific options.

        Options not specified by the caller should be omitted entirely from
        the API call (*not* sent as False or empty). This ensures
        that your ESP account settings apply by default.
        """
        self.message.send()
        self.assert_esp_called('/example.com/messages')
        data = self.get_api_call_data()
        mailgun_fields = {key: value for key, value in data.items()
                          if key.startswith('o:') or key.startswith('v:')}
        self.assertEqual(mailgun_fields, {})

    # noinspection PyUnresolvedReferences
    def test_send_attaches_anymail_status(self):
        """ The anymail_status should be attached to the message when it is sent """
        response_content = b"""{
            "id": "<12345.67890@example.com>",
            "message": "Queued. Thank you."
        }"""
        self.set_mock_response(raw=response_content)
        msg = mail.EmailMessage('Subject', 'Message', 'from@example.com', ['to1@example.com'],)
        sent = msg.send()
        self.assertEqual(sent, 1)
        self.assertEqual(msg.anymail_status.status, {'queued'})
        self.assertEqual(msg.anymail_status.message_id, '<12345.67890@example.com>')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].status, 'queued')
        self.assertEqual(msg.anymail_status.recipients['to1@example.com'].message_id, '<12345.67890@example.com>')
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

    # test_json_serialization_errors: Mailgun payload isn't JSON, so we don't test this.
    # (Anything that requests can serialize as a form field will work with Mailgun)


@tag('mailgun')
class MailgunBackendRecipientsRefusedTests(MailgunBackendMockAPITestCase):
    """Should raise AnymailRecipientsRefused when *all* recipients are rejected or invalid"""

    # Mailgun doesn't check email bounce or complaint lists at time of send --
    # it always just queues the message. You'll need to listen for the "rejected"
    # and "failed" events to detect refused recipients.

    # The one exception is a completely invalid email, which will return a 400 response
    # and show up as an AnymailAPIError at send time.
    INVALID_TO_RESPONSE = b"""{
        "message": "'to' parameter is not a valid address. please check documentation"
    }"""

    # NOTE: As of Anymail 0.10, Anymail catches actually-invalid recipient emails
    # before attempting to pass them along to the ESP, so the tests below use technically
    # valid emails that would actually be accepted by Mailgun. (We're just making sure
    # the backend would correctly handle the 400 response if something slipped through.)

    def test_invalid_email(self):
        self.set_mock_response(status_code=400, raw=self.INVALID_TO_RESPONSE)
        msg = mail.EmailMessage('Subject', 'Body', 'from@example.com', to=['not-really@invalid'])
        with self.assertRaises(AnymailAPIError):
            msg.send()

    def test_fail_silently(self):
        self.set_mock_response(status_code=400, raw=self.INVALID_TO_RESPONSE)
        sent = mail.send_mail('Subject', 'Body', 'from@example.com', ['not-really@invalid'],
                              fail_silently=True)
        self.assertEqual(sent, 0)


@tag('mailgun')
class MailgunBackendSessionSharingTestCase(SessionSharingTestCases, MailgunBackendMockAPITestCase):
    """Requests session sharing tests"""
    pass  # tests are defined in SessionSharingTestCases


@tag('mailgun')
@override_settings(EMAIL_BACKEND="anymail.backends.mailgun.EmailBackend")
class MailgunBackendImproperlyConfiguredTests(AnymailTestMixin, SimpleTestCase):
    """Test ESP backend without required settings in place"""

    def test_missing_api_key(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            mail.send_mail('Subject', 'Message', 'from@example.com', ['to@example.com'])
        errmsg = str(cm.exception)
        # Make sure the error mentions MAILGUN_API_KEY and ANYMAIL_MAILGUN_API_KEY
        self.assertRegex(errmsg, r'\bMAILGUN_API_KEY\b')
        self.assertRegex(errmsg, r'\bANYMAIL_MAILGUN_API_KEY\b')
