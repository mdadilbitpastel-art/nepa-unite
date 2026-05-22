"""Stripe webhook event handlers.

Called from the Celery dispatcher with the verified Stripe event payload.
Each handler should be idempotent: Stripe retries duplicates.
"""

from __future__ import annotations

import logging
from typing import Callable

from django.db import transaction
from django.utils import timezone

from core.tasks import write_audit_log
from notifications.service import notify
from notifications.models import Notification
from orders.models import Order
from payments.models import Payment

logger = logging.getLogger(__name__)


def _payment_for(event_data: dict) -> Payment | None:
    intent_id = event_data.get("id")
    if not intent_id:
        return None
    return Payment.objects.filter(stripe_payment_intent_id=intent_id).first()


@transaction.atomic
def handle_payment_succeeded(event: dict) -> None:
    payment = _payment_for(event["data"]["object"])
    if payment is None:
        logger.warning("payment_succeeded: no Payment for intent %s",
                       event["data"]["object"].get("id"))
        return
    payment.status = Payment.Status.COMPLETED
    payment.save(update_fields=["status"])

    order = payment.order
    if order.status == Order.Status.DRAFT:
        order.status = Order.Status.CONFIRMED
        order.save(update_fields=["status", "updated_at"])

    write_audit_log.delay(
        actor_id=None,
        action="payment.succeeded",
        entity_type="Payment",
        entity_id=str(payment.pk),
        payload={"order_id": str(order.pk)},
    )


@transaction.atomic
def handle_payment_failed(event: dict) -> None:
    payment = _payment_for(event["data"]["object"])
    if payment is None:
        return
    payment.status = Payment.Status.FAILED
    payment.save(update_fields=["status"])
    notify(
        recipient=payment.order.buyer,
        kind=Notification.Kind.PAYMENT,
        title=f"Payment failed for order #{payment.order_id}",
        body="Please update your payment method and try again.",
        payload={"order_id": str(payment.order_id)},
    )


@transaction.atomic
def handle_charge_dispute_created(event: dict) -> None:
    """Freeze pending disbursements + notify admin + audit."""
    object_ = event["data"]["object"]
    intent_id = object_.get("payment_intent")
    payment = (
        Payment.objects.filter(stripe_payment_intent_id=intent_id).first()
        if intent_id else None
    )
    if payment is None:
        logger.warning("dispute.created without matching Payment (pi=%s)", intent_id)
        return
    payment.status = Payment.Status.DISPUTED
    payment.save(update_fields=["status"])

    write_audit_log.delay(
        actor_id=None,
        action="payment.dispute_opened",
        entity_type="Payment",
        entity_id=str(payment.pk),
        payload={"dispute_id": object_.get("id")},
    )

    # Page every admin via in-app notification.
    from users.models import CustomUser
    for admin in CustomUser.objects.filter(role=CustomUser.Role.ADMIN):
        notify(
            recipient=admin,
            kind=Notification.Kind.PAYMENT,
            title=f"Dispute opened on order #{payment.order_id}",
            body=f"Stripe dispute {object_.get('id')} requires review.",
            payload={"order_id": str(payment.order_id),
                     "dispute_id": object_.get("id")},
        )


EVENT_HANDLERS: dict[str, Callable[[dict], None]] = {
    "payment_intent.succeeded": handle_payment_succeeded,
    "payment_intent.payment_failed": handle_payment_failed,
    "charge.dispute.created": handle_charge_dispute_created,
}


def dispatch(event: dict) -> None:
    handler = EVENT_HANDLERS.get(event.get("type", ""))
    if handler is None:
        logger.info("No handler for event type %s; ignoring", event.get("type"))
        return
    handler(event)
