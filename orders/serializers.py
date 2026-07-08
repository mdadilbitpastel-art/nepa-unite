from __future__ import annotations

from rest_framework import serializers

from orders.models import (
    Cart,
    CartItem,
    Order,
    OrderItem,
    ReturnEvent,
    ReturnRequest,
)


class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    seller_name = serializers.SerializerMethodField()
    # Return/exchange policy + live eligibility, so the order page can render
    # a "Return item" button only when the window is genuinely open.
    is_returnable = serializers.BooleanField(
        source="product.is_returnable", read_only=True
    )
    is_exchangeable = serializers.BooleanField(
        source="product.is_exchangeable", read_only=True
    )
    return_window_days = serializers.IntegerField(
        source="product.return_window_days", read_only=True
    )
    return_eligible = serializers.SerializerMethodField()
    active_return = serializers.SerializerMethodField()
    # Every return/exchange ever raised on this item (newest first) so the order
    # page can show the full history — how many times, and each outcome.
    return_history = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "id", "product", "product_name", "seller", "seller_name",
            "quantity", "unit_price", "fulfillment_status",
            "is_returnable", "is_exchangeable", "return_window_days",
            "return_eligible", "active_return", "return_history",
        )
        read_only_fields = fields

    def get_seller_name(self, obj) -> str | None:
        """Storefront/business name for the item's seller."""
        tenant = getattr(obj.seller, "tenant", None)
        return tenant.name if tenant else None

    def get_return_eligible(self, obj) -> bool:
        from orders.returns_service import item_return_eligible
        return item_return_eligible(obj)

    def get_active_return(self, obj) -> dict | None:
        # ReturnRequest.Meta orders newest-first, so the prefetched list's first
        # element is the latest — reuse it instead of re-querying per item.
        returns = list(obj.returns.all())
        if not returns:
            return None
        rr = returns[0]
        return {
            "id": str(rr.id),
            "type": rr.type,
            "status": rr.status,
            "status_display": rr.get_status_display(),
        }

    def get_return_history(self, obj) -> list:
        # Newest-first (Meta-ordered), prefetched — full record of every
        # return/exchange raised on the item and how each one ended up.
        return [
            {
                "id": str(r.id),
                "type": r.type,
                "status": r.status,
                "status_display": r.get_status_display(),
                "refund_amount": str(r.refund_amount),
                "created_at": r.created_at.isoformat(),
            }
            for r in obj.returns.all()
        ]


class OrderItemInputSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(serializers.Serializer):
    items = OrderItemInputSerializer(many=True, allow_empty=False)
    shipping_name = serializers.CharField(max_length=255)
    shipping_phone = serializers.CharField(max_length=20)
    shipping_address_line1 = serializers.CharField(max_length=255)
    shipping_address_line2 = serializers.CharField(max_length=255, required=False, default="")
    shipping_city = serializers.CharField(max_length=100)
    shipping_state = serializers.CharField(max_length=50)
    shipping_zip = serializers.CharField(max_length=20)
    buyer_notes = serializers.CharField(required=False, default="")


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    # Human label for the raw order status (e.g. "Delivered").
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    # True only while the order can still be cancelled — i.e. before it is
    # delivered. Drives whether the "Cancel order" action renders. Mirrors the
    # order state machine, so the button and the API agree.
    can_cancel = serializers.SerializerMethodField()
    # The single badge an order-list row should show. Before delivery it is the
    # order status; once delivered/closed and a return/exchange is in progress,
    # it surfaces that (e.g. "Pickup scheduled", "Refunded") instead.
    display_status = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id", "buyer", "tenant", "status", "status_display", "can_cancel",
            "display_status", "total_amount",
            "shipping_name", "shipping_phone",
            "shipping_address_line1", "shipping_address_line2",
            "shipping_city", "shipping_state", "shipping_zip",
            "buyer_notes", "stripe_payment_intent_id",
            "items", "delivered_at", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_can_cancel(self, obj) -> bool:
        from orders.state import can_transition
        return can_transition(obj.status, Order.Status.CANCELLED)

    def get_display_status(self, obj) -> dict:
        from orders.returns_service import order_effective_status
        return order_effective_status(obj)


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)


