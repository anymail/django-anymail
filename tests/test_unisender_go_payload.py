from __future__ import annotations

from email.headerregistry import Address

from django.test import SimpleTestCase, override_settings, tag
from requests.structures import CaseInsensitiveDict

from anymail.backends.unisender_go import EmailBackend, UnisenderGoPayload
from anymail.message import AnymailMessage

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
    def test_unisender_go_payload__full(self):
        substitutions = {TO_EMAIL: SUBSTITUTION_ONE, OTHER_TO_EMAIL: SUBSTITUTION_TWO}
        email = AnymailMessage(
            template_id=TEMPLATE_ID,
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=str(Address(display_name=FROM_NAME, addr_spec=FROM_EMAIL)),
            to=[
                str(Address(display_name=TO_NAME, addr_spec=TO_EMAIL)),
                str(Address(display_name=OTHER_TO_NAME, addr_spec=OTHER_TO_EMAIL)),
            ],
            merge_data=substitutions,
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {
                "to": ", ".join(email.to),
            },
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

    def test_unisender_go_payload__cc_bcc(self):
        cc_to_email = "receiver_cc@test.test"
        bcc_to_email = "receiver_bcc@test.test"
        email = AnymailMessage(
            template_id=TEMPLATE_ID,
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[
                str(Address(display_name=TO_NAME, addr_spec=TO_EMAIL)),
                str(Address(display_name=OTHER_TO_NAME, addr_spec=OTHER_TO_EMAIL)),
            ],
            cc=[cc_to_email],
            bcc=[bcc_to_email],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_headers = {
            "To": f"{TO_NAME} <{TO_EMAIL}>, {OTHER_TO_NAME} <{OTHER_TO_EMAIL}>",
            "CC": cc_to_email,
        }
        expected_headers = CaseInsensitiveDict(expected_headers)
        expected_recipients = [
            {
                "email": TO_EMAIL,
                "substitutions": {"to_name": TO_NAME},
            },
            {
                "email": OTHER_TO_EMAIL,
                "substitutions": {"to_name": OTHER_TO_NAME},
            },
            {"email": cc_to_email},
            {"email": bcc_to_email},
        ]

        self.assertEqual(payload.data["headers"], expected_headers)
        self.assertCountEqual(payload.data["recipients"], expected_recipients)

    def test_unisender_go_payload__parse_from__with_name(self):
        email = AnymailMessage(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=str(Address(display_name=FROM_NAME, addr_spec=FROM_EMAIL)),
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
        }

        self.assertEqual(payload.data, expected_payload)

    def test_unisender_go_payload__parse_from__without_name(self):
        email = AnymailMessage(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=FROM_EMAIL,
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL={"UNISENDER_GO_SEND_DEFAULTS": {"esp_extra": {"skip_unsubscribe": 1}}},
    )
    def test_unisender_go_payload__parse_from__with_unsub__in_settings(self):
        email = AnymailMessage(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
            "skip_unsubscribe": 1,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL={"UNISENDER_GO_SEND_DEFAULTS": {"esp_extra": {"skip_unsubscribe": 0}}},
    )
    def test_unisender_go_payload__parse_from__with_unsub__in_args(self):
        email = AnymailMessage(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
            esp_extra={"skip_unsubscribe": 1},
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
            "skip_unsubscribe": 1,
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL={
            "UNISENDER_GO_SEND_DEFAULTS": {"esp_extra": {"global_language": "en"}}
        },
    )
    def test_unisender_go_payload__parse_from__global_language__in_settings(self):
        email = AnymailMessage(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
            "global_language": "en",
        }

        self.assertEqual(payload.data, expected_payload)

    @override_settings(
        ANYMAIL={
            "UNISENDER_GO_SEND_DEFAULTS": {"esp_extra": {"global_language": "fr"}}
        },
    )
    def test_unisender_go_payload__parse_from__global_language__in_args(self):
        email = AnymailMessage(
            subject=SUBJECT,
            merge_global_data=GLOBAL_DATA,
            from_email=f"{FROM_NAME} <{FROM_EMAIL}>",
            to=[TO_EMAIL],
            esp_extra={"global_language": "en"},
        )
        backend = EmailBackend()

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
            "global_language": "en",
        }

        self.assertEqual(payload.data, expected_payload)

    def test_unisender_go_payload__parse_from__bypass_esp_extra(self):
        email = AnymailMessage(
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

        payload = UnisenderGoPayload(
            message=email, backend=backend, defaults=backend.send_defaults
        )
        expected_payload = {
            "from_email": FROM_EMAIL,
            "from_name": FROM_NAME,
            "global_substitutions": GLOBAL_DATA,
            "headers": {"to": TO_EMAIL},
            "recipients": [{"email": TO_EMAIL}],
            "subject": SUBJECT,
            "bypass_global": 1,
            "bypass_unavailable": 1,
            "bypass_unsubscribed": 1,
            "bypass_complained": 1,
        }

        self.assertEqual(payload.data, expected_payload)
