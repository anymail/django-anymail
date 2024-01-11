from __future__ import annotations

import json
import typing
from datetime import datetime, timezone
from hashlib import md5

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.crypto import constant_time_compare

from anymail.exceptions import AnymailWebhookValidationFailure
from anymail.signals import AnymailTrackingEvent, EventType, RejectReason, tracking
from anymail.webhooks.base import AnymailCoreWebhookView

"""
Callback API example:
{
   "auth":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
   "events_by_user":
   [
      {
        "user_id":456,
        "project_id":"6432890213745872",
        "project_name":"MyProject",
        "events":
        [
          {
            "event_name":"transactional_email_status",
            "event_data":
            {
              "job_id":"1a3Q2V-0000OZ-S0",
              "metadata":
              {
                "key1":"val1",
                "key2":"val2"
              },
              "email":"recipient.email@example.com",
              "status":"sent",
              "event_time":"2015-11-30 15:09:42",
              "url":"http://some.url.com",
              "delivery_info":
              {
                "delivery_status": "err_delivery_failed",
                "destination_response": "550 Spam rejected",
                "user_agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36...",
                "ip":"111.111.111.111"
              }
            }
          },
          {
            "event_name":"transactional_spam_block",
            "event_data":
            {
              "block_time":"YYYY-MM-DD HH:MM:SS",
              "block_type":"one_smtp",
              "domain":"domain_name",
              "SMTP_blocks_count":8,
              "domain_status":"blocked"
            }
          }
        ]
      }
   ]
}
"""


class UnisenderGoTrackingWebhookView(AnymailCoreWebhookView):
    """Handler for UniSender delivery and engagement tracking webhooks"""

    esp_name = "UnisenderGo"
    signal = tracking

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
        "err_user_unknown": RejectReason.INVALID,
        "err_user_inactive": RejectReason.INVALID,
        "err_will_retry": RejectReason.INVALID,
        "err_mailbox_discarded": RejectReason.INVALID,
        "err_mailbox_full": RejectReason.BOUNCED,
        "err_spam_rejected": RejectReason.SPAM,
        "err_blacklisted": RejectReason.BLOCKED,
        "err_too_large": RejectReason.BLOCKED,
        "err_unsubscribed": RejectReason.UNSUBSCRIBED,
        "err_unreachable": RejectReason.INVALID,
        "err_skip_letter": RejectReason.INVALID,
        "err_domain_inactive": RejectReason.INVALID,
        "err_destination_misconfigured": RejectReason.BOUNCED,
        "err_delivery_failed": RejectReason.OTHER,
        "err_spam_skipped": RejectReason.SPAM,
        "err_lost": RejectReason.OTHER,
    }

    http_method_names = ["post", "head", "options", "get"]

    def get(
        self, request: HttpRequest, *args: typing.Any, **kwargs: typing.Any
    ) -> HttpResponse:
        # Some ESPs verify the webhook with a GET request at configuration time
        return HttpResponse()

    def validate_request(self, request: HttpRequest) -> None:
        """
        How Unisender GO authenticate:
        Hash the whole request body text and replace api key in "auth" field by this hash.

        So it is both auth and encryption. Also, they hash JSON without spaces.
        """
        request_json = json.loads(request.body.decode("utf-8"))
        request_auth = request_json.get("auth", "")
        request_json["auth"] = settings.ANYMAIL_UNISENDERGO_API_KEY
        json_with_key = json.dumps(request_json, separators=(",", ":"))

        expected_auth = md5(json_with_key.encode("utf-8")).hexdigest()

        if not constant_time_compare(request_auth, expected_auth):
            raise AnymailWebhookValidationFailure(
                f"Missing or invalid basic auth in Anymail {self.esp_name} webhook"
            )

    def parse_events(self, request: HttpRequest) -> list[AnymailTrackingEvent]:
        request_json = json.loads(request.body.decode("utf-8"))
        esp_events = request_json["events_by_user"][0]["events"]
        parsed_events = [
            self.esp_to_anymail_event(esp_event) for esp_event in esp_events
        ]
        return [event for event in parsed_events if event]

    def esp_to_anymail_event(self, esp_event: dict) -> AnymailTrackingEvent | None:
        if esp_event["event_name"] == "transactional_spam_block":
            return None
        event_data = esp_event["event_data"]
        event_type = self.event_types.get(event_data["status"], EventType.UNKNOWN)
        timestamp = datetime.fromisoformat(event_data["event_time"])
        timestamp_utc = timestamp.replace(tzinfo=timezone.utc)
        metadata = event_data["metadata"]
        event_data["esp_name"] = self.esp_name
        delivery_info = event_data.get("delivery_info", {})
        unisender_delivery_status = delivery_info.get("delivery_status", "")
        if unisender_delivery_status.startswith("err"):
            anymail_reject_reason = self.reject_reasons.get(
                unisender_delivery_status, RejectReason.OTHER
            )
        else:
            anymail_reject_reason = ""

        return AnymailTrackingEvent(
            event_type=event_type,
            timestamp=timestamp_utc,
            message_id=metadata.get("message_id", None),
            event_id=None,
            recipient=event_data["email"],
            reject_reason=anymail_reject_reason,
            mta_response=delivery_info.get("destination_response", ""),
            tags=None,
            metadata=metadata,
            click_url=None,
            user_agent=delivery_info.get("use_ragent", ""),
            esp_event=event_data,
        )
