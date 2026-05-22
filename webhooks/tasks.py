"""Webhook tasks — Stripe inbound dispatch + outgoing platform events."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from notifications.service import notify
from notifications.models import Notification
from webhooks.handlers import dispatch
from webhooks.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

PLATFORM_EVENT_TYPES = {
    "order.created", "order.confirmed", "order.shipped",
    "order.delivered", "order.cancelled",
    "payment.completed", "payment.failed", "dispute.opened",
    "member.approved", "member.suspended",
    "contract.updated", "contract.expired",
}

MAX_ATTEMPTS = 5


# ---------------------------------------------------------------------------
# Stripe inbound dispatch
# ---------------------------------------------------------------------------
@shared_task
def process_stripe_event(event: dict) -> None:
    dispatch(event)


# ---------------------------------------------------------------------------
# Platform outgoing webhooks
# ---------------------------------------------------------------------------
@shared_task
def emit_platform_event(event_type: str, payload: dict) -> None:
    """Fan out an event to every registered endpoint subscribed to it."""
    if event_type not in PLATFORM_EVENT_TYPES:
        logger.warning("Unknown platform event type: %s", event_type)
        return
    endpoints = WebhookEndpoint.objects.filter(is_active=True)
    for endpoint in endpoints:
        if endpoint.event_types and event_type not in endpoint.event_types:
            continue
        delivery = WebhookDelivery.objects.create(
            endpoint=endpoint,
            event_type=event_type,
            payload=payload,
        )
        deliver_webhook.delay(str(delivery.pk))


@shared_task(bind=True)
def deliver_webhook(self, delivery_id: str) -> None:
    """Attempt delivery; on failure, schedule the next retry per OUTGOING_WEBHOOK_RETRY_DELAYS."""
    try:
        delivery = WebhookDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    except WebhookDelivery.DoesNotExist:
        return

    endpoint = delivery.endpoint
    delivery.attempt += 1

    body = json.dumps({
        "event_type": delivery.event_type,
        "payload": delivery.payload,
        "delivery_id": str(delivery.pk),
        "attempt": delivery.attempt,
    })
    signature = hmac.new(
        endpoint.secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    try:
        resp = requests.post(
            endpoint.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-NEPA-Signature": signature,
                "X-NEPA-Event": delivery.event_type,
            },
            timeout=settings.OUTGOING_WEBHOOK_TIMEOUT,
        )
        delivery.last_status_code = resp.status_code
        delivery.last_response = (resp.text or "")[:2000]
        ok = 200 <= resp.status_code < 300
    except requests.RequestException as exc:
        delivery.last_status_code = None
        delivery.last_response = str(exc)[:2000]
        ok = False

    if ok:
        delivery.status = WebhookDelivery.Status.DELIVERED
        delivery.delivered_at = timezone.now()
        endpoint.failure_count = 0
        endpoint.last_delivery_at = timezone.now()
        endpoint.save(update_fields=["failure_count", "last_delivery_at", "updated_at"])
        delivery.save()
        return

    # Failure path — schedule the next retry or give up.
    delays = settings.OUTGOING_WEBHOOK_RETRY_DELAYS
    if delivery.attempt < MAX_ATTEMPTS:
        delay = delays[min(delivery.attempt - 1, len(delays) - 1)]
        delivery.next_retry_at = timezone.now() + timedelta(seconds=delay)
        delivery.save()
        deliver_webhook.apply_async(args=[delivery_id], countdown=delay)
    else:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.save()
        endpoint.failure_count += 1
        endpoint.save(update_fields=["failure_count", "updated_at"])
        _notify_admin_endpoint_failed(endpoint, delivery)


def _notify_admin_endpoint_failed(endpoint: WebhookEndpoint, delivery: WebhookDelivery) -> None:
    from users.models import CustomUser
    for admin in CustomUser.objects.filter(role=CustomUser.Role.ADMIN):
        notify(
            recipient=admin,
            kind=Notification.Kind.SYSTEM,
            title=f"Webhook endpoint failed: {endpoint.url}",
            body=(
                f"Delivery {delivery.pk} for event {delivery.event_type} "
                f"failed after {delivery.attempt} attempts."
            ),
            payload={
                "endpoint_id": str(endpoint.pk),
                "delivery_id": str(delivery.pk),
            },
            send_email=False,
        )
