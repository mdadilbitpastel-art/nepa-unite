from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.models import Job
from products.models import Product
from products.serializers import (
    ProductSerializer,
    ProductDetailSerializer,
    BulkUploadSerializer,
    ProductSearchQuerySerializer,
)
from products.services import contract_price_for_buyer, search_products
from products.tasks import (
    process_bulk_upload,
    reindex_product,
    remove_product_from_index,
)
from users.models import CustomUser
from users.permissions import IsSeller


class ProductViewSet(viewsets.ModelViewSet):
    """All product operations.

    - create/update/partial_update/destroy: seller-only, owner-only
    - retrieve: any authenticated role; buyers get contract pricing
    - bulk_upload: seller-only, returns a job_id
    - search: public
    """

    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action == "search":
            return [AllowAny()]
        if self.action in ("create", "update", "partial_update", "destroy", "bulk_upload"):
            return [IsAuthenticated(), IsSeller()]
        return [IsAuthenticated()]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create(self, request, *args, **kwargs):
        if request.user.tenant_id is None:
            return Response(
                {"detail": "User is not attached to a tenant."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}  (used by bulk-upload polling)
# ---------------------------------------------------------------------------
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
