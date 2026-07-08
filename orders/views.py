from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.shortcuts import get_object_or_404

from orders.models import Cart, CartItem, Order, OrderItem, ReturnRequest
from orders.serializers import (
    CartAddSerializer,
    CartCheckoutSerializer,
    CartItemSerializer,
    CartSerializer,
    CartUpdateSerializer,
    OrderCreateSerializer,
    OrderSerializer,
    OrderStatusUpdateSerializer,
    ReturnCreateSerializer,
    ReturnRequestSerializer,
    ReturnStatusUpdateSerializer,
)
from orders.services import (
    OrderCreationError,
    create_order,
    transition_order,
)
from orders.returns_service import (
    close_order_if_window_expired,
    create_return,
    transition_return,
)
from orders.returns_state import InvalidReturnTransitionError
from orders.state import InvalidTransitionError
from products.models import Product
from users.models import BuyerAddress, CustomUser
from users.permissions import IsBuyer


class OrderViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Order.objects.all().prefetch_related(
        "items", "items__product", "items__seller__tenant",
        "items__returns", "returns",
    )
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
        vd = serializer.validated_data
        shipping = {k: vd[k] for k in vd if k.startswith("shipping_") or k == "buyer_notes"}
        try:
            order = create_order(
                buyer=request.user,
                items=vd["items"],
                shipping=shipping,
            )
        except OrderCreationError as exc:
            raise ValidationError(str(exc))
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # GET /api/v1/orders  — sellers see only their own line items
    # ------------------------------------------------------------------
    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = OrderSerializer(
            qs, many=True, context=self.get_serializer_context()
        ).data
        if request.user.role == CustomUser.Role.SELLER:
            sid = str(request.user.pk)
            for order in data:
                order["items"] = [
                    item for item in order["items"]
                    if str(item["seller"]) == sid
                ]
        return Response(data)

    # ------------------------------------------------------------------
    # GET /api/v1/orders/{id}
    # ------------------------------------------------------------------
    def retrieve(self, request, *args, **kwargs):
        order = self.get_object()
        # Auto-close the order the first time it's viewed after the return
        # window elapses, so the return/exchange option disappears on time.
        if close_order_if_window_expired(order, actor=request.user):
            order.refresh_from_db()
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


