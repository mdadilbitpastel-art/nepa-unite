from __future__ import annotations

from rest_framework import serializers

from commissions.models import Commission, CommissionRate


class CommissionSerializer(serializers.ModelSerializer):
    seller_email = serializers.EmailField(source="seller.email", read_only=True)

    class Meta:
        model = Commission
        fields = (
            "id", "order", "order_item", "seller", "seller_email", "category",
            "base_amount", "rate_percent", "commission_amount", "status",
            "earned_at", "reversed_at", "created_at",
        )
        read_only_fields = fields


class CommissionRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionRate
        fields = (
            "id", "category", "percent", "min_fee", "is_active",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
