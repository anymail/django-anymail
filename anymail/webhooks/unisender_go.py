from __future__ import annotations

import json
import typing
from datetime import datetime, timezone
from hashlib import md5

from django.http import HttpRequest, HttpResponse
from django.utils.crypto import constant_time_compare

from ..exceptions import AnymailWebhookValidationFailure
from ..signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from ..utils import get_anymail_setting
from .base import AnymailBaseWebhookView


class UnisenderGoTrackingWebhookView(AnymailBaseWebhookView):
    """Handler for Unisender Go delivery and engagement tracking webhooks"""

    # See https://godocs.unisender.ru/web-api-ref#callback-format for webhook payload

    esp_name = "Unisender Go"
    signal = tracking
    warn_if_no_basic_auth = False  # because we validate against signature

    api_key: str | None = None  # allows kwargs override

    event_types = {
        "sent": EventType.SENT,
        "delivered": EventType.DELIVERED,
        "opened": EventType.OPENED,
        "clicked": EventType.CLICKED,
        "unsubscribed": EventType.UNSUBSCRIBED,
        "subscribed": EventType.SUBSCRIBED,
        "spam": EventType.COMPLAINED,
        "soft_bounced": EventType.DEFERRED,
        "hard_bounced": EventType.BOUNCED,
    }

    reject_reasons = {
        "err_user_unknown": RejectReason.BOUNCED,
        "err_user_inactive": RejectReason.BOUNCED,
        "err_will_retry": None,  # not rejected
        "err_mailbox_discarded": RejectReason.BOUNCED,
        "err_mailbox_full": RejectReason.BOUNCED,
        "err_spam_rejected": RejectReason.SPAM,
        "err_blacklisted": RejectReason.BLOCKED,
        "err_too_large": RejectReason.BOUNCED,
        "err_unsubscribed": RejectReason.UNSUBSCRIBED,
        "err_unreachable": RejectReason.BOUNCED,
        "err_skip_letter": RejectReason.BOUNCED,
        "err_domain_inactive": RejectReason.BOUNCED,
        "err_destination_misconfigured": RejectReason.BOUNCED,
        "err_delivery_failed": RejectReason.OTHER,
        "err_spam_skipped": RejectReason.SPAM,
        "err_lost": RejectReason.OTHER,
    }

    http_method_names = ["post", "head", "options", "get"]

    def __init__(self, **kwargs):
        api_key = get_anymail_setting(
            "api_key", esp_name=self.esp_name, allow_bare=True, kwargs=kwargs
        )
        self.api_key_bytes = api_key.encode("ascii")
        super().__init__(**kwargs)

    def get(
        self, request: HttpRequest, *args: typing.Any, **kwargs: typing.Any
    ) -> HttpResponse:
        # Unisender Go verifies the webhook with a GET request at configuration time
        return HttpResponse()

    def parse_json_body(self, request: HttpRequest) -> dict:
        # Cache parsed JSON request.body on the request.
        if hasattr(request, "_parsed_json"):
            parsed: dict = getattr(request, "_parsed_json")
        else:
            parsed = json.loads(request.body.decode())
            setattr(request, "_parsed_json", parsed)
        return parsed

    def validate_request(self, request: HttpRequest) -> None:
        """
        Validate Unisender Go webhook signature:
        "MD5 hash of the string body of the message, with the auth value replaced
        by the api_key of the user/project whose handler is being called."
        https://godocs.unisender.ru/web-api-ref#callback-format
        """
        # This must avoid any assumptions about how Unisender Go serializes JSON
        # (key order, spaces, Unicode encoding vs. \u escapes, etc.). But we do
        # assume the "auth" field MD5 hash is unique within the serialized JSON,
        # so that we can use string replacement to calculate the expected hash.
        body = request.body
        try:
            parsed = self.parse_json_body(request)
            actual_auth = parsed["auth"]
            actual_auth_bytes = actual_auth.encode()
        except (AttributeError, KeyError, ValueError):
            raise AnymailWebhookValidationFailure(
                "Unisender Go webhook called with invalid payload"
            )

        body_to_sign = body.replace(actual_auth_bytes, self.api_key_bytes)
        expected_auth = md5(body_to_sign).hexdigest()
        if not constant_time_compare(actual_auth, expected_auth):
            # If webhook has a selected project, include the project_id in the error.
            try:
                project_id = parsed["events_by_user"][0]["project_id"]
            except (KeyError, IndexError):
                project_id = parsed.get("project_id")  # try "single event" payload
            is_for_project = f" is for Project ID {project_id}" if project_id else ""
            raise AnymailWebhookValidationFailure(
                "Unisender Go webhook called with incorrect signature"
                f" (check Anymail UNISENDER_GO_API_KEY setting{is_for_project})"
            )

    def parse_events(self, request: HttpRequest) -> list[AnymailTrackingEvent]:
        parsed = self.parse_json_body(request)
        # Unisender Go has two options for webhook payloads. We support both.
        try:
            events_by_user = parsed["events_by_user"]
        except KeyError:
            # "Use single event": one flat dict, combining "event_data" fields
            # with "event_name", "user_id", "project_id", etc.
            if parsed["event_name"] == "transactional_email_status":
                esp_events = [parsed]
            else:
                esp_events = []
        else:
            # Not "use single event": we want the "event_data" from all events
            # with event_name "transactional_email_status".
            assert len(events_by_user) == 1  # "A single element array" per API docs
            esp_events = [
                event["event_data"]
                for event in events_by_user[0]["events"]
                if event["event_name"] == "transactional_email_status"
            ]

        return [self.esp_to_anymail_event(esp_event) for esp_event in esp_events]

    def esp_to_anymail_event(self, event_data: dict) -> AnymailTrackingEvent:
        event_type = self.event_types.get(event_data["status"], EventType.UNKNOWN)

        # Unisender Go does not provide any way to deduplicate webhook calls.
        # (There is an "ID" HTTP header, but it has a unique value for every
        # webhook call--including retransmissions of earlier failed calls.)
        event_id = None

        # event_time is ISO-like, without a stated time zone. (But it's UTC per docs.)
        try:
            timestamp = datetime.fromisoformat(event_data["event_time"]).replace(
                tzinfo=timezone.utc
            )
        except KeyError:
            timestamp = None

        # Extract our message_id (see backend UNISENDER_GO_GENERATE_MESSAGE_ID).
        metadata = event_data.get("metadata", {}).copy()
        message_id = metadata.pop("anymail_id", event_data.get("job_id"))

        delivery_info = event_data.get("delivery_info", {})
        delivery_status = delivery_info.get("delivery_status", "")
        if delivery_status.startswith("err"):
            reject_reason = self.reject_reasons.get(delivery_status, RejectReason.OTHER)
        else:
            reject_reason = None

        description = delivery_info.get("delivery_status") or event_data.get("comment")
        mta_response = delivery_info.get("destination_response")

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp,
            message_id=message_id,
            event_id=event_id,
            recipient=event_data["email"],
            reject_reason=reject_reason,
            description=description,
            mta_response=mta_response,
            metadata=metadata,
            click_url=event_data.get("url"),
            user_agent=delivery_info.get("user_agent"),
            esp_event=event_data,
        )
