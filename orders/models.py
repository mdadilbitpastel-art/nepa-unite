from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        FULFILLMENT = "fulfillment", "Fulfillment"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.PROTECT,
        related_name="orders",
        db_column="tenant_id",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    shipping_name = models.CharField(max_length=255, blank=True, default="")
    shipping_phone = models.CharField(max_length=20, blank=True, default="")
    shipping_address_line1 = models.CharField(max_length=255, blank=True, default="")
    shipping_address_line2 = models.CharField(max_length=255, blank=True, default="")
    shipping_city = models.CharField(max_length=100, blank=True, default="")
    shipping_state = models.CharField(max_length=50, blank=True, default="")
    shipping_zip = models.CharField(max_length=20, blank=True, default="")
    buyer_notes = models.TextField(blank=True, default="")
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, default="")
    status_changed_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_order"

    @property
    def calculated_total(self) -> Decimal:
        """Sum of (quantity * unit_price) across all items.

        Source of truth for charging; `total_amount` is the stored snapshot.
        """
        total = Decimal("0.00")
        for item in self.items.all():
            total += Decimal(item.quantity) * item.unit_price
        return total


class OrderItem(models.Model):
    class FulfillmentStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        FULFILLED = "fulfilled", "Fulfilled"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT, related_name="order_items"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sold_items",
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    fulfillment_status = models.CharField(
        max_length=16,
        choices=FulfillmentStatus.choices,
        default=FulfillmentStatus.PENDING,
    )

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    class Meta:
        db_table = "orders_orderitem"


class OrderActivityLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="activity_logs"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="order_actions",
    )
    from_status = models.CharField(max_length=16, blank=True, default="")
    to_status = models.CharField(max_length=16)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders_orderactivitylog"
        ordering = ["-created_at"]
