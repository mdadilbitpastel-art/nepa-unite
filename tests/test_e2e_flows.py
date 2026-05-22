"""End-to-end happy-path flows.

Every external dependency (Auth0, Stripe, S3, Elasticsearch, Celery) is
mocked at its boundary so these tests run in CI without those services.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

from rest_framework.test import APIClient

from orders.models import Order
from payments.models import Invoice, Payment
from products.models import Product
from users.models import CustomUser, Tenant, WorkflowTemplate
from webhooks.models import WebhookDelivery, WebhookEndpoint


# ---------------------------------------------------------------------------
# Flow 1: register buyer -> admin approves -> login -> search -> order ->
#         payment intent -> order confirmed -> delivered -> invoice download
# ---------------------------------------------------------------------------
def test_flow_1_buyer_happy_path(db, monkeypatch, mock_send_email):
    api = APIClient()
    admin = _make_admin(db)
    seller, product = _seed_seller_with_product(db, sku="E2E-1", price="50")

    # Register
    with patch("users.views.auth0_client.create_user",
               return_value={"user_id": "auth0|e2e1"}):
        response = api.post(
            "/api/v1/auth/register",
            {"email": "buyer-e2e1@example.com", "password": "supersecret",
             "role": "buyer", "business_name": "BuyerCo",
             "vertical_type": "dental"},
            format="json",
        )
    assert response.status_code == 201
    buyer = CustomUser.objects.get(email="buyer-e2e1@example.com")

    # Admin approves
    api.force_authenticate(admin)
    response = api.post(f"/api/v1/admin/members/{buyer.pk}/approve/")
    assert response.status_code == 200
    buyer.refresh_from_db()
    assert buyer.status == CustomUser.Status.ACTIVE
    api.force_authenticate(None)

    # Buyer "logs in" — bypass Auth0 in the test by force-auth as the user.
    api.force_authenticate(buyer)

    # Search (use the public endpoint)
    api.force_authenticate(None)
    with patch("products.documents.ProductDocument.search",
               side_effect=Exception("ES down")):
        response = api.get("/api/v1/products/search/?q=E2E")
    assert response.status_code == 200

    # Place order
    api.force_authenticate(buyer)
    monkeypatch.setattr("orders.services.reserve_inventory", lambda pid, qty: 0)
    monkeypatch.setattr("orders.services.release_inventory", lambda pid, qty: 0)
    monkeypatch.setattr("orders.services.emit_platform_event.delay", lambda **k: None)
    monkeypatch.setattr("orders.services.notify_order_status_change", lambda **k: None)
    monkeypatch.setattr("orders.services.write_audit_log.delay", lambda **k: None)
    response = api.post(
        "/api/v1/orders/",
        {"items": [{"product_id": str(product.pk), "quantity": 1}]},
        format="json",
    )
    assert response.status_code == 201
    order_id = response.json()["id"]

    # Payment intent
    with patch("payments.stripe_service.stripe.PaymentIntent.create",
               return_value=SimpleNamespace(id="pi_e2e1", client_secret="cs")):
        response = api.post(
            "/api/v1/payments/intent", {"order_id": order_id}, format="json"
        )
    assert response.status_code == 201

    # Stripe webhook -> confirm
    from webhooks.handlers import handle_payment_succeeded
    handle_payment_succeeded({
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_e2e1"}},
    })
    Order.objects.get(pk=order_id).refresh_from_db()

    # Walk through to delivered.
    for target in ("fulfillment", "shipped", "delivered"):
        response = api.patch(
            f"/api/v1/orders/{order_id}/status/", {"status": target}, format="json"
        )
        assert response.status_code == 200

    # Invoice download
    with patch("payments.invoice_service._s3_client") as s3:
        s3.return_value.generate_presigned_url.return_value = "https://s3/inv"
        response = api.get(f"/api/v1/orders/{order_id}/invoice")
    assert response.status_code == 200
    assert Invoice.objects.filter(order_id=order_id).exists()


# ---------------------------------------------------------------------------
# Flow 2: seller register/approve -> create product -> buyer search finds it.
# ---------------------------------------------------------------------------
def test_flow_2_seller_listing_pipeline(db, mock_send_email):
    api = APIClient()
    admin = _make_admin(db)

    with patch("users.views.auth0_client.create_user",
               return_value={"user_id": "auth0|e2e2"}):
        response = api.post(
            "/api/v1/auth/register",
            {"email": "seller-e2e2@example.com", "password": "supersecret",
             "role": "seller", "business_name": "SellerCo",
             "vertical_type": "law_office"},
            format="json",
        )
    assert response.status_code == 201
    seller = CustomUser.objects.get(email="seller-e2e2@example.com")

    api.force_authenticate(admin)
    api.post(f"/api/v1/admin/members/{seller.pk}/approve/")
    api.force_authenticate(seller)

    response = api.post(
        "/api/v1/products/",
        {"sku": "E2E2-1", "name": "Seller product", "description": "x",
         "price": "12.50", "attributes": {}, "inventory_count": 8},
        format="json",
    )
    assert response.status_code == 201
    product_id = response.json()["id"]

    # Buyer-side search via PG fallback
    api.force_authenticate(None)
    with patch("products.documents.ProductDocument.search",
               side_effect=Exception("ES down")):
        response = api.get("/api/v1/products/search/?q=Seller")
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(str(item["id"]) == product_id for item in items)


# ---------------------------------------------------------------------------
# Flow 3: order placed -> buyer requests refund -> payment refunded ->
#         inventory released -> order cancelled.
# ---------------------------------------------------------------------------
def test_flow_3_refund_flow(db, monkeypatch):
    buyer, _seller, product = _seed_user_set_with_product(db)
    api = APIClient()
    api.force_authenticate(buyer)
    monkeypatch.setattr("orders.services.reserve_inventory", lambda pid, qty: 0)
    monkeypatch.setattr("orders.services.emit_platform_event.delay", lambda **k: None)
    monkeypatch.setattr("orders.services.notify_order_status_change", lambda **k: None)
    monkeypatch.setattr("orders.services.write_audit_log.delay", lambda **k: None)
    monkeypatch.setattr("orders.services.release_inventory", lambda pid, qty: 0)

    response = api.post(
        "/api/v1/orders/",
        {"items": [{"product_id": str(product.pk), "quantity": 2}]},
        format="json",
    )
    assert response.status_code == 201
    order_id = response.json()["id"]
    order = Order.objects.get(pk=order_id)
    Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_refund_flow",
        amount=order.total_amount, platform_fee=Decimal("1"),
        status=Payment.Status.COMPLETED,
    )

    released = []
    monkeypatch.setattr(
        "payments.stripe_service.release_inventory",
        lambda pid, qty: released.append((pid, qty)),
    )
    with patch("payments.stripe_service.stripe.Refund.create"):
        from payments.stripe_service import process_refund
        process_refund(str(order.pk))

    order.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    payment = Payment.objects.get(stripe_payment_intent_id="pi_refund_flow")
    assert payment.status == Payment.Status.REFUNDED
    assert len(released) == 1


# ---------------------------------------------------------------------------
# Flow 4: outgoing order.created webhook fires, simulate failure, retry runs
#         on schedule.
# ---------------------------------------------------------------------------
def test_flow_4_webhook_delivery_and_retry(db, buyer_user):
    WebhookEndpoint.objects.create(
        owner=buyer_user,
        url="https://buyer.example.com/hook",
        secret="topsecret",
        event_types=["order.created"],
    )
    from webhooks.tasks import deliver_webhook, emit_platform_event

    with patch("webhooks.tasks.deliver_webhook.delay") as delay_call:
        emit_platform_event(
            event_type="order.created", payload={"order_id": "abc"}
        )
    assert WebhookDelivery.objects.count() == 1
    delivery = WebhookDelivery.objects.first()
    delay_call.assert_called_once_with(str(delivery.pk))

    # First attempt fails — assert next retry scheduled at +60s.
    fake = MagicMock(status_code=503, text="busy")
    with patch("webhooks.tasks.requests.post", return_value=fake), \
         patch("webhooks.tasks.deliver_webhook.apply_async") as retry:
        deliver_webhook(str(delivery.pk))
    delivery.refresh_from_db()
    assert delivery.status == WebhookDelivery.Status.PENDING
    assert delivery.attempt == 1
    retry.assert_called_once()
    assert retry.call_args.kwargs["countdown"] == 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_admin(db) -> CustomUser:
    tenant = Tenant.objects.create(
        name="Platform", vertical_type=WorkflowTemplate.Vertical.OTHER,
        status=Tenant.Status.ACTIVE,
    )
    return CustomUser.objects.create(
        email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        auth0_sub=f"auth0|admin-{uuid.uuid4().hex[:6]}",
        role=CustomUser.Role.ADMIN, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )


def _seed_seller_with_product(db, *, sku: str, price: str) -> tuple[CustomUser, Product]:
    tenant = Tenant.objects.create(
        name=f"Tenant {sku}", vertical_type=WorkflowTemplate.Vertical.DENTAL,
        status=Tenant.Status.ACTIVE,
    )
    seller = CustomUser.objects.create(
        email=f"seller-{sku}@example.com", auth0_sub=f"auth0|s-{sku}",
        role=CustomUser.Role.SELLER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    product = Product.objects.create(
        tenant=tenant, seller=seller, sku=sku,
        name="E2E product", description="desc",
        price=Decimal(price), inventory_count=10,
    )
    return seller, product


def _seed_user_set_with_product(db) -> tuple[CustomUser, CustomUser, Product]:
    tenant = Tenant.objects.create(
        name="E2E", vertical_type=WorkflowTemplate.Vertical.DENTAL,
        status=Tenant.Status.ACTIVE,
    )
    buyer = CustomUser.objects.create(
        email=f"b-{uuid.uuid4().hex[:6]}@example.com",
        auth0_sub=f"auth0|b-{uuid.uuid4().hex[:6]}",
        role=CustomUser.Role.BUYER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    seller = CustomUser.objects.create(
        email=f"s-{uuid.uuid4().hex[:6]}@example.com",
        auth0_sub=f"auth0|s-{uuid.uuid4().hex[:6]}",
        role=CustomUser.Role.SELLER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    product = Product.objects.create(
        tenant=tenant, seller=seller, sku="E2E-REFUND",
        name="Refundable", description="x",
        price=Decimal("25"), inventory_count=10,
    )
    return buyer, seller, product
