from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from commissions import services
from commissions.models import Commission, CommissionRate
from commissions.serializers import CommissionRateSerializer, CommissionSerializer
from users.permissions import IsAdmin


class CommissionListView(APIView):
    """GET /api/v1/commissions/ — admin ledger, newest first.

    Optional filters: ``?status=earned`` and ``?seller=<uuid>``.
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = Commission.objects.select_related("seller").all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        seller_id = request.query_params.get("seller")
        if seller_id:
            qs = qs.filter(seller_id=seller_id)
        return Response(CommissionSerializer(qs, many=True).data)


class CommissionSummaryView(APIView):
    """GET /api/v1/commissions/summary/ — totals per status for admin earnings."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        qs = Commission.objects.all()
        seller_id = request.query_params.get("seller")
        if seller_id:
            qs = qs.filter(seller_id=seller_id)
        return Response(services.summary(qs))


class CommissionRateListCreateView(APIView):
    """GET/POST /api/v1/commissions/rates/ — manage the category fee schedule."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        rates = CommissionRate.objects.all()
        return Response(CommissionRateSerializer(rates, many=True).data)

    def post(self, request):
        serializer = CommissionRateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CommissionRateDetailView(APIView):
    """PUT/PATCH/DELETE /api/v1/commissions/rates/<id>/ — edit one rate."""

    permission_classes = [IsAuthenticated, IsAdmin]

    def put(self, request, pk):
        rate = get_object_or_404(CommissionRate, pk=pk)
        serializer = CommissionRateSerializer(rate, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    patch = put

    def delete(self, request, pk):
        rate = get_object_or_404(CommissionRate, pk=pk)
        rate.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
