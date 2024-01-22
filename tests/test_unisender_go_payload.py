from __future__ import annotations

from django.test import SimpleTestCase, override_settings, tag

from anymail.backends.unisender_go import EmailBackend, UnisenderGoPayload
from anymail.message import AnymailMessageMixin

TEMPLATE_ID = "template_id"
FROM_EMAIL = "sender@test.test"
FROM_NAME = "test name"
TO_EMAIL = "receiver@test.test"
TO_NAME = "receiver"
OTHER_TO_EMAIL = "receiver1@test.test"
OTHER_TO_NAME = "receiver1"
SUBJECT = "subject"
GLOBAL_DATA = {"arg": "arg"}
SUBSTITUTION_ONE = {"arg1": "arg1"}
SUBSTITUTION_TWO = {"arg2": "arg2"}


@tag("unisender_go")
@override_settings(ANYMAIL_UNISENDER_GO_API_KEY=None, ANYMAIL_UNISENDER_GO_API_URL="")
class TestUnisenderGoPayload(SimpleTestCase):
    @override_settings(ANYMAIL_UNISENDER_GO_SKIP_UNSUBSCRIBE=False)
    def test_unisender_go_payload__full(self):
        substitutions = {TO_EMAIL: SUBSTITUTION_ONE, OTHER_TO_EMAIL: SUBSTITUTION_TWO}
        email = AnymailMessageMixin(
            template_id=TEMPLATE_ID,
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[f"{TO_NAME} <{TO_EMAIL}>", f"{OTHER_TO_NAME} <{OTHER_TO_EMAIL}>"],
            merge_data=substitutions,
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [
                {
                    "email": TO_EMAIL,
                    "substitutions": {**SUBSTITUTION_ONE, "to_name": TO_NAME},
                },
                {
                    "email": OTHER_TO_EMAIL,
                    "substitutions": {**SUBSTITUTION_TWO, "to_name": OTHER_TO_NAME},
                },
            ],
            "subject": SUBJECT,
            "template_id": TEMPLATE_ID,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(ANYMAIL_UNISENDER_GO_SKIP_UNSUBSCRIBE=False)
    def test_unisender_go_payload__parse_from__with_name(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL_UNISENDER_GO_SKIP_UNSUBSCRIBE=False,
    )
    def test_unisender_go_payload__parse_from__without_name(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=FROM_EMAIL,
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": "",
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL_UNISENDER_GO_SKIP_UNSUBSCRIBE=True,
    )
    def test_unisender_go_payload__parse_from__with_unsub__in_settings(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
            "skip_unsubscribe": 1,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(ANYMAIL_UNISENDER_GO_SKIP_UNSUBSCRIBE=False)
    def test_unisender_go_payload__parse_from__with_unsub__in_args(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
            esp_extra={"skip_unsubscribe": 1},
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
            "skip_unsubscribe": 1,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL_UNISENDER_GO_GLOBAL_LANGUAGE="en",
    )
    def test_unisender_go_payload__parse_from__global_language__in_settings(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
            "global_language": "en",
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(ANYMAIL_UNISENDER_GO_GLOBAL_LANGUAGE="fr")
    def test_unisender_go_payload__parse_from__global_language__in_args(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
            esp_extra={"global_language": "en"},
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
            "global_language": "en",
        }

        self.assertEqual(payload.data, expected_payload)

    def test_unisender_go_payload__parse_from__bypass_esp_extra(self):
        email = AnymailMessageMixin(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
            esp_extra={
                "bypass_global": 1,
                "bypass_unavailable": 1,
                "bypass_unsubscribed": 1,
                "bypass_complained": 1,
            },
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(message=email, backend=backend, defaults={})
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {},
            "recipients": [{"email": TO_EMAIL, "substitutions": {"to_name": ""}}],
            "subject": SUBJECT,
            "bypass_global": 1,
            "bypass_unavailable": 1,
            "bypass_unsubscribed": 1,
            "bypass_complained": 1,
        }

        self.assertEqual(payload.data, expected_payload)
