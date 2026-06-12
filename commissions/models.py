from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class CommissionRate(models.Model):
    """Per-category referral-fee schedule (Amazon / Flipkart style).

    The marketplace's commission ("referral fee") varies by product category.
    ``category`` matches ``Product.attributes['category']`` (exposed as
    ``Product.category_value``). A category with no active row is
    commission-free (0%).

    ``min_fee`` is Amazon's "minimum referral fee" floor — when the percentage
    works out to less than this, the floor is charged instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=128, unique=True)
    percent = models.DecimalField(max_digits=5, decimal_places=2)
    min_fee = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commissions_commissionrate"
        ordering = ["category"]

    def __str__(self) -> str:
        return f"{self.category}: {self.percent}%"


class Commission(models.Model):
    """Admin's commission on one sold line item — an append-style ledger row.

    One Commission per OrderItem. Lifecycle mirrors a marketplace settlement:
    accrued (``pending``) when the buyer's payment is captured, ``earned`` once
    the order is delivered, and ``reversed`` if the order is cancelled/refunded.
    The rate and base amount are snapshotted so later rate changes never rewrite
    booked history.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        EARNED = "earned", "Earned"
        REVERSED = "reversed", "Reversed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        "orders.Order", on_delete=models.PROTECT, related_name="commissions"
    )
    order_item = models.OneToOneField(
        "orders.OrderItem", on_delete=models.PROTECT, related_name="commission"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="commissions",
    )
    category = models.CharField(max_length=128, blank=True, default="")
    base_amount = models.DecimalField(max_digits=12, decimal_places=2)
    rate_percent = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    earned_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "commissions_commission"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["seller", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Commission[{self.commission_amount} on order {self.order_id}]"
