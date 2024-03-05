from __future__ import annotations

import json
import typing
from datetime import datetime, timezone
from hashlib import md5

from django.http import HttpRequest, HttpResponse
from django.utils.crypto import constant_time_compare

from anymail.exceptions import AnymailWebhookValidationFailure
from anymail.signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from anymail.utils import get_anymail_setting
from anymail.webhooks.base import AnymailCoreWebhookView


class UnisenderGoTrackingWebhookView(AnymailCoreWebhookView):
    """Handler for UniSender delivery and engagement tracking webhooks"""

    # See https://godocs.unisender.ru/web-api-ref#callback-format for webhook payload

    esp_name = "Unisender Go"
    signal = tracking
    warn_if_no_basic_auth = False  # because we validate against signature

    event_types = {
        "sent": EventType.SENT,
        "delivered": EventType.DELIVERED,
        "opened": EventType.OPENED,
        "clicked": EventType.CLICKED,
        "unsubscribed": EventType.UNSUBSCRIBED,
        "subscribed": EventType.SUBSCRIBED,
        "spam": EventType.COMPLAINED,
        "soft_bounced": EventType.BOUNCED,
        "hard_bounced": EventType.BOUNCED,
    }

    reject_reasons = {
        "err_user_unknown": RejectReason.BOUNCED,
        "err_user_inactive": RejectReason.BOUNCED,
        "err_will_retry": RejectReason.BOUNCED,
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

    def get(
        self, request: HttpRequest, *args: typing.Any, **kwargs: typing.Any
    ) -> HttpResponse:
        # Unisender Go verifies the webhook with a GET request at configuration time
        return HttpResponse()

    def validate_request(self, request: HttpRequest) -> None:
        """
        How Unisender GO authenticate:
        Hash the whole request body text and replace api key in "auth" field by this hash.

        So it is both auth and encryption. Also, they hash JSON without spaces.
        """
        request_json = json.loads(request.body.decode("utf-8"))
        request_auth = request_json.get("auth", "")
        request_json["auth"] = get_anymail_setting(
            "api_key", esp_name=self.esp_name, allow_bare=True
        )
        json_with_key = json.dumps(request_json, separators=(",", ":"))

        expected_auth = md5(json_with_key.encode("utf-8")).hexdigest()

        if not constant_time_compare(request_auth, expected_auth):
            raise AnymailWebhookValidationFailure(
                "Unisender Go webhook called with incorrect signature"
            )

    def parse_events(self, request: HttpRequest) -> list[AnymailTrackingEvent]:
        request_json = json.loads(request.body.decode("utf-8"))
        assert len(request_json["events_by_user"]) == 1  # per API docs
        esp_events = request_json["events_by_user"][0]["events"]
        return [
            self.esp_to_anymail_event(esp_event)
            for esp_event in esp_events
            if esp_event["event_name"] == "transactional_email_status"
        ]

    def esp_to_anymail_event(self, esp_event: dict) -> AnymailTrackingEvent:
        event_data = esp_event["event_data"]
        event_type = self.event_types.get(event_data["status"], EventType.UNKNOWN)
        timestamp = datetime.fromisoformat(event_data["event_time"])
        timestamp_utc = timestamp.replace(tzinfo=timezone.utc)
        metadata = event_data.get("metadata", {})
        message_id = metadata.pop("anymail_id", event_data.get("job_id"))

        delivery_info = event_data.get("delivery_info", {})
        delivery_status = delivery_info.get("delivery_status", "")
        if delivery_status.startswith("err"):
            reject_reason = self.reject_reasons.get(delivery_status, RejectReason.OTHER)
        else:
            reject_reason = None

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp_utc,
            message_id=message_id,
            event_id=None,
            recipient=event_data["email"],
            reject_reason=reject_reason,
            mta_response=delivery_info.get("destination_response"),
            metadata=metadata,
            click_url=event_data.get("url"),
            user_agent=delivery_info.get("user_agent"),
            esp_event=event_data,
        )
