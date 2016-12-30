from datetime import datetime
from email.mime.text import MIMEText

import six
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import get_connection, send_mail
from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.utils.functional import Promise
from django.utils.timezone import utc
from django.utils.translation import ugettext_lazy

from anymail.exceptions import AnymailConfigurationError, AnymailUnsupportedFeature
from anymail.message import AnymailMessage

from .utils import AnymailTestMixin


recorded_send_params = []


@override_settings(EMAIL_BACKEND='anymail.backends.test.TestBackend',
                   ANYMAIL_TEST_SAMPLE_SETTING='sample',  # required TestBackend setting
                   ANYMAIL_TEST_RECORDED_SEND_PARAMS=recorded_send_params)
class TestBackendTestCase(SimpleTestCase, AnymailTestMixin):
    """Base TestCase using Anymail's TestBackend"""

    def setUp(self):
        super(TestBackendTestCase, self).setUp()
        del recorded_send_params[:]  # empty the list from previous tests
        # Simple message useful for many tests
        self.message = AnymailMessage('Subject', 'Text Body', 'from@example.com', ['to@example.com'])

    @staticmethod
    def get_send_count():
        """Returns number of times "send api" has been called this test"""
        return len(recorded_send_params)

    @staticmethod
    def get_send_params():
        """Returns the params for the most recent "send api" call"""
        return recorded_send_params[-1]


@override_settings(EMAIL_BACKEND='anymail.backends.test.TestBackend')  # but no ANYMAIL settings overrides
class BackendSettingsTests(SimpleTestCase, AnymailTestMixin):          # (so not TestBackendTestCase)
    """Test settings initializations for Anymail EmailBackends"""

    @override_settings(ANYMAIL={'TEST_SAMPLE_SETTING': 'setting_from_anymail_settings'})
    def test_anymail_setting(self):
        """ESP settings usually come from ANYMAIL settings dict"""
        backend = get_connection()
        self.assertEqual(backend.sample_setting, 'setting_from_anymail_settings')

    @override_settings(TEST_SAMPLE_SETTING='setting_from_bare_settings')
    def test_bare_setting(self):
        """ESP settings are also usually allowed at root of settings file"""
        backend = get_connection()
        self.assertEqual(backend.sample_setting, 'setting_from_bare_settings')

    @override_settings(ANYMAIL={'TEST_SAMPLE_SETTING': 'setting_from_settings'})
    def test_connection_kwargs_overrides_settings(self):
        """Can override settings file in get_connection"""
        backend = get_connection()
        self.assertEqual(backend.sample_setting, 'setting_from_settings')

        backend = get_connection(sample_setting='setting_from_kwargs')
        self.assertEqual(backend.sample_setting, 'setting_from_kwargs')

    def test_missing_setting(self):
        """Settings without defaults must be provided"""
        with self.assertRaises(AnymailConfigurationError) as cm:
            get_connection()
        self.assertIsInstance(cm.exception, ImproperlyConfigured)  # Django consistency
        errmsg = str(cm.exception)
        self.assertRegex(errmsg, r'\bTEST_SAMPLE_SETTING\b')
        self.assertRegex(errmsg, r'\bANYMAIL_TEST_SAMPLE_SETTING\b')

    @override_settings(ANYMAIL={'SENDGRID_USERNAME': 'username_from_settings',
                                'SENDGRID_PASSWORD': 'password_from_settings'})
    def test_username_password_kwargs_overrides(self):
        """Overrides for 'username' and 'password' should work like other overrides"""
        # These are special-cased because of default args in Django core mail functions.
        # (Use the SendGrid backend, which has settings named 'username' and 'password'.)
        backend = get_connection('anymail.backends.sendgrid.SendGridBackend')
        self.assertEqual(backend.username, 'username_from_settings')
        self.assertEqual(backend.password, 'password_from_settings')

        backend = get_connection('anymail.backends.sendgrid.SendGridBackend',
                                 username='username_from_kwargs', password='password_from_kwargs')
        self.assertEqual(backend.username, 'username_from_kwargs')
        self.assertEqual(backend.password, 'password_from_kwargs')


