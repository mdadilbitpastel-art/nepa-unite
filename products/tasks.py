"""Background tasks for the products app."""

from __future__ import annotations

import csv
import io
import logging
from decimal import Decimal, InvalidOperation

from celery import shared_task
from django.db import transaction

from core.models import Job
from products.models import Product

logger = logging.getLogger(__name__)

REQUIRED_CSV_COLUMNS = ("sku", "name", "description", "price", "inventory_count")


@shared_task
def reindex_product(product_id: str) -> None:
    """Reindex one product in the ES index."""
    try:
        from products.documents import ProductDocument
        product = Product.objects.get(pk=product_id)
        ProductDocument().update(product)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reindex_product(%s) failed: %s", product_id, exc)


@shared_task
def remove_product_from_index(product_id: str) -> None:
    try:
        from products.documents import ProductDocument
        product = Product.objects.get(pk=product_id)
        ProductDocument().delete(product, ignore=404)
    except Exception as exc:  # noqa: BLE001
        logger.warning("remove_product_from_index(%s) failed: %s", product_id, exc)


@shared_task
def low_stock_alert(product_id: str) -> None:
    """Notify the seller that a product just dropped below LOW_STOCK_THRESHOLD."""
    from django.conf import settings
    from django.core.mail import send_mail
    try:
        product = Product.objects.select_related("seller").get(pk=product_id)
    except Product.DoesNotExist:
        return
    send_mail(
        subject=f"Low stock: {product.name}",
        message=(
            f"Inventory for {product.sku} ({product.name}) is now "
            f"{product.inventory_count}, below the low-stock threshold."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[product.seller.email],
        fail_silently=True,
    )


@shared_task
def process_bulk_upload(job_id: str, csv_text: str) -> None:
    """Validate then insert each row of a CSV upload.

    Validation happens up-front; if any row is malformed the job fails as a
    whole. This avoids the surprise of a partially-loaded catalog.
    """
    try:
        job = Job.objects.get(pk=job_id)
    except Job.DoesNotExist:
        logger.error("process_bulk_upload: missing job %s", job_id)
        return

    job.status = Job.Status.RUNNING
    job.save(update_fields=["status", "updated_at"])

    seller = job.owner
    rows, errors = _validate_csv(csv_text)
    job.total = len(rows)

    if errors:
        job.status = Job.Status.FAILED
        job.errors = errors
        job.save(update_fields=["status", "total", "errors", "updated_at"])
        return

    with transaction.atomic():
        created_ids: list[str] = []
        for row in rows:
            try:
                product = Product.objects.create(
                    tenant_id=seller.tenant_id,
                    seller=seller,
                    sku=row["sku"],
                    name=row["name"],
                    description=row.get("description", ""),
                    price=Decimal(row["price"]),
                    inventory_count=int(row["inventory_count"]),
                    attributes=row.get("attributes", {}),
                )
                created_ids.append(str(product.pk))
                job.succeeded += 1
            except Exception as exc:  # noqa: BLE001
                job.failed += 1
                job.errors.append({"row": row, "error": str(exc)})
        job.status = (
            Job.Status.SUCCESS if job.failed == 0 else Job.Status.FAILED
        )
        job.result = {"created_ids": created_ids}
        job.save()

    for pk in created_ids:
        reindex_product.delay(pk)


def _validate_csv(csv_text: str) -> tuple[list[dict], list[dict]]:
    """Return (rows, errors). `errors` is empty when the CSV is fully valid."""
    errors: list[dict] = []
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(csv_text))

    if reader.fieldnames is None:
        return rows, [{"row": 0, "error": "CSV has no header"}]

    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in reader.fieldnames]
    if missing:
        return rows, [{"row": 0, "error": f"Missing columns: {missing}"}]

    for line_no, row in enumerate(reader, start=2):
        if not row.get("sku") or not row.get("name"):
            errors.append({"row": line_no, "error": "sku and name are required"})
            continue
        try:
            price = Decimal(row["price"])
            if price <= 0:
                raise InvalidOperation("price must be positive")
        except (InvalidOperation, KeyError) as exc:
            errors.append({"row": line_no, "error": f"invalid price: {exc}"})
            continue
        try:
            inv = int(row["inventory_count"])
            if inv < 0:
                raise ValueError("inventory_count must be >= 0")
        except (ValueError, KeyError) as exc:
            errors.append({"row": line_no, "error": f"invalid inventory_count: {exc}"})
            continue
        rows.append({
            "sku": row["sku"].strip(),
            "name": row["name"].strip(),
            "description": row.get("description", "").strip(),
            "price": str(price),
            "inventory_count": inv,
            "attributes": {},
        })
    return rows, errors
