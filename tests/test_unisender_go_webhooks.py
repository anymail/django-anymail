from __future__ import annotations

import datetime
import hashlib
import uuid

from anymail.exceptions import AnymailWebhookValidationFailure
from anymail.signals import EventType, RejectReason
from django.test import RequestFactory
from django.test import SimpleTestCase, override_settings
from django.utils.timezone import utc

from anymail.webhooks.unisender_go import UnisenderGoTrackingWebhookView

EVENT_TYPE = EventType.SENT
EVENT_TIME = '2015-11-30 15:09:42'
EVENT_DATETIME = datetime.datetime(2015, 11, 30, 15, 9, 42, tzinfo=utc)
MESSAGE_ID = '1a3Q2V-0000OZ-S0'
DELIVERY_RESPONSE = '550 Spam rejected'
UNISENDER_TEST_EMAIL = 'recipient.email@example.com'
TEST_API_KEY = 'api_key'
TEST_EMAIL_ID = str(uuid.uuid4())
UNISENDER_TEST_DEFAULT_EXAMPLE = {
    'auth': TEST_API_KEY,
    'events_by_user': [
        {
            'user_id': 456,
            'project_id': '6432890213745872',
            'project_name': 'MyProject',
            'events': [
                {
                    'event_name': 'transactional_email_status',
                    'event_data': {
                        'job_id': MESSAGE_ID,
                        'metadata': {'key1': 'val1', 'message_id': TEST_EMAIL_ID},
                        'email': UNISENDER_TEST_EMAIL,
                        'status': EVENT_TYPE,
                        'event_time': EVENT_TIME,
                        'url': 'http://some.url.com',
                        'delivery_info': {
                            'delivery_status': 'err_delivery_failed',
                            'destination_response': DELIVERY_RESPONSE,
                            'user_agent': (
                                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                                '(KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36'
                            ),
                            'ip': '111.111.111.111',
                        },
                    },
                },
                {
                    'event_name': 'transactional_spam_block',
                    'event_data': {
                        'block_time': 'YYYY-MM-DD HH:MM:SS',
                        'block_type': 'one_smtp',
                        'domain': 'domain_name',
                        'SMTP_blocks_count': 8,
                        'domain_status': 'blocked',
                    },
                },
            ],
        }
    ],
}
EXAMPLE_WITHOUT_DELIVERY_INFO = {
    'auth': '',
    'events_by_user': [
        {
            'events': [
                {
                    'event_name': 'transactional_email_status',
                    'event_data': {
                        'job_id': MESSAGE_ID,
                        'metadata': {},
                        'email': UNISENDER_TEST_EMAIL,
                        'status': EVENT_TYPE,
                        'event_time': EVENT_TIME,
                    },
                }
            ]
        }
    ],
}
REQUEST_JSON = '{"auth":"api_key","key":"value"}'
REQUEST_JSON_MD5 = '8c64386327f53722434f44021a7a0d40'  # md5 hash of REQUEST_JSON
REQUEST_DATA_AUTH = {'auth': REQUEST_JSON_MD5, 'key': 'value'}


def _request_json_to_dict_with_hashed_key(request_json: bytes) -> dict[str, str]:
    new_auth = hashlib.md5(request_json).hexdigest()
    return {'auth': new_auth, 'key': 'value'}


class TestUnisenderGoWebhooks(SimpleTestCase):
    def test_sent_event(self):
        request = RequestFactory().post(
            path='/',
            data=UNISENDER_TEST_DEFAULT_EXAMPLE,
            content_type='application/json',
        )
        view = UnisenderGoTrackingWebhookView()

        events = view.parse_events(request)
        event = events[0]

        assert len(events) == 1
        assert event.event_type == EVENT_TYPE
        assert event.timestamp == EVENT_DATETIME
        assert event.event_id is None
        assert event.recipient == UNISENDER_TEST_EMAIL
        assert event.reject_reason == RejectReason.OTHER
        assert event.mta_response == DELIVERY_RESPONSE
        assert event.metadata == {'key1': 'val1', 'message_id': TEST_EMAIL_ID}

    def test_without_delivery_info(self):
        request = RequestFactory().post(
            path='/',
            data=EXAMPLE_WITHOUT_DELIVERY_INFO,
            content_type='application/json',
        )
        view = UnisenderGoTrackingWebhookView()

        events = view.parse_events(request)

        assert len(events) == 1

    @override_settings(ANYMAIL_UNISENDERGO_API_KEY=TEST_API_KEY)
    def test_check_authorization(self):
        request_data = _request_json_to_dict_with_hashed_key(b'{"auth":"api_key","key":"value"}')
        request = RequestFactory().post(
            path='/', data=request_data, content_type='application/json'
        )
        view = UnisenderGoTrackingWebhookView()

        view.validate_request(request)

    @override_settings(ANYMAIL_UNISENDERGO_API_KEY=TEST_API_KEY)
    def test_check_authorization__fail__ordinar_quoters(self):
        request_json = b"{'auth':'api_key','key':'value'}"
        request_data = _request_json_to_dict_with_hashed_key(request_json)
        request = RequestFactory().post(
            path='/', data=request_data, content_type='application/json'
        )
        view = UnisenderGoTrackingWebhookView()

        with self.assertRaises(AnymailWebhookValidationFailure):
            view.validate_request(request)

    @override_settings(ANYMAIL_UNISENDERGO_API_KEY=TEST_API_KEY)
    def test_check_authorization__fail__spaces_after_semicolon(self):
        request_json = b'{"auth": "api_key","key": "value"}'
        request_data = _request_json_to_dict_with_hashed_key(request_json)
        request = RequestFactory().post(
            path='/', data=request_data, content_type='application/json'
        )
        view = UnisenderGoTrackingWebhookView()

        with self.assertRaises(AnymailWebhookValidationFailure):
            view.validate_request(request)

    @override_settings(ANYMAIL_UNISENDERGO_API_KEY=TEST_API_KEY)
    def test_check_authorization__fail__spaces_after_comma(self):
        request_json = b'{"auth":"api_key", "key":"value"}'
        request_data = _request_json_to_dict_with_hashed_key(request_json)
        request = RequestFactory().post(
            path='/', data=request_data, content_type='application/json'
        )
        view = UnisenderGoTrackingWebhookView()

        with self.assertRaises(AnymailWebhookValidationFailure):
            view.validate_request(request)