class UnsupportedFeatureTests(TestBackendTestCase):
    """Tests mail features not supported by backend are handled properly"""

    def test_unsupported_feature(self):
        """Unsupported features raise AnymailUnsupportedFeature"""
        # TestBackend doesn't support non-HTML alternative parts
        self.message.attach_alternative(b'FAKE_MP3_DATA', 'audio/mpeg')
        with self.assertRaises(AnymailUnsupportedFeature):
            self.message.send()

    @override_settings(ANYMAIL={
        'IGNORE_UNSUPPORTED_FEATURES': True
    })
    def test_ignore_unsupported_features(self):
        """Setting prevents exception"""
        self.message.attach_alternative(b'FAKE_MP3_DATA', 'audio/mpeg')
        self.message.send()  # should not raise exception


class SendDefaultsTests(TestBackendTestCase):
    """Tests backend support for global SEND_DEFAULTS and <ESP>_SEND_DEFAULTS"""

    @override_settings(ANYMAIL={
        'SEND_DEFAULTS': {
            # This isn't an exhaustive list of Anymail message attrs; just one of each type
            'metadata': {'global': 'globalvalue'},
            'send_at': datetime(2016, 5, 12, 4, 17, 0, tzinfo=utc),
            'tags': ['globaltag'],
            'template_id': 'my-template',
            'track_clicks': True,
            'esp_extra': {'globalextra': 'globalsetting'},
        }
    })
    def test_send_defaults(self):
        """Test that (non-esp-specific) send defaults are applied"""
        self.message.send()
        params = self.get_send_params()
        # All these values came from ANYMAIL_SEND_DEFAULTS:
        self.assertEqual(params['metadata'], {'global': 'globalvalue'})
        self.assertEqual(params['send_at'], datetime(2016, 5, 12, 4, 17, 0, tzinfo=utc))
        self.assertEqual(params['tags'], ['globaltag'])
        self.assertEqual(params['template_id'], 'my-template')
        self.assertEqual(params['track_clicks'], True)
        self.assertEqual(params['globalextra'], 'globalsetting')  # TestBackend merges esp_extra into params

    @override_settings(ANYMAIL={
        'TEST_SEND_DEFAULTS': {  # "TEST" is the name of the TestBackend's ESP
            'metadata': {'global': 'espvalue'},
            'tags': ['esptag'],
            'track_opens': False,
            'esp_extra': {'globalextra': 'espsetting'},
        }
    })
    def test_esp_send_defaults(self):
        """Test that esp-specific send defaults are applied"""
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['metadata'], {'global': 'espvalue'})
        self.assertEqual(params['tags'], ['esptag'])
        self.assertEqual(params['track_opens'], False)
        self.assertEqual(params['globalextra'], 'espsetting')  # TestBackend merges esp_extra into params

    @override_settings(ANYMAIL={
        'SEND_DEFAULTS': {
            'metadata': {'global': 'globalvalue', 'other': 'othervalue'},
            'tags': ['globaltag'],
            'track_clicks': True,
            'track_opens': False,
            'esp_extra': {'globalextra': 'globalsetting'},
        }
    })
    def test_send_defaults_combine_with_message(self):
        """Individual message settings are *merged into* the global send defaults"""
        self.message.metadata = {'message': 'messagevalue', 'other': 'override'}
        self.message.tags = ['messagetag']
        self.message.track_clicks = False
        self.message.esp_extra = {'messageextra': 'messagesetting'}

        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['metadata'], {  # metadata merged
            'global': 'globalvalue',  # global default preserved
            'message': 'messagevalue',  # message setting added
            'other': 'override'})  # message setting overrides global default
        self.assertEqual(params['tags'], ['globaltag', 'messagetag'])  # tags concatenated
        self.assertEqual(params['track_clicks'], False)  # message overrides
        self.assertEqual(params['track_opens'], False)  # (no message setting)
        self.assertEqual(params['globalextra'], 'globalsetting')
        self.assertEqual(params['messageextra'], 'messagesetting')

        # Send another message to make sure original SEND_DEFAULTS unchanged
        send_mail('subject', 'body', 'from@example.com', ['to@example.com'])
        params = self.get_send_params()
        self.assertEqual(params['metadata'], {'global': 'globalvalue', 'other': 'othervalue'})
        self.assertEqual(params['tags'], ['globaltag'])
        self.assertEqual(params['track_clicks'], True)
        self.assertEqual(params['track_opens'], False)
        self.assertEqual(params['globalextra'], 'globalsetting')

    @override_settings(ANYMAIL={
        'SEND_DEFAULTS': {
            # This isn't an exhaustive list of Anymail message attrs; just one of each type
            'metadata': {'global': 'globalvalue'},
            'tags': ['globaltag'],
            'template_id': 'global-template',
            'esp_extra': {'globalextra': 'globalsetting'},
        },
        'TEST_SEND_DEFAULTS': {  # "TEST" is the name of the TestBackend's ESP
            'merge_global_data': {'esp': 'espmerge'},
            'metadata': {'esp': 'espvalue'},
            'tags': ['esptag'],
            'esp_extra': {'espextra': 'espsetting'},
        }
    })
    def test_esp_send_defaults_override_globals(self):
        """ESP-specific send defaults override *individual* global defaults"""
        self.message.send()
        params = self.get_send_params()
        self.assertEqual(params['merge_global_data'], {'esp': 'espmerge'})  # esp-defaults only
        self.assertEqual(params['metadata'], {'esp': 'espvalue'})
        self.assertEqual(params['tags'], ['esptag'])
        self.assertEqual(params['template_id'], 'global-template')  # global-defaults only
        self.assertEqual(params['espextra'], 'espsetting')
        self.assertNotIn('globalextra', params)  # entire esp_extra is overriden by esp-send-defaults


