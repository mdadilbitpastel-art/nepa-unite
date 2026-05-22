from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from orders.models import Order
from orders.serializers import (
    OrderCreateSerializer,
    OrderSerializer,
    OrderStatusUpdateSerializer,
)
from orders.services import (
    OrderCreationError,
    create_order,
    transition_order,
)
from orders.state import InvalidTransitionError
from users.models import CustomUser
from users.permissions import IsBuyer


class OrderViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Order.objects.all().prefetch_related("items")
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    # ------------------------------------------------------------------
    # Role-scoped queryset (used by list and retrieve).
    # ------------------------------------------------------------------
    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == CustomUser.Role.ADMIN:
            return qs
        if user.role == CustomUser.Role.BUYER:
            return qs.filter(buyer=user)
        if user.role == CustomUser.Role.SELLER:
            return qs.filter(items__seller=user).distinct()
        return qs.none()

    def filter_queryset(self, queryset):
        params = self.request.query_params
        status_value = params.get("status")
        date_from = params.get("date_from")
        date_to = params.get("date_to")
        if status_value:
            queryset = queryset.filter(status=status_value)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset.order_by("-created_at")

    # ------------------------------------------------------------------
    # POST /api/v1/orders  (buyer only)
    # ------------------------------------------------------------------
    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsBuyer()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = create_order(
                buyer=request.user,
                items=serializer.validated_data["items"],
            )
        except OrderCreationError as exc:
            raise ValidationError(str(exc))
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # GET /api/v1/orders/{id}
    # ------------------------------------------------------------------
    def retrieve(self, request, *args, **kwargs):
        order = self.get_object()
        data = OrderSerializer(order).data
        if request.user.role == CustomUser.Role.SELLER:
            data["items"] = [
                item for item in data["items"]
                if item["seller"] == str(request.user.pk)
            ]
        return Response(data)

    # ------------------------------------------------------------------
    # PATCH /api/v1/orders/{id}/status
    # ------------------------------------------------------------------
    @action(detail=True, methods=["patch"], url_path="status")
    def change_status(self, request, pk=None):
        order = self.get_object()
        if not self._can_transition(request.user, order):
            raise PermissionDenied("Not allowed to transition this order.")
        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = transition_order(
                order=order,
                target_status=serializer.validated_data["status"],
                actor=request.user,
            )
        except InvalidTransitionError as exc:
            raise ValidationError(str(exc))
        return Response(OrderSerializer(order).data)

    @staticmethod
    def _can_transition(user, order: Order) -> bool:
        if user.role == CustomUser.Role.ADMIN:
            return True
        if user.role == CustomUser.Role.BUYER and order.buyer_id == user.pk:
            return True
        if user.role == CustomUser.Role.SELLER and order.items.filter(seller=user).exists():
            return True
        return False
