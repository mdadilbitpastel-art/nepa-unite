from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Product(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "users.Tenant",
        on_delete=models.PROTECT,
        related_name="products",
        db_column="tenant_id",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="products",
    )
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    attributes = models.JSONField(default=dict, blank=True)
    inventory_count = models.IntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "sku"], name="uniq_product_sku_per_tenant"
            ),
            models.CheckConstraint(
                check=models.Q(inventory_count__gte=0),
                name="product_inventory_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sku} — {self.name}"

    # ------------------------------------------------------------------
    # Computed values exposed to the Elasticsearch document.
    # `attributes` is a flexible JSON blob whose shape varies per vertical;
    # the marketplace needs a stable set of facets to filter against.
    # ------------------------------------------------------------------
    @property
    def category_value(self) -> str:
        return (self.attributes or {}).get("category", "")

    @property
    def region_value(self) -> str:
        return (self.attributes or {}).get("region", "")

    @property
    def contract_status_value(self) -> str:
        return (self.attributes or {}).get("contract_status", "")

    @property
    def in_stock_value(self) -> bool:
        return self.inventory_count > 0


class ProductImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="images"
    )
    image_url = models.URLField()
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "products_productimage"