class LazyStringsTest(TestBackendTestCase):
    """
    Tests ugettext_lazy strings forced real before passing to ESP transport.

    Docs notwithstanding, Django lazy strings *don't* work anywhere regular
    strings would. In particular, they aren't instances of unicode/str.
    There are some cases (e.g., urllib.urlencode, requests' _encode_params)
    where this can cause encoding errors or just very wrong results.

    Since Anymail sits on the border between Django app code and non-Django
    ESP code (e.g., requests), it's responsible for converting lazy text
    to actual strings.
    """

    def assertNotLazy(self, s, msg=None):
        self.assertNotIsInstance(s, Promise,
                                 msg=msg or "String %r is lazy" % six.text_type(s))

    def test_lazy_from(self):
        # This sometimes ends up lazy when settings.DEFAULT_FROM_EMAIL is meant to be localized
        self.message.from_email = ugettext_lazy(u'"Global Sales" <sales@example.com>')
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['from'].address)

    def test_lazy_subject(self):
        self.message.subject = ugettext_lazy("subject")
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['subject'])

    def test_lazy_body(self):
        self.message.body = ugettext_lazy("text body")
        self.message.attach_alternative(ugettext_lazy("html body"), "text/html")
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['text_body'])
        self.assertNotLazy(params['html_body'])

    def test_lazy_headers(self):
        self.message.extra_headers['X-Test'] = ugettext_lazy("Test Header")
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['extra_headers']['X-Test'])

    def test_lazy_attachments(self):
        self.message.attach(ugettext_lazy("test.csv"), ugettext_lazy("test,csv,data"), "text/csv")
        self.message.attach(MIMEText(ugettext_lazy("contact info")))
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['attachments'][0].name)
        self.assertNotLazy(params['attachments'][0].content)
        self.assertNotLazy(params['attachments'][1].content)

    def test_lazy_tags(self):
        self.message.tags = [ugettext_lazy("Shipping"), ugettext_lazy("Sales")]
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['tags'][0])
        self.assertNotLazy(params['tags'][1])

    def test_lazy_metadata(self):
        self.message.metadata = {'order_type': ugettext_lazy("Subscription")}
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['metadata']['order_type'])

    def test_lazy_merge_data(self):
        self.message.merge_data = {
            'to@example.com': {'duration': ugettext_lazy("One Month")}}
        self.message.merge_global_data = {'order_type': ugettext_lazy("Subscription")}
        self.message.send()
        params = self.get_send_params()
        self.assertNotLazy(params['merge_data']['to@example.com']['duration'])
        self.assertNotLazy(params['merge_global_data']['order_type'])
