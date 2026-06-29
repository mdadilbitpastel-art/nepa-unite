from __future__ import annotations

from rest_framework import serializers

from orders.models import Cart, CartItem, Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = (
            "id", "product", "seller", "quantity", "unit_price",
            "fulfillment_status",
        )
        read_only_fields = fields


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

    class Meta:
        model = Order
        fields = (
            "id", "buyer", "tenant", "status", "total_amount",
            "shipping_name", "shipping_phone",
            "shipping_address_line1", "shipping_address_line2",
            "shipping_city", "shipping_state", "shipping_zip",
            "buyer_notes", "stripe_payment_intent_id",
            "items", "created_at", "updated_at",
        )
        read_only_fields = fields


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)


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
