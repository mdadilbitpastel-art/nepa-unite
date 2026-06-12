"""Commission calculation + ledger lifecycle (Amazon / Flipkart model).

Commission is the platform/admin's cut on each sold line item. The rate is
category-based (see :class:`commissions.models.CommissionRate`): only an
explicit, *active* rate is charged — a category with no rate (or an inactive
one) is commission-free (0%). This module is the single source of truth for
"what is the commission on X" — the Stripe fee on the buyer's PaymentIntent and
the deduction from the seller's payout both call into here so they always agree
with the ledger.

Lifecycle helpers (``accrue_for_order`` / ``earn_for_order`` /
``reverse_for_order``) are all idempotent so they can be safely re-run from
retried Stripe webhooks or redirect-fallback reconciliation.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from commissions.models import Commission, CommissionRate

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")


def rate_for_category(category: str) -> tuple[Decimal, Decimal]:
    """Return ``(percent, min_fee)`` for a category.

    Only an explicit, *active* CommissionRate is charged. A category with no
    rate — or an inactive one — is commission-free (0%).
    """
    if category:
        rate = CommissionRate.objects.filter(
            category=category, is_active=True
        ).first()
        if rate is not None:
            return rate.percent, rate.min_fee
    return Decimal("0"), Decimal("0.00")


def compute_commission(category: str, base_amount: Decimal) -> tuple[Decimal, Decimal]:
    """Return ``(rate_percent, commission_amount)`` for a base amount.

    Applies the category's minimum-fee floor when the percentage falls below it.
    """
    percent, min_fee = rate_for_category(category)
    amount = (base_amount * percent / Decimal(100)).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )
    if min_fee and amount < min_fee:
        amount = min_fee.quantize(CENTS, rounding=ROUND_HALF_UP)
    return percent, amount


def _item_category(item) -> str:
    return item.product.category_value if item.product_id else ""


def commission_for_item(item) -> Decimal:
    """Commission amount for a single OrderItem (its line total × category rate)."""
    base = Decimal(item.quantity) * item.unit_price
    _, amount = compute_commission(_item_category(item), base)
    return amount


def commission_total_for_order(order) -> Decimal:
    """Sum of per-item commissions for an order — the platform fee on the PI."""
    total = Decimal("0.00")
    for item in order.items.select_related("product").all():
        total += commission_for_item(item)
    return total.quantize(CENTS)


# ---------------------------------------------------------------------------
# Ledger lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def accrue_for_order(order) -> list[Commission]:
    """Book a PENDING commission per order item. Idempotent (one row per item)."""
    created: list[Commission] = []
    for item in order.items.select_related("product").all():
        base = (Decimal(item.quantity) * item.unit_price).quantize(CENTS)
        category = _item_category(item)
        percent, amount = compute_commission(category, base)
        obj, was_created = Commission.objects.get_or_create(
            order_item=item,
            defaults={
                "order": order,
                "seller_id": item.seller_id,
                "category": category,
                "base_amount": base,
                "rate_percent": percent,
                "commission_amount": amount,
                "status": Commission.Status.PENDING,
            },
        )
        if was_created:
            created.append(obj)
    return created


def earn_for_order(order) -> int:
    """Mark this order's PENDING commissions EARNED (e.g. on delivery)."""
    return Commission.objects.filter(
        order=order, status=Commission.Status.PENDING
    ).update(
        status=Commission.Status.EARNED,
        earned_at=timezone.now(),
        updated_at=timezone.now(),
    )


def reverse_for_order(order) -> int:
    """Reverse all non-reversed commissions for an order (cancel / refund)."""
    return (
        Commission.objects.filter(order=order)
        .exclude(status=Commission.Status.REVERSED)
        .update(
            status=Commission.Status.REVERSED,
            reversed_at=timezone.now(),
            updated_at=timezone.now(),
        )
    )


def summary(queryset=None) -> dict:
    """Totals + counts grouped by status, for the admin earnings dashboard."""
    from django.db.models import Count, Sum

    qs = Commission.objects.all() if queryset is None else queryset
    out: dict[str, dict] = {}
    earned_total = Decimal("0.00")
    for status_value, _ in Commission.Status.choices:
        agg = qs.filter(status=status_value).aggregate(
            total=Sum("commission_amount"), count=Count("id")
        )
        total = agg["total"] or Decimal("0.00")
        out[status_value] = {"total": str(total), "count": agg["count"]}
        if status_value == Commission.Status.EARNED:
            earned_total = total
    out["earned_total"] = str(earned_total)
    return out
