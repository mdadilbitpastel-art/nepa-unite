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
    # Set the moment the order transitions to DELIVERED — the anchor for the
    # per-item return window (delivered_at + product.return_window_days).
    delivered_at = models.DateTimeField(null=True, blank=True)
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


class Cart(models.Model):
    """One persistent cart per buyer. Auto-created on first read/write."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_cart"


class CartItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="cart_items"
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_cartitem"
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product"], name="uniq_cartitem_per_cart_product"
            ),
        ]
        ordering = ["-updated_at"]


class ReturnRequest(models.Model):
    """A buyer-raised return or exchange against a single order item.

    The lifecycle (see orders/returns_state.py) is seller-managed with admin
    override: requested → approved → pickup_scheduled → picked_up → received →
    refunded (return) / exchange_shipped → exchange_completed (exchange).
    """

    class Type(models.TextChoices):
        RETURN = "return", "Return"
        EXCHANGE = "exchange", "Exchange"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        PICKUP_SCHEDULED = "pickup_scheduled", "Pickup scheduled"
        PICKED_UP = "picked_up", "Picked up"
        RECEIVED = "received", "Received"
        REFUNDED = "refunded", "Refunded"
        EXCHANGE_SHIPPED = "exchange_shipped", "Exchange shipped"
        EXCHANGE_COMPLETED = "exchange_completed", "Exchange completed"

    class Reason(models.TextChoices):
        DEFECTIVE = "defective", "Defective / damaged"
        WRONG_ITEM = "wrong_item", "Wrong item delivered"
        NOT_AS_DESCRIBED = "not_as_described", "Not as described"
        SIZE_FIT = "size_fit", "Size / fit issue"
        NO_LONGER_NEEDED = "no_longer_needed", "No longer needed"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="returns"
    )
    order_item = models.ForeignKey(
        OrderItem, on_delete=models.CASCADE, related_name="returns"
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="return_requests",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="seller_returns",
    )
    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.PROTECT,
        related_name="returns",
        db_column="tenant_id",
    )
    type = models.CharField(
        max_length=16, choices=Type.choices, default=Type.RETURN
    )
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.REQUESTED
    )
    reason = models.CharField(max_length=24, choices=Reason.choices)
    reason_note = models.TextField(blank=True, default="")
    quantity = models.PositiveIntegerField(default=1)
    refund_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    # For an exchange: the replacement product the buyer wants (defaults to the
    # same product). Null for a plain return.
    exchange_product = models.ForeignKey(
        "products.Product",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="exchange_requests",
    )
    pickup_scheduled_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")
    stripe_refund_id = models.CharField(max_length=255, blank=True, default="")
    status_changed_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orders_returnrequest"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["seller", "status"]),
            models.Index(fields=["buyer", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} {self.status} — item {self.order_item_id}"


class ReturnEvent(models.Model):
    """Timeline entry for a ReturnRequest — mirrors OrderActivityLog."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    return_request = models.ForeignKey(
        ReturnRequest, on_delete=models.CASCADE, related_name="events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="return_actions",
    )
    from_status = models.CharField(max_length=24, blank=True, default="")
    to_status = models.CharField(max_length=24)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders_returnevent"
        ordering = ["created_at"]


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
