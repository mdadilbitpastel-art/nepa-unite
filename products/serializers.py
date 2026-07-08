from __future__ import annotations

from decimal import Decimal

import bleach
from django.db.models import Avg
from rest_framework import serializers

from products.models import Product, ProductImage, ProductReview, WishlistItem


class RatingFieldsMixin:
    """Adds `rating_avg` / `review_count` to a product serializer.

    Reads the `_rating_avg` / `_review_count` annotations set by
    ProductViewSet.get_queryset() when present (no extra queries); falls
    back to a per-object aggregate for ad-hoc serialization (e.g. the
    response returned straight after create()).
    """

    def get_rating_avg(self, obj) -> float:
        val = getattr(obj, "_rating_avg", None)
        if val is None:
            val = obj.reviews.aggregate(a=Avg("rating"))["a"]
        return round(float(val), 1) if val else 0.0

    def get_review_count(self, obj) -> int:
        val = getattr(obj, "_review_count", None)
        if val is None:
            val = obj.reviews.count()
        return int(val or 0)


class ProductSerializer(RatingFieldsMixin, serializers.ModelSerializer):
    primary_image_url = serializers.SerializerMethodField()
    rating_avg = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id", "tenant", "seller", "sku", "name", "description",
            "price", "mrp", "attributes", "inventory_count", "min_order_qty",
            "is_returnable", "return_window_days", "is_exchangeable",
            "return_policy_note",
            "status", "primary_image_url", "rating_avg", "review_count",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant", "seller", "status",
                            "primary_image_url", "rating_avg", "review_count",
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

    def validate_mrp(self, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise serializers.ValidationError("MRP must be greater than zero.")
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
        # MRP, when given, must be at least the selling price — otherwise the
        # storefront would render a negative discount.
        mrp = attrs.get("mrp", getattr(self.instance, "mrp", None))
        price = attrs.get("price", getattr(self.instance, "price", None))
        if mrp is not None and price is not None and mrp < price:
            raise serializers.ValidationError(
                {"mrp": "MRP cannot be lower than the selling price."}
            )
        return attrs


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ("id", "image_url", "is_primary", "created_at")
        read_only_fields = ("id", "created_at")


class ProductDetailSerializer(RatingFieldsMixin, serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    primary_image_url = serializers.SerializerMethodField()
    rating_avg = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    seller_logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id", "tenant", "seller", "sku", "name", "description",
            "price", "mrp", "attributes", "inventory_count", "min_order_qty",
            "status", "primary_image_url", "images",
            "rating_avg", "review_count",
            "seller_name", "seller_logo_url",
            "is_returnable", "return_window_days", "is_exchangeable",
            "return_policy_note",
            "created_at", "updated_at",
        )

    def get_primary_image_url(self, obj) -> str | None:
        if not obj.primary_image:
            return None
        request = self.context.get("request")
        url = obj.primary_image.url
        return request.build_absolute_uri(url) if request else url

    def get_seller_name(self, obj) -> str | None:
        """Storefront/business name — the tenant the product belongs to."""
        return obj.tenant.name if obj.tenant_id else None

    def get_seller_logo_url(self, obj) -> str | None:
        logo = obj.tenant.logo if obj.tenant_id else None
        if not logo:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(logo.url) if request else logo.url


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


class WishlistItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_price = serializers.DecimalField(
        source="product.price", read_only=True, max_digits=10, decimal_places=2
    )
    product_image_url = serializers.SerializerMethodField()

    class Meta:
        model = WishlistItem
        fields = ("id", "product", "product_name", "product_price",
                  "product_image_url", "created_at")
        read_only_fields = ("id", "created_at")

    def get_product_image_url(self, obj) -> str | None:
        if not obj.product.primary_image:
            return None
        req = self.context.get("request")
        url = obj.product.primary_image.url
        return req.build_absolute_uri(url) if req else url


class ProductReviewSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = ProductReview
        fields = ("id", "product", "user", "user_email", "rating",
                  "title", "body", "created_at", "updated_at")
        read_only_fields = ("id", "user", "user_email", "created_at", "updated_at")

    def validate_rating(self, value: int) -> int:
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value


class ProductSearchQuerySerializer(serializers.Serializer):
    SORT_CHOICES = (
        "relevance", "price_asc", "price_desc",
        "rating_desc", "newest", "discount_desc",
    )

    q = serializers.CharField(required=False, allow_blank=True, default="")
    category = serializers.CharField(required=False, allow_blank=True, default="")
    region = serializers.CharField(required=False, allow_blank=True, default="")
    brand = serializers.CharField(required=False, allow_blank=True, default="")
    price_min = serializers.FloatField(required=False, allow_null=True)
    price_max = serializers.FloatField(required=False, allow_null=True)
    min_rating = serializers.FloatField(
        required=False, allow_null=True, min_value=0, max_value=5
    )
    contract_status = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    in_stock = serializers.BooleanField(required=False, default=None,
                                        allow_null=True)
    sort = serializers.ChoiceField(
        choices=SORT_CHOICES, required=False, default="relevance"
    )
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(
        required=False, default=20, min_value=1, max_value=100
    )

    def to_internal_value(self, data):
        result = super().to_internal_value(data)
        # Coerce empty strings to None so the search service can skip them.
        for key in ("q", "category", "region", "brand", "contract_status"):
            if result.get(key) == "":
                result[key] = None
        return result
