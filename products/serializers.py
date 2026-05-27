from __future__ import annotations

from decimal import Decimal

import bleach
from rest_framework import serializers

from products.models import Product, ProductImage


class ProductSerializer(serializers.ModelSerializer):
    primary_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id", "tenant", "seller", "sku", "name", "description",
            "price", "attributes", "inventory_count", "min_order_qty", "status",
            "primary_image_url",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant", "seller", "status",
                            "primary_image_url",
                            "created_at", "updated_at")

    def get_primary_image_url(self, obj) -> str | None:
        if not obj.primary_image:
            return None
        request = self.context.get("request")
        url = obj.primary_image.url
        return request.build_absolute_uri(url) if request else url

    def validate_price(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value

    def validate_inventory_count(self, value: int) -> int:
        if value < 0:
            raise serializers.ValidationError("Inventory count cannot be negative.")
        return value

    def validate_sku(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("SKU is required.")
        return value.strip()

    def validate_name(self, value: str) -> str:
        return bleach.clean(value, tags=[], strip=True).strip()

    def validate_description(self, value: str) -> str:
        return bleach.clean(value, tags=[], strip=True)

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.method == "POST":
            tenant_id = request.user.tenant_id
            sku = attrs.get("sku")
            if (
                tenant_id and sku
                and Product.objects.filter(tenant_id=tenant_id, sku=sku).exists()
            ):
                raise serializers.ValidationError(
                    {"sku": "A product with this SKU already exists for your tenant."}
                )
        return attrs


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ("id", "image_url", "is_primary", "created_at")
        read_only_fields = ("id", "created_at")


class ProductDetailSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    primary_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id", "tenant", "seller", "sku", "name", "description",
            "price", "attributes", "inventory_count", "min_order_qty", "status",
            "primary_image_url", "images",
            "created_at", "updated_at",
        )

    def get_primary_image_url(self, obj) -> str | None:
        if not obj.primary_image:
            return None
        request = self.context.get("request")
        url = obj.primary_image.url
        return request.build_absolute_uri(url) if request else url


class BulkUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        name = (getattr(value, "name", "") or "").lower()
        if not name.endswith(".csv"):
            raise serializers.ValidationError("File must be a .csv")
        # 10 MB ceiling — bigger uploads should use a presigned-S3 flow.
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("File exceeds 10 MB limit")
        return value


class ProductSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.CharField(required=False, allow_blank=True, default="")
    region = serializers.CharField(required=False, allow_blank=True, default="")
    price_min = serializers.FloatField(required=False, allow_null=True)
    price_max = serializers.FloatField(required=False, allow_null=True)
    contract_status = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    in_stock = serializers.BooleanField(required=False, default=None,
                                        allow_null=True)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(
        required=False, default=20, min_value=1, max_value=100
    )

    def to_internal_value(self, data):
        result = super().to_internal_value(data)
        # Coerce empty strings to None so the search service can skip them.
        for key in ("q", "category", "region", "contract_status"):
            if result.get(key) == "":
                result[key] = None
        return result
