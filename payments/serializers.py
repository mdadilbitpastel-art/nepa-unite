from __future__ import annotations

from rest_framework import serializers

from payments.models import Invoice, Payment


class PaymentIntentRequestSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()


class DisburseRequestSerializer(serializers.Serializer):
    order_item_id = serializers.UUIDField()


class SellerOnboardSerializer(serializers.Serializer):
    """No body required — the request user is the seller being onboarded."""


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            "id", "order", "stripe_payment_intent_id", "amount",
            "platform_fee", "status", "disbursed_at", "created_at",
        )
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = (
            "id", "order", "invoice_number", "s3_key",
            "pre_signed_url", "pre_signed_url_expires_at", "created_at",
        )
        read_only_fields = fields
