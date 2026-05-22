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
    order = Order.objects.select_for_update().get(pk=order_id)
    amount_cents = _to_cents(order.total_amount)
    fee_cents = int(
        amount_cents * Decimal(settings.STRIPE_PLATFORM_FEE_PERCENT) / Decimal(100)
    )

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
        platform_fee=Decimal(fee_cents) / Decimal(100),
        status=Payment.Status.PENDING,
    )
    return {"client_secret": intent.client_secret, "payment_intent_id": intent.id}


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

    gross = Decimal(item.quantity) * item.unit_price
    fee = (gross * Decimal(settings.STRIPE_PLATFORM_FEE_PERCENT) / Decimal(100))
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

    for item in order.items.all():
        try:
            release_inventory(str(item.product_id), item.quantity)
        except Exception:  # noqa: BLE001
            logger.warning("release_inventory failed for item %s", item.pk)

    order.status = Order.Status.CANCELLED
    order.save(update_fields=["status", "updated_at"])
