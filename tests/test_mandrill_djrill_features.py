from datetime import date

from django.core import mail
from django.test import override_settings, tag

from anymail.exceptions import AnymailSerializationError

from .test_mandrill_backend import MandrillBackendMockAPITestCase


@tag("mandrill")
class MandrillBackendDjrillFeatureTests(MandrillBackendMockAPITestCase):
    """Test backend support for deprecated features leftover from Djrill"""

    # These features should now be accessed through esp_extra

    def test_async(self):
        # async becomes a keyword in Python 3.7. If you have code like this:
        #   self.message.async = True
        # it should be changed to:
        #   self.message.esp_extra = {"async": True}
        # (The setattr below keeps these tests compatible,
        # but isn't recommended for your code.)
        setattr(self.message, "async", True)  # don't do this; use esp_extra instead
        with self.assertWarnsRegex(DeprecationWarning, "async"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["async"], True)

    def test_auto_html(self):
        self.message.auto_html = True
        with self.assertWarnsRegex(DeprecationWarning, "auto_html"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["auto_html"], True)

    def test_auto_text(self):
        self.message.auto_text = True
        with self.assertWarnsRegex(DeprecationWarning, "auto_text"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["auto_text"], True)

    def test_google_analytics_campaign(self):
        self.message.google_analytics_campaign = "Email Receipts"
        with self.assertWarnsRegex(DeprecationWarning, "google_analytics_campaign"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["google_analytics_campaign"], "Email Receipts")

    def test_google_analytics_domains(self):
        self.message.google_analytics_domains = ["example.com"]
        with self.assertWarnsRegex(DeprecationWarning, "google_analytics_domains"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["google_analytics_domains"], ["example.com"])

    def test_important(self):
        self.message.important = True
        with self.assertWarnsRegex(DeprecationWarning, "important"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["important"], True)

    def test_inline_css(self):
        self.message.inline_css = True
        with self.assertWarnsRegex(DeprecationWarning, "inline_css"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["inline_css"], True)

    def test_ip_pool(self):
        self.message.ip_pool = "Bulk Pool"
        with self.assertWarnsRegex(DeprecationWarning, "ip_pool"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["ip_pool"], "Bulk Pool")

    def test_merge_language(self):
        self.message.merge_language = "mailchimp"
        with self.assertWarnsRegex(DeprecationWarning, "merge_language"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["merge_language"], "mailchimp")

    def test_preserve_recipients(self):
        self.message.preserve_recipients = True
        with self.assertWarnsRegex(DeprecationWarning, "preserve_recipients"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["preserve_recipients"], True)

    def test_recipient_metadata(self):
        self.message.recipient_metadata = {
            # Anymail expands simple python dicts into the more-verbose
            # rcpt/values structures the Mandrill API uses
            "customer@example.com": {"cust_id": "67890", "order_id": "54321"},
            "guest@example.com": {"cust_id": "94107", "order_id": "43215"},
        }
        with self.assertWarnsRegex(DeprecationWarning, "recipient_metadata"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertCountEqual(
            data["message"]["recipient_metadata"],
            [
                {
                    "rcpt": "customer@example.com",
                    "values": {"cust_id": "67890", "order_id": "54321"},
                },
                {
                    "rcpt": "guest@example.com",
                    "values": {"cust_id": "94107", "order_id": "43215"},
                },
            ],
        )

    def test_return_path_domain(self):
        self.message.return_path_domain = "support.example.com"
        with self.assertWarnsRegex(DeprecationWarning, "return_path_domain"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["return_path_domain"], "support.example.com")

    def test_signing_domain(self):
        self.message.signing_domain = "example.com"
        with self.assertWarnsRegex(DeprecationWarning, "signing_domain"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["signing_domain"], "example.com")

    def test_subaccount(self):
        self.message.subaccount = "marketing-dept"
        with self.assertWarnsRegex(DeprecationWarning, "subaccount"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["subaccount"], "marketing-dept")

    def test_template_content(self):
        self.message.template_content = {
            "HEADLINE": "<h1>Specials Just For *|FNAME|*</h1>",
            "OFFER_BLOCK": "<p><em>Half off</em> all fruit</p>",
        }
        with self.assertWarnsRegex(DeprecationWarning, "template_content"):
            self.message.send()
        data = self.get_api_call_json()
        # Anymail expands simple python dicts into the more-verbose name/content
        # structures the Mandrill API uses
        self.assertCountEqual(
            data["template_content"],
            [
                {"name": "HEADLINE", "content": "<h1>Specials Just For *|FNAME|*</h1>"},
                {
                    "name": "OFFER_BLOCK",
                    "content": "<p><em>Half off</em> all fruit</p>",
                },
            ],
        )

    def test_tracking_domain(self):
        self.message.tracking_domain = "click.example.com"
        with self.assertWarnsRegex(DeprecationWarning, "tracking_domain"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["tracking_domain"], "click.example.com")

    def test_url_strip_qs(self):
        self.message.url_strip_qs = True
        with self.assertWarnsRegex(DeprecationWarning, "url_strip_qs"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["url_strip_qs"], True)

    def test_use_template_from(self):
        self.message.template_id = "PERSONALIZED_SPECIALS"  # forces send-template api
        self.message.use_template_from = True
        with self.assertWarnsRegex(DeprecationWarning, "use_template_from"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("from_email", data["message"])
        self.assertNotIn("from_name", data["message"])

    def test_use_template_subject(self):
        self.message.template_id = "PERSONALIZED_SPECIALS"  # force send-template API
        self.message.use_template_subject = True
        with self.assertWarnsRegex(DeprecationWarning, "use_template_subject"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertNotIn("subject", data["message"])

    def test_view_content_link(self):
        self.message.view_content_link = True
        with self.assertWarnsRegex(DeprecationWarning, "view_content_link"):
            self.message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["view_content_link"], True)

    def test_default_omits_options(self):
        """Make sure by default we don't send any Mandrill-specific options.

        Options not specified by the caller should be omitted entirely from
        the Mandrill API call (*not* sent as False or empty). This ensures
        that your Mandrill account settings apply by default.
        """
        self.message.send()
        self.assert_esp_called("/messages/send.json")
        data = self.get_api_call_json()
        self.assertFalse("auto_html" in data["message"])
        self.assertFalse("auto_text" in data["message"])
        self.assertFalse("bcc_address" in data["message"])
        self.assertFalse("from_name" in data["message"])
        self.assertFalse("global_merge_vars" in data["message"])
        self.assertFalse("google_analytics_campaign" in data["message"])
        self.assertFalse("google_analytics_domains" in data["message"])
        self.assertFalse("important" in data["message"])
        self.assertFalse("inline_css" in data["message"])
        self.assertFalse("merge_language" in data["message"])
        self.assertFalse("merge_vars" in data["message"])
        self.assertFalse("preserve_recipients" in data["message"])
        self.assertFalse("recipient_metadata" in data["message"])
        self.assertFalse("return_path_domain" in data["message"])
        self.assertFalse("signing_domain" in data["message"])
        self.assertFalse("subaccount" in data["message"])
        self.assertFalse("tracking_domain" in data["message"])
        self.assertFalse("url_strip_qs" in data["message"])
        self.assertFalse("view_content_link" in data["message"])
        # Options at top level of api params (not in message dict):
        self.assertFalse("async" in data)
        self.assertFalse("ip_pool" in data)

    def test_dates_not_serialized(self):
        """
        Old versions of predecessor package Djrill accidentally serialized dates to ISO
        """
        self.message.metadata = {"SHIP_DATE": date(2015, 12, 2)}
        with self.assertRaises(AnymailSerializationError):
            self.message.send()

    @override_settings(ANYMAIL_MANDRILL_SEND_DEFAULTS={"subaccount": "test_subaccount"})
    def test_subaccount_setting(self):
        """Global, non-esp_extra version of subaccount default"""
        with self.assertWarnsRegex(DeprecationWarning, "subaccount"):
            mail.send_mail("Subject", "Body", "from@example.com", ["to@example.com"])
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["subaccount"], "test_subaccount")

    @override_settings(
        ANYMAIL_MANDRILL_SEND_DEFAULTS={"subaccount": "global_setting_subaccount"}
    )
    def test_subaccount_message_overrides_setting(self):
        """Global, non-esp_extra version of subaccount default"""
        message = mail.EmailMessage(
            "Subject", "Body", "from@example.com", ["to@example.com"]
        )
        # subaccount should override global setting:
        message.subaccount = "individual_message_subaccount"
        with self.assertWarnsRegex(DeprecationWarning, "subaccount"):
            message.send()
        data = self.get_api_call_json()
        self.assertEqual(data["message"]["subaccount"], "individual_message_subaccount")