# ---------------------------------------------------------------------------
# /api/v1/cart  — persistent buyer cart
# ---------------------------------------------------------------------------
class CartViewSet(viewsets.ViewSet):
    """Buyer's persistent cart.

    GET    /api/v1/cart/                       → current cart
    POST   /api/v1/cart/items/                 → add item {product_id, quantity}
    PATCH  /api/v1/cart/items/{item_id}/       → update quantity
    DELETE /api/v1/cart/items/{item_id}/       → remove item
    POST   /api/v1/cart/clear/                 → empty cart
    POST   /api/v1/cart/checkout/              → convert cart → Order
    """

    permission_classes = [IsAuthenticated, IsBuyer]

    def _get_cart(self, user) -> Cart:
        cart, _ = Cart.objects.get_or_create(user=user)
        return cart

    def list(self, request):
        cart = self._get_cart(request.user)
        return Response(CartSerializer(cart, context={"request": request}).data)

    @action(detail=False, methods=["post"], url_path="items")
    def add_item(self, request):
        serializer = CartAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pid = serializer.validated_data["product_id"]
        qty = serializer.validated_data["quantity"]
        product = get_object_or_404(Product, pk=pid)
        if product.status != Product.Status.ACTIVE:
            return Response({"detail": "Product not available."},
                            status=status.HTTP_400_BAD_REQUEST)
        cart = self._get_cart(request.user)
        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product, defaults={"quantity": qty},
        )
        if not created:
            item.quantity = item.quantity + qty
            item.save(update_fields=["quantity", "updated_at"])
        return Response(
            CartSerializer(cart, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=False, methods=["patch", "delete"],
            url_path=r"items/(?P<item_id>[^/.]+)")
    def modify_item(self, request, item_id=None):
        cart = self._get_cart(request.user)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)
        if request.method == "DELETE":
            item.delete()
            return Response(CartSerializer(cart, context={"request": request}).data)
        serializer = CartUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item.quantity = serializer.validated_data["quantity"]
        item.save(update_fields=["quantity", "updated_at"])
        return Response(CartSerializer(cart, context={"request": request}).data)

    @action(detail=False, methods=["post"], url_path="clear")
    def clear(self, request):
        cart = self._get_cart(request.user)
        cart.items.all().delete()
        return Response(CartSerializer(cart, context={"request": request}).data)

    @action(detail=False, methods=["post"], url_path="checkout")
    def checkout(self, request):
        serializer = CartCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        cart = self._get_cart(request.user)
        if not cart.items.exists():
            return Response({"detail": "Cart is empty."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Resolve shipping: either a saved address_id or inline fields.
        shipping: dict = {}
        if vd.get("address_id"):
            addr = get_object_or_404(
                BuyerAddress, pk=vd["address_id"], user=request.user
            )
            shipping = {
                "shipping_name": addr.recipient_name,
                "shipping_phone": addr.phone,
                "shipping_address_line1": addr.line1,
                "shipping_address_line2": addr.line2,
                "shipping_city": addr.city,
                "shipping_state": addr.state,
                "shipping_zip": addr.zip_code,
                "buyer_notes": vd.get("buyer_notes", ""),
            }
        else:
            shipping = {k: vd.get(k, "") for k in (
                "shipping_name", "shipping_phone",
                "shipping_address_line1", "shipping_address_line2",
                "shipping_city", "shipping_state", "shipping_zip",
                "buyer_notes",
            )}

        items = [
            {"product_id": str(i.product_id), "quantity": i.quantity}
            for i in cart.items.all()
        ]
        try:
            order = create_order(buyer=request.user, items=items, shipping=shipping)
        except OrderCreationError as exc:
            raise ValidationError(str(exc))
        cart.items.all().delete()
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class ReturnViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Buyer-raised returns/exchanges, seller-managed with admin override.

    GET /api/v1/returns/            list (role-scoped)
    POST /api/v1/returns/           buyer opens a return/exchange
    GET /api/v1/returns/{id}/       detail + timeline events
    PATCH /api/v1/returns/{id}/status  advance the lifecycle
    """

    queryset = (
        ReturnRequest.objects.all()
        .select_related(
            "order", "order_item", "order_item__product", "buyer",
            "seller", "seller__tenant",
        )
        .prefetch_related("events")
    )
    serializer_class = ReturnRequestSerializer
    permission_classes = [IsAuthenticated]

    # Target statuses each role is allowed to drive.
    _SELLER_ACTIONS = {
        ReturnRequest.Status.APPROVED,
        ReturnRequest.Status.REJECTED,
        ReturnRequest.Status.PICKUP_SCHEDULED,
        ReturnRequest.Status.PICKED_UP,
        ReturnRequest.Status.RECEIVED,
        ReturnRequest.Status.REFUNDED,
        ReturnRequest.Status.EXCHANGE_SHIPPED,
        ReturnRequest.Status.EXCHANGE_COMPLETED,
    }
    _BUYER_ACTIONS = {ReturnRequest.Status.CANCELLED}

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == CustomUser.Role.ADMIN:
            return qs
        if user.role == CustomUser.Role.BUYER:
            return qs.filter(buyer=user)
        if user.role == CustomUser.Role.SELLER:
            return qs.filter(seller=user)
        return qs.none()

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsBuyer()]
        return [IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        ser = ReturnCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        item = get_object_or_404(OrderItem, pk=data["order_item"])
        exchange_product = None
        if data.get("exchange_product"):
            exchange_product = get_object_or_404(
                Product, pk=data["exchange_product"]
            )
        rr = create_return(
            buyer=request.user,
            order_item=item,
            type=data["type"],
            reason=data["reason"],
            reason_note=data.get("reason_note", ""),
            quantity=data.get("quantity", 1),
            exchange_product=exchange_product,
        )
        out = ReturnRequestSerializer(rr, context={"request": request})
        return Response(out.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path="status")
    def change_status(self, request, pk=None):
        rr = self.get_object()  # role-scoped by get_queryset
        ser = ReturnStatusUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        target = ser.validated_data["status"]
        self._authorize_transition(request.user, rr, target)
        try:
            rr = transition_return(
                return_request=rr,
                target_status=target,
                actor=request.user,
                note=ser.validated_data.get("note", ""),
                pickup_scheduled_at=ser.validated_data.get("pickup_scheduled_at"),
            )
        except InvalidReturnTransitionError as exc:
            raise ValidationError(str(exc))
        out = ReturnRequestSerializer(rr, context={"request": request})
        return Response(out.data)

    def _authorize_transition(self, user, rr, target) -> None:
        role = user.role
        if role == CustomUser.Role.ADMIN:
            return
        if role == CustomUser.Role.SELLER:
            if rr.seller_id != user.pk:
                raise PermissionDenied("Not your return to manage.")
            if target not in self._SELLER_ACTIONS:
                raise PermissionDenied("Sellers cannot set that status.")
            return
        if role == CustomUser.Role.BUYER:
            if rr.buyer_id != user.pk:
                raise PermissionDenied("Not your return.")
            if target not in self._BUYER_ACTIONS:
                raise PermissionDenied("Buyers can only cancel a return.")
            return
        raise PermissionDenied("Not allowed.")
