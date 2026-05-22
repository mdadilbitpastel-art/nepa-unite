from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order
from payments import stripe_service
from payments.serializers import (
    DisburseRequestSerializer,
    InvoiceSerializer,
    PaymentIntentRequestSerializer,
    PaymentSerializer,
    SellerOnboardSerializer,
)
from users.models import CustomUser
from users.permissions import IsAdmin, IsBuyer, IsSeller

logger = logging.getLogger(__name__)


class PaymentIntentView(APIView):
    permission_classes = [IsAuthenticated, IsBuyer]

    def post(self, request):
        serializer = PaymentIntentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = get_object_or_404(Order, pk=serializer.validated_data["order_id"])
        if order.buyer_id != request.user.pk:
            raise PermissionDenied("You can only pay for your own orders.")
        result = stripe_service.create_payment_intent(str(order.pk))
        return Response(result, status=status.HTTP_201_CREATED)


class DisburseView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = DisburseRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stripe_service.disburse_to_seller(
            str(serializer.validated_data["order_item_id"])
        )
        return Response(status=status.HTTP_202_ACCEPTED)


class OrderPaymentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        # Role gating: buyer must own; seller must have an item; admin always ok.
        if request.user.role == CustomUser.Role.BUYER and order.buyer_id != request.user.pk:
            raise PermissionDenied()
        if (
            request.user.role == CustomUser.Role.SELLER
            and not order.items.filter(seller=request.user).exists()
        ):
            raise PermissionDenied()
        payments = order.payments.order_by("created_at")
        return Response(PaymentSerializer(payments, many=True).data)


class SellerOnboardView(APIView):
    permission_classes = [IsAuthenticated, IsSeller]

    def post(self, request):
        SellerOnboardSerializer(data=request.data).is_valid(raise_exception=True)
        url = stripe_service.create_seller_account(str(request.user.pk))
        return Response({"onboarding_url": url})


class OrderInvoiceView(APIView):
    """GET /api/v1/orders/{id}/invoice — return a fresh pre-signed URL."""

    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        if request.user.role == CustomUser.Role.BUYER and order.buyer_id != request.user.pk:
            raise PermissionDenied()

        from payments.invoice_service import (
            generate_invoice,
            refresh_pre_signed_url,
        )
        from django.utils import timezone

        invoice = order.invoices.order_by("-created_at").first()
        if invoice is None:
            invoice = generate_invoice(str(order.pk))
        elif (
            invoice.pre_signed_url_expires_at is None
            or invoice.pre_signed_url_expires_at <= timezone.now()
        ):
            refresh_pre_signed_url(invoice)
        return Response(InvoiceSerializer(invoice).data)
