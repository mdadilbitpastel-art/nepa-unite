"""Stripe Connect operations: seller onboarding, payment intents, transfers, refunds.

Funds flow: buyer pays the platform Stripe account. After delivery confirmation
the platform issues a Transfer to the seller's connected account minus the
platform fee. Refunds reverse the original PaymentIntent.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from orders.models import Order
from payments.models import Payment
from products.inventory import release_inventory
from users.models import CustomUser

logger = logging.getLogger(__name__)


def _configure() -> None:
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _to_cents(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


# ---------------------------------------------------------------------------
# Health probe
# ---------------------------------------------------------------------------
def stripe_mode() -> str:
    """'test', 'live', or 'unset' inferred from the secret key prefix."""
    key = settings.STRIPE_SECRET_KEY or ""
    if key.startswith("sk_test_") or key.startswith("rk_test_"):
        return "test"
    if key.startswith("sk_live_") or key.startswith("rk_live_"):
        return "live"
    return "unset"


def stripe_health() -> tuple[bool, str | None]:
    """Lightweight Stripe connectivity probe for the admin health dashboard.

    Deliberately NOT wired into the load-balancer /api/health/ probe: Stripe is
    a third-party dependency, and a slow or down Stripe must never take this
    service out of rotation. We make a cheap authenticated call (Balance) to
    confirm the secret key is valid and the API is reachable.
    """
    if not settings.STRIPE_SECRET_KEY:
        return False, "STRIPE_SECRET_KEY not configured"
    _configure()
    try:
        stripe.Balance.retrieve()
        return True, None
    except Exception as exc:  # noqa: BLE001 - report any failure verbatim
        return False, str(exc)


# ---------------------------------------------------------------------------
# Seller onboarding
# ---------------------------------------------------------------------------
def create_seller_account(user_id: str) -> str:
    """Create an Express Connect account + onboarding link.

    Returns the onboarding URL the seller should visit. The
    `stripe_account_id` is stored on the CustomUser.
    """
    _configure()
    user = CustomUser.objects.get(pk=user_id)
    if not user.stripe_account_id:
        account = stripe.Account.create(
            type="express",
            email=user.email,
            capabilities={
                "card_payments": {"requested": True},
                "transfers": {"requested": True},
            },
        )
        user.stripe_account_id = account.id
        user.save(update_fields=["stripe_account_id", "updated_at"])

    link = stripe.AccountLink.create(
        account=user.stripe_account_id,
        return_url=settings.STRIPE_ONBOARDING_RETURN_URL,
        refresh_url=settings.STRIPE_ONBOARDING_REFRESH_URL,
        type="account_onboarding",
    )
    return link.url


# ---------------------------------------------------------------------------
# Buyer-side payment intent
# ---------------------------------------------------------------------------
@transaction.atomic
def create_payment_intent(order_id: str) -> dict[str, Any]:
    """Create a PaymentIntent that lands in the platform account.

    The application fee is the platform's cut; the remainder is later
    transferred to the seller(s) via `disburse_to_seller`.
    Returns {"client_secret": ..., "payment_intent_id": ...}.
    """
    _configure()
    from commissions.services import commission_total_for_order

    order = Order.objects.select_for_update().get(pk=order_id)
    amount_cents = _to_cents(order.total_amount)
    # Platform fee = the admin's commission, summed over the order's line items
    # at their category rates (single source of truth with the commission ledger).
    platform_fee = commission_total_for_order(order)

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        metadata={"order_id": str(order.pk)},
        automatic_payment_methods={"enabled": True},
    )

    order.stripe_payment_intent_id = intent.id
    order.save(update_fields=["stripe_payment_intent_id", "updated_at"])

    Payment.objects.create(
        order=order,
        stripe_payment_intent_id=intent.id,
        amount=order.total_amount,
        platform_fee=platform_fee,
        status=Payment.Status.PENDING,
    )
    return {"client_secret": intent.client_secret, "payment_intent_id": intent.id}


# Stripe statuses for which an existing PaymentIntent can still be reused by the
# buyer (i.e. not yet paid and not in a terminal/canceled state).
_REUSABLE_INTENT_STATUSES = {
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
    "processing",
}


def get_or_create_payment_intent(order_id: str) -> dict[str, Any]:
    """Return a client_secret for the order, reusing an open PaymentIntent.

    Used by the buyer checkout page so that re-loading the page does not spawn a
    fresh PaymentIntent (and a fresh pending Payment row) every time. Falls back
    to `create_payment_intent` when there is no reusable intent yet.
    """
    _configure()
    order = Order.objects.get(pk=order_id)
    pending = (
        order.payments.filter(status=Payment.Status.PENDING)
        .exclude(stripe_payment_intent_id="")
        .order_by("-created_at")
        .first()
    )
    if pending is not None:
        try:
            intent = stripe.PaymentIntent.retrieve(pending.stripe_payment_intent_id)
        except stripe.error.StripeError:
            intent = None
        if intent is not None and intent.status in _REUSABLE_INTENT_STATUSES:
            return {
                "client_secret": intent.client_secret,
                "payment_intent_id": intent.id,
            }
    return create_payment_intent(order_id)


@transaction.atomic
def sync_payment_status(order_id: str) -> str | None:
    """Reconcile a Payment/Order with Stripe by retrieving the PaymentIntent.

    Returns the Stripe PaymentIntent status (or None when the order has no
    intent yet). This makes the buyer checkout flow work in environments where
    no Stripe webhook is configured (e.g. local test mode): on the post-payment
    redirect we pull the authoritative status straight from Stripe rather than
    waiting on `payment_intent.succeeded`. Webhook handling stays the source of
    truth in production; both paths are idempotent.
    """
    _configure()
    order = Order.objects.select_for_update().get(pk=order_id)
    if not order.stripe_payment_intent_id:
        return None

    intent = stripe.PaymentIntent.retrieve(order.stripe_payment_intent_id)
    payment = Payment.objects.filter(stripe_payment_intent_id=intent.id).first()
    if payment is None:
        return intent.status

    if intent.status == "succeeded":
        if payment.status != Payment.Status.COMPLETED:
            payment.status = Payment.Status.COMPLETED
            payment.save(update_fields=["status"])
        if order.status == Order.Status.DRAFT:
            order.status = Order.Status.CONFIRMED
            order.save(update_fields=["status", "updated_at"])
        # Book the admin's commission (idempotent — mirrors the webhook path).
        from commissions.services import accrue_for_order
        accrue_for_order(order)
    elif intent.status == "canceled" and payment.status == Payment.Status.PENDING:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status"])

    return intent.status


# ---------------------------------------------------------------------------
# Seller disbursement
# ---------------------------------------------------------------------------
def disburse_to_seller(order_item_id: str) -> None:
    """Transfer one order item's seller share (minus platform fee)."""
    _configure()
    from orders.models import OrderItem
    item = OrderItem.objects.select_related("seller", "order").get(pk=order_item_id)
    seller = item.seller
    if not seller.stripe_account_id:
        raise RuntimeError(f"Seller {seller.pk} has not completed Stripe onboarding")

    from commissions.services import commission_for_item

    gross = Decimal(item.quantity) * item.unit_price
    # Admin commission for this line item at its category rate (same figure
    # booked to the commission ledger).
    fee = commission_for_item(item)
    net = gross - fee

    stripe.Transfer.create(
        amount=_to_cents(net),
        currency="usd",
        destination=seller.stripe_account_id,
        transfer_group=f"order:{item.order_id}",
        metadata={
            "order_id": str(item.order_id),
            "order_item_id": str(item.pk),
        },
    )

    payment = item.order.payments.filter(
        status=Payment.Status.COMPLETED
    ).order_by("-created_at").first()
    if payment is not None:
        payment.disbursed_at = timezone.now()
        payment.save(update_fields=["disbursed_at"])


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------
@transaction.atomic
def process_refund(order_id: str) -> None:
    _configure()
    order = Order.objects.select_for_update().prefetch_related("items").get(pk=order_id)
    payment = order.payments.exclude(
        status=Payment.Status.REFUNDED
    ).order_by("-created_at").first()
    if payment is None:
        raise RuntimeError(f"No refundable payment for order {order_id}")

    stripe.Refund.create(payment_intent=payment.stripe_payment_intent_id)

    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["status"])

    # Reverse any commission booked for this order — the admin doesn't keep a
    # cut on refunded sales.
    from commissions.services import reverse_for_order
    reverse_for_order(order)

    for item in order.items.all():
        try:
            release_inventory(str(item.product_id), item.quantity)
        except Exception:  # noqa: BLE001
            logger.warning("release_inventory failed for item %s", item.pk)

    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
