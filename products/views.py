from __future__ import annotations

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from django.db.models import Avg, Count

from core.models import Job
from products.categories import INDUSTRY_CATEGORIES
from products.models import Product, ProductReview, WishlistItem
from products.serializers import (
    BulkUploadSerializer,
    ProductDetailSerializer,
    ProductReviewSerializer,
    ProductSearchQuerySerializer,
    ProductSerializer,
    WishlistItemSerializer,
)
from products.services import contract_price_for_buyer, search_products
from products.tasks import (
    process_bulk_upload,
    reindex_product,
    remove_product_from_index,
)
from users.models import CustomUser
from users.permissions import IsBuyer, IsSeller


class ProductViewSet(viewsets.ModelViewSet):
    """All product operations.

    - create/update/partial_update/destroy: seller-only, owner-only
    - retrieve: public; authenticated buyers additionally get contract pricing
    - bulk_upload: seller-only, returns a job_id
    - search: public
    """

    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        # Annotate aggregate rating so list/retrieve responses can expose
        # rating_avg / review_count without a per-object query (N+1).
        return Product.objects.annotate(
            _rating_avg=Avg("reviews__rating"),
            _review_count=Count("reviews", distinct=True),
        )

    def get_permissions(self):
        if self.action in ("search", "categories", "brands", "by_seller", "retrieve"):
            # Public storefront: anyone may browse a product detail page.
            # retrieve() already guards contract pricing behind is_authenticated.
            return [AllowAny()]
        if self.action == "reviews":
            # GET is public; POST requires an authed buyer (enforced inside).
            if self.request.method == "GET":
                return [AllowAny()]
            return [IsAuthenticated()]
        if self.action in ("create", "update", "partial_update", "destroy", "bulk_upload"):
            return [IsAuthenticated(), IsSeller()]
        return [IsAuthenticated()]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @staticmethod
    def _stripe_gate(user) -> Response | None:
        """Block sellers who haven't finished Stripe Connect onboarding.

        Returning a Response signals the caller to short-circuit. We do this
        on every listing-creation path so a seller can never publish a
        product they can't actually receive payouts for. Disabled in dev
        until Stripe Connect is provisioned (see settings.STRIPE_GATE_ENABLED).
        """
        if not settings.STRIPE_GATE_ENABLED:
            return None
        if user.role == CustomUser.Role.SELLER and not user.stripe_account_id:
            return Response(
                {
                    "detail": (
                        "Complete Stripe Connect onboarding before listing "
                        "products. POST /api/v1/sellers/onboard to start."
                    ),
                    "code": "stripe_onboarding_required",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def create(self, request, *args, **kwargs):
        if request.user.tenant_id is None:
            return Response(
                {"detail": "User is not attached to a tenant."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        gate = self._stripe_gate(request.user)
        if gate is not None:
            return gate
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save(
            tenant_id=request.user.tenant_id,
            seller=request.user,
        )
        reindex_product.delay(str(product.pk))
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)

    def _check_seller_owns(self, product: Product, user) -> None:
        if product.seller_id != user.pk:
            raise PermissionDenied("Only the owning seller may modify this product.")

    def update(self, request, *args, **kwargs):
        product = self.get_object()
        self._check_seller_owns(product, request.user)
        serializer = self.get_serializer(product, data=request.data, partial=False)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        reindex_product.delay(str(product.pk))
        return Response(ProductSerializer(product).data)

    def partial_update(self, request, *args, **kwargs):
        product = self.get_object()
        self._check_seller_owns(product, request.user)
        serializer = self.get_serializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        reindex_product.delay(str(product.pk))
        return Response(ProductSerializer(product).data)

    def destroy(self, request, *args, **kwargs):
        """Soft delete — never remove from PG."""
        product = self.get_object()
        self._check_seller_owns(product, request.user)
        if product.status == Product.Status.DELETED:
            return Response(status=status.HTTP_204_NO_CONTENT)
        product.status = Product.Status.DELETED
        product.save(update_fields=["status", "updated_at"])
        remove_product_from_index.delay(str(product.pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def retrieve(self, request, *args, **kwargs):
        product = self.get_object()
        data = ProductDetailSerializer(product).data
        if (
            request.user
            and request.user.is_authenticated
            and request.user.role == CustomUser.Role.BUYER
        ):
            contract_price = contract_price_for_buyer(product, request.user)
            if contract_price is not None:
                data["contract_price"] = str(contract_price)
        return Response(data)

    # ------------------------------------------------------------------
    # POST /api/v1/products/bulk-upload
    # ------------------------------------------------------------------
    @action(
        detail=False,
        methods=["post"],
        url_path="bulk-upload",
        parser_classes=[MultiPartParser, FormParser],
    )
    def bulk_upload(self, request):
        gate = self._stripe_gate(request.user)
        if gate is not None:
            return gate
        serializer = BulkUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        csv_file = serializer.validated_data["file"]
        try:
            csv_text = csv_file.read().decode("utf-8")
        except UnicodeDecodeError:
            return Response(
                {"detail": "CSV file must be UTF-8 encoded."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = Job.objects.create(kind="products.bulk_upload", owner=request.user)
        process_bulk_upload.delay(str(job.pk), csv_text)
        return Response(
            {"job_id": str(job.pk), "status": job.status},
            status=status.HTTP_202_ACCEPTED,
        )

    # ------------------------------------------------------------------
    # GET /api/v1/products/search  (public)
    # ------------------------------------------------------------------
    @action(detail=False, methods=["get"], permission_classes=[AllowAny],
            authentication_classes=[])
    def search(self, request):
        serializer = ProductSearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        result = search_products(**params)
        return Response({
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "items": result.items,
            "facets": result.facets,
            "used_fallback": result.used_fallback,
        })

    # ------------------------------------------------------------------
    # GET /api/v1/products/categories  (public)
    # Distinct categories derived from products.attributes->>'category'.
    # ------------------------------------------------------------------
    @action(detail=False, methods=["get"], permission_classes=[AllowAny],
            authentication_classes=[])
    def categories(self, request):
        rows = (
            Product.objects.filter(status=Product.Status.ACTIVE)
            .exclude(attributes__category__isnull=True)
            .exclude(attributes__category="")
            .values_list("attributes__category", flat=True)
        )
        counts: dict[str, int] = {}
        for c in rows:
            if not c:
                continue
            counts[c] = counts.get(c, 0) + 1

        # Full predefined catalog from products/categories.py, plus any ad-hoc
        # categories that exist on products but aren't in the predefined list.
        names: set[str] = set(counts)
        for cats in INDUSTRY_CATEGORIES.values():
            names.update(cats)

        items = []
        for name in sorted(names):
            item: dict = {"name": name}
            if counts.get(name):
                item["product_count"] = counts[name]
            items.append(item)
        return Response({"items": items})

    # ------------------------------------------------------------------
    # GET /api/v1/products/brands  (public)
    # Distinct brands derived from products.attributes->>'brand'.
    # ------------------------------------------------------------------
    @action(detail=False, methods=["get"], permission_classes=[AllowAny],
            authentication_classes=[])
    def brands(self, request):
        rows = (
            Product.objects.filter(status=Product.Status.ACTIVE)
            .exclude(attributes__brand__isnull=True)
            .exclude(attributes__brand="")
            .values_list("attributes__brand", flat=True)
        )
        counts: dict[str, int] = {}
        for b in rows:
            if not b:
                continue
            counts[b] = counts.get(b, 0) + 1
        items = [
            {"name": name, "product_count": counts[name]}
            for name in sorted(counts)
        ]
        return Response({"items": items})

    # ------------------------------------------------------------------
    # GET /api/v1/products/by-seller/{seller_id}  (public storefront)
    # ------------------------------------------------------------------
    @action(detail=False, methods=["get"], url_path=r"by-seller/(?P<seller_id>[^/.]+)",
            permission_classes=[AllowAny], authentication_classes=[])
    def by_seller(self, request, seller_id=None):
        qs = (
            Product.objects.filter(seller_id=seller_id, status=Product.Status.ACTIVE)
            .order_by("-created_at")
        )
        page = int(request.query_params.get("page", 1))
        page_size = min(int(request.query_params.get("page_size", 20)), 100)
        total = qs.count()
        start = (page - 1) * page_size
        items = ProductSerializer(
            qs[start:start + page_size], many=True, context={"request": request}
        ).data
        return Response({
            "total": total, "page": page, "page_size": page_size, "items": items,
        })

    # ------------------------------------------------------------------
    # GET /api/v1/products/{id}/reviews  (public)
    # POST /api/v1/products/{id}/reviews  (buyer)
    # ------------------------------------------------------------------
    @action(detail=True, methods=["get", "post"], url_path="reviews",
            permission_classes=[AllowAny])
    def reviews(self, request, pk=None):
        product = self.get_object()
        if request.method == "POST":
            if not (request.user and request.user.is_authenticated):
                return Response(
                    {"detail": "Authentication required."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if request.user.role != CustomUser.Role.BUYER:
                return Response(
                    {"detail": "Only buyers can write reviews."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            serializer = ProductReviewSerializer(
                data={**request.data, "product": str(product.pk)}
            )
            serializer.is_valid(raise_exception=True)
            try:
                review = serializer.save(user=request.user, product=product)
            except Exception:  # IntegrityError on unique constraint
                return Response(
                    {"detail": "You've already reviewed this product."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                ProductReviewSerializer(review).data,
                status=status.HTTP_201_CREATED,
            )
        # GET
        qs = product.reviews.select_related("user").all()
        agg = qs.aggregate(avg=Avg("rating"), count=Count("id"))
        return Response({
            "average_rating": round(agg["avg"] or 0, 2),
            "count": agg["count"],
            "items": ProductReviewSerializer(qs, many=True).data,
        })


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}  (used by bulk-upload polling)
# ---------------------------------------------------------------------------
class WishlistViewSet(viewsets.ModelViewSet):
    """Buyer's wishlist — add / list / remove favorited products."""

    serializer_class = WishlistItemSerializer
    permission_classes = [IsAuthenticated, IsBuyer]
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        return (
            WishlistItem.objects.filter(user=self.request.user)
            .select_related("product")
        )

    def create(self, request, *args, **kwargs):
        product_id = request.data.get("product")
        if not product_id:
            return Response(
                {"detail": "product is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not Product.objects.filter(pk=product_id).exists():
            return Response(
                {"detail": "Product not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        item, created = WishlistItem.objects.get_or_create(
            user=request.user, product_id=product_id
        )
        return Response(
            WishlistItemSerializer(item, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ProductReviewViewSet(
    viewsets.GenericViewSet,
):
    """Buyer manages their own reviews (update / delete)."""

    serializer_class = ProductReviewSerializer
    permission_classes = [IsAuthenticated, IsBuyer]
    queryset = ProductReview.objects.all()

    def partial_update(self, request, pk=None):
        review = self.get_object()
        if review.user_id != request.user.pk:
            raise PermissionDenied("Can only edit your own review.")
        serializer = self.get_serializer(review, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductReviewSerializer(review).data)

    def destroy(self, request, pk=None):
        review = self.get_object()
        if review.user_id != request.user.pk:
            raise PermissionDenied("Can only delete your own review.")
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({"detail": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
        # Only the owner or an admin can poll.
        if job.owner_id != request.user.pk and request.user.role != CustomUser.Role.ADMIN:
            raise PermissionDenied()
        return Response({
            "id": str(job.pk),
            "kind": job.kind,
            "status": job.status,
            "total": job.total,
            "succeeded": job.succeeded,
            "failed": job.failed,
            "errors": job.errors,
            "result": job.result,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        })
