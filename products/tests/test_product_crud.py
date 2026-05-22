"""PUT/DELETE/GET detail + search + bulk upload tests."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile

from contracts.models import Contract
from core.models import Job
from products.models import Product
from products.services import SearchResult


def _make_product(seller, tenant, **overrides):
    defaults = dict(
        tenant=tenant,
        seller=seller,
        sku="SKU-1",
        name="Widget",
        description="A widget",
        price=Decimal("9.99"),
        inventory_count=10,
        attributes={"category": "tools", "region": "scranton"},
    )
    defaults.update(overrides)
    return Product.objects.create(**defaults)


# ---------------------------------------------------------------------------
# PUT /api/v1/products/{id}
# ---------------------------------------------------------------------------
def test_seller_can_update_own_product(db, force_login, seller_user, tenant):
    product = _make_product(seller_user, tenant)
    client = force_login(seller_user)
    response = client.put(
        f"/api/v1/products/{product.pk}/",
        {"sku": "SKU-1", "name": "Widget v2", "description": "Better",
         "price": "19.99", "attributes": {}, "inventory_count": 5},
        format="json",
    )
    assert response.status_code == 200, response.content
    product.refresh_from_db()
    assert product.name == "Widget v2"
    assert product.price == Decimal("19.99")


def test_seller_cannot_update_other_sellers_product(
    db, force_login, seller_user, tenant
):
    other = _make_product(seller_user, tenant, sku="SKU-A")
    from users.models import CustomUser
    intruder = CustomUser.objects.create(
        email="seller2@example.com", auth0_sub="auth0|s2",
        role=CustomUser.Role.SELLER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    client = force_login(intruder)
    response = client.put(
        f"/api/v1/products/{other.pk}/",
        {"sku": "SKU-A", "name": "hijacked", "description": "x",
         "price": "1", "attributes": {}, "inventory_count": 0},
        format="json",
    )
    assert response.status_code == 403


def test_buyer_cannot_update_product(db, force_login, seller_user, buyer_user, tenant):
    product = _make_product(seller_user, tenant)
    client = force_login(buyer_user)
    response = client.put(
        f"/api/v1/products/{product.pk}/", {"name": "x"}, format="json"
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/v1/products/{id} — soft delete only
# ---------------------------------------------------------------------------
def test_seller_delete_soft_deletes(db, force_login, seller_user, tenant):
    product = _make_product(seller_user, tenant)
    client = force_login(seller_user)
    response = client.delete(f"/api/v1/products/{product.pk}/")
    assert response.status_code == 204
    product.refresh_from_db()
    assert product.status == Product.Status.DELETED
    # Row still exists in PG.
    assert Product.objects.filter(pk=product.pk).exists()


# ---------------------------------------------------------------------------
# GET /api/v1/products/{id} — contract pricing for buyers
# ---------------------------------------------------------------------------
def test_buyer_sees_contract_price_when_eligible(
    db, force_login, seller_user, buyer_user, tenant
):
    from django.utils import timezone
    from datetime import timedelta
    product = _make_product(seller_user, tenant, sku="WIDGET", price=Decimal("100"))
    Contract.objects.create(
        vendor_name="GPO-Co",
        title="Tools tier",
        pricing_tiers=[{
            "match": {"category": "tools"},
            "price": "85.00",
        }],
        admin_fee_percent=Decimal("5"),
        valid_from=timezone.now().date() - timedelta(days=1),
        valid_until=timezone.now().date() + timedelta(days=10),
        is_active=True,
    )
    client = force_login(buyer_user)
    response = client.get(f"/api/v1/products/{product.pk}/")
    assert response.status_code == 200
    body = response.json()
    assert body["price"] == "100.00"
    assert body["contract_price"] == "85.00"


def test_seller_does_not_see_contract_price(
    db, force_login, seller_user, tenant
):
    product = _make_product(seller_user, tenant)
    client = force_login(seller_user)
    response = client.get(f"/api/v1/products/{product.pk}/")
    assert response.status_code == 200
    assert "contract_price" not in response.json()


# ---------------------------------------------------------------------------
# POST /api/v1/products/bulk-upload
# ---------------------------------------------------------------------------
def test_bulk_upload_returns_job_id(db, force_login, seller_user, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    csv = (
        "sku,name,description,price,inventory_count\n"
        "B1,Bulk1,Hi,1.50,5\n"
        "B2,Bulk2,Hi,2.50,5\n"
    ).encode("utf-8")
    upload = SimpleUploadedFile("products.csv", csv, content_type="text/csv")
    client = force_login(seller_user)
    with patch("products.views.process_bulk_upload.delay") as task:
        response = client.post(
            "/api/v1/products/bulk-upload/",
            {"file": upload},
            format="multipart",
        )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert Job.objects.filter(pk=body["job_id"]).exists()
    task.assert_called_once()


def test_bulk_upload_rejects_non_csv(db, force_login, seller_user):
    client = force_login(seller_user)
    upload = SimpleUploadedFile("products.txt", b"hello", content_type="text/plain")
    response = client.post(
        "/api/v1/products/bulk-upload/",
        {"file": upload},
        format="multipart",
    )
    assert response.status_code == 400


def test_bulk_upload_processes_valid_csv(db, seller_user):
    from products.tasks import process_bulk_upload
    job = Job.objects.create(kind="products.bulk_upload", owner=seller_user)
    csv_text = (
        "sku,name,description,price,inventory_count\n"
        "X1,X One,desc,9.99,5\n"
        "X2,X Two,desc,19.99,0\n"
    )
    with patch("products.tasks.reindex_product.delay"):
        process_bulk_upload(str(job.pk), csv_text)
    job.refresh_from_db()
    assert job.status == Job.Status.SUCCESS
    assert job.succeeded == 2
    assert Product.objects.filter(sku="X1").exists()
    assert Product.objects.filter(sku="X2").exists()


def test_bulk_upload_rejects_csv_with_bad_rows(db, seller_user):
    from products.tasks import process_bulk_upload
    job = Job.objects.create(kind="products.bulk_upload", owner=seller_user)
    csv_text = (
        "sku,name,description,price,inventory_count\n"
        "Y1,,desc,9.99,5\n"        # missing name
        "Y2,Y Two,desc,-1,5\n"      # bad price
    )
    process_bulk_upload(str(job.pk), csv_text)
    job.refresh_from_db()
    assert job.status == Job.Status.FAILED
    assert len(job.errors) == 2
    assert not Product.objects.filter(sku="Y1").exists()


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}
# ---------------------------------------------------------------------------
def test_owner_can_poll_their_job(db, force_login, seller_user):
    job = Job.objects.create(
        kind="x", owner=seller_user, status=Job.Status.SUCCESS,
        total=2, succeeded=2,
    )
    client = force_login(seller_user)
    response = client.get(f"/api/v1/jobs/{job.pk}/")
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_non_owner_cannot_poll_someone_elses_job(
    db, force_login, seller_user, buyer_user
):
    job = Job.objects.create(kind="x", owner=seller_user)
    client = force_login(buyer_user)
    response = client.get(f"/api/v1/jobs/{job.pk}/")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/products/search
# ---------------------------------------------------------------------------
def test_search_is_public_and_returns_results(db, api_client, seller_user, tenant):
    _make_product(seller_user, tenant, sku="S1", name="Search Widget")

    fake = SearchResult(
        items=[{"id": "abc", "name": "Search Widget"}],
        total=1, page=1, page_size=20, facets={}, used_fallback=False,
    )
    with patch("products.views.search_products", return_value=fake):
        response = api_client.get("/api/v1/products/search/?q=widget")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Search Widget"


def test_search_falls_back_to_postgres_when_es_down(db, api_client, seller_user, tenant):
    _make_product(seller_user, tenant, sku="S2", name="Fallback Widget",
                  status=Product.Status.ACTIVE)
    # Force the search service to take its except branch.
    with patch("products.documents.ProductDocument.search",
               side_effect=Exception("ES down")):
        response = api_client.get("/api/v1/products/search/?q=fallback")
    assert response.status_code == 200
    body = response.json()
    assert body["used_fallback"] is True
    assert body["total"] >= 1