class ReturnEventSerializer(serializers.ModelSerializer):
    actor_role = serializers.SerializerMethodField()

    class Meta:
        model = ReturnEvent
        fields = (
            "id", "from_status", "to_status", "note", "actor_role", "created_at",
        )
        read_only_fields = fields

    def get_actor_role(self, obj) -> str:
        return getattr(obj.actor, "role", "") or ""


class ReturnRequestSerializer(serializers.ModelSerializer):
    product = serializers.UUIDField(source="order_item.product_id", read_only=True)
    product_name = serializers.CharField(
        source="order_item.product.name", read_only=True
    )
    product_image_url = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    events = ReturnEventSerializer(many=True, read_only=True)

    class Meta:
        model = ReturnRequest
        fields = (
            "id", "order", "order_item", "product", "product_name",
            "product_image_url", "buyer", "seller", "seller_name",
            "type", "status", "status_display", "reason", "reason_note",
            "quantity", "refund_amount", "exchange_product",
            "pickup_scheduled_at", "resolution_note", "stripe_refund_id",
            "events", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_seller_name(self, obj) -> str | None:
        tenant = getattr(obj.seller, "tenant", None)
        return tenant.name if tenant else None

    def get_product_image_url(self, obj) -> str | None:
        img = obj.order_item.product.primary_image
        if not img:
            return None
        req = self.context.get("request")
        return req.build_absolute_uri(img.url) if req else img.url


class ReturnCreateSerializer(serializers.Serializer):
    order_item = serializers.UUIDField()
    type = serializers.ChoiceField(
        choices=ReturnRequest.Type.choices, default=ReturnRequest.Type.RETURN
    )
    reason = serializers.ChoiceField(choices=ReturnRequest.Reason.choices)
    reason_note = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1, default=1)
    exchange_product = serializers.UUIDField(required=False, allow_null=True)


class ReturnStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReturnRequest.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    pickup_scheduled_at = serializers.DateTimeField(
        required=False, allow_null=True
    )


class CartItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_min_order_qty = serializers.IntegerField(
        source="product.min_order_qty", read_only=True
    )
    unit_price = serializers.DecimalField(
        source="product.price", read_only=True, max_digits=10, decimal_places=2
    )
    line_total = serializers.SerializerMethodField()
    product_image_url = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = (
            "id", "product", "product_name", "product_sku",
            "product_min_order_qty", "product_image_url", "quantity",
            "unit_price", "line_total", "updated_at",
        )
        read_only_fields = (
            "id", "product_name", "product_sku", "product_min_order_qty",
            "product_image_url", "unit_price", "line_total", "updated_at",
        )

    def get_line_total(self, obj) -> str:
        return str(obj.product.price * obj.quantity)

    def get_product_image_url(self, obj) -> str | None:
        if not obj.product.primary_image:
            return None
        req = self.context.get("request")
        url = obj.product.primary_image.url
        return req.build_absolute_uri(url) if req else url


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ("id", "items", "total", "item_count", "updated_at")
        read_only_fields = fields

    def get_total(self, obj) -> str:
        total = sum((i.product.price * i.quantity for i in obj.items.all()), start=0)
        return str(total)

    def get_item_count(self, obj) -> int:
        return sum(i.quantity for i in obj.items.all())


class CartAddSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)


class CartUpdateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class CartCheckoutSerializer(serializers.Serializer):
    address_id = serializers.UUIDField(required=False, allow_null=True)
    shipping_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    shipping_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    shipping_address_line1 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    shipping_address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    shipping_city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    shipping_state = serializers.CharField(max_length=50, required=False, allow_blank=True)
    shipping_zip = serializers.CharField(max_length=20, required=False, allow_blank=True)
    buyer_notes = serializers.CharField(required=False, allow_blank=True, default="")
