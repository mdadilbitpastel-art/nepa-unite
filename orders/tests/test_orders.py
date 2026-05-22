"""Order endpoint tests: create, list, retrieve, status transitions."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from orders.models import Order
from orders.state import InvalidTransitionError
from products.inventory import InsufficientInventoryError
from products.models import Product


@pytest.fixture(autouse=True)
def mute_outbound(monkeypatch):
    """Don't hit the network or Redis lock in any of these tests."""
    monkeypatch.setattr(
        "orders.services.reserve_inventory",
        lambda product_id, qty: 0,
    )
    monkeypatch.setattr(
        "orders.services.release_inventory",
        lambda product_id, qty: 0,
    )


@pytest.fixture
def product(db, seller_user, tenant):
    return Product.objects.create(
        tenant=tenant, seller=seller_user,
        sku="ORD-1", name="Order test",
        description="x", price=Decimal("10.00"),
        inventory_count=20,
    )


def _post_order(client, product_id, qty=2):
    return client.post(
        "/api/v1/orders/",
        {"items": [{"product_id": str(product_id), "quantity": qty}]},
        format="json",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/orders
# ---------------------------------------------------------------------------
def test_buyer_can_create_order(db, force_login, buyer_user, product):
    client = force_login(buyer_user)
    with patch("orders.services.emit_platform_event"), \
         patch("orders.services.notify_order_status_change"):
        response = _post_order(client, product.pk, qty=3)
    assert response.status_code == 201, response.content
    body = response.json()
    assert Decimal(body["total_amount"]) == Decimal("30.00")
    assert len(body["items"]) == 1


def test_seller_cannot_create_order(db, force_login, seller_user, product):
    client = force_login(seller_user)
    response = _post_order(client, product.pk)
    assert response.status_code == 403


def test_unauthenticated_cannot_create_order(db, api_client, product):
    response = _post_order(api_client, product.pk)
    assert response.status_code in (401, 403)


def test_order_create_rejects_inactive_product(
    db, force_login, buyer_user, product
):
    product.status = Product.Status.INACTIVE
    product.save(update_fields=["status"])
    client = force_login(buyer_user)
    response = _post_order(client, product.pk)
    assert response.status_code == 400


def test_order_create_releases_inventory_on_partial_failure(
    db, force_login, buyer_user, product, tenant, seller_user, monkeypatch
):
    second = Product.objects.create(
        tenant=tenant, seller=seller_user,
        sku="ORD-2", name="x", description="x",
        price=Decimal("5"), inventory_count=20,
    )
    calls = []

    def fake_reserve(pid, qty):
        calls.append(("reserve", pid, qty))
        if pid == str(second.pk):
            raise InsufficientInventoryError(pid, qty, 0)

    def fake_release(pid, qty):
        calls.append(("release", pid, qty))

    monkeypatch.setattr("orders.services.reserve_inventory", fake_reserve)
    monkeypatch.setattr("orders.services.release_inventory", fake_release)

    client = force_login(buyer_user)
    response = client.post(
        "/api/v1/orders/",
        {"items": [
            {"product_id": str(product.pk), "quantity": 1},
            {"product_id": str(second.pk), "quantity": 1},
        ]},
        format="json",
    )
    assert response.status_code == 400
    # First reserve succeeded, second failed -> release should fire for the first.
    assert ("release", str(product.pk), 1) in calls


# ---------------------------------------------------------------------------
# GET /api/v1/orders
# ---------------------------------------------------------------------------
def test_buyer_only_sees_own_orders(db, force_login, buyer_user, product, tenant):
    # buyer_user owns one order; a different buyer owns another.
    from users.models import CustomUser
    other_buyer = CustomUser.objects.create(
        email="b2@example.com", auth0_sub="auth0|b2",
        role=CustomUser.Role.BUYER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    Order.objects.create(buyer=buyer_user, tenant=tenant)
    Order.objects.create(buyer=other_buyer, tenant=tenant)
    client = force_login(buyer_user)
    response = client.get("/api/v1/orders/")
    assert response.status_code == 200
    body = response.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    assert len(items) == 1
    assert items[0]["buyer"] == str(buyer_user.pk)


def test_seller_sees_only_orders_with_their_items(
    db, force_login, seller_user, buyer_user, product
):
    # Create an order with a line item from seller_user.
    order = Order.objects.create(buyer=buyer_user, tenant=buyer_user.tenant)
    from orders.models import OrderItem
    OrderItem.objects.create(
        order=order, product=product, seller=seller_user,
        quantity=1, unit_price=Decimal("10"),
    )
    client = force_login(seller_user)
    response = client.get("/api/v1/orders/")
    assert response.status_code == 200
    body = response.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    assert len(items) >= 1


def test_admin_sees_every_order(db, force_login, admin_user, buyer_user, tenant):
    Order.objects.create(buyer=buyer_user, tenant=tenant)
    client = force_login(admin_user)
    response = client.get("/api/v1/orders/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /api/v1/orders/{id}/status
# ---------------------------------------------------------------------------
def test_status_transition_happy_path(
    db, force_login, buyer_user, product, monkeypatch
):
    order = Order.objects.create(buyer=buyer_user, tenant=buyer_user.tenant)
    client = force_login(buyer_user)
    monkeypatch.setattr("orders.services.emit_platform_event.delay", lambda **k: None)
    monkeypatch.setattr("orders.services.notify_order_status_change", lambda **k: None)
    monkeypatch.setattr("orders.services.write_audit_log.delay", lambda **k: None)
    response = client.patch(
        f"/api/v1/orders/{order.pk}/status/", {"status": "confirmed"}, format="json"
    )
    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == Order.Status.CONFIRMED


def test_status_transition_rejects_invalid_jump(
    db, force_login, buyer_user, monkeypatch
):
    order = Order.objects.create(buyer=buyer_user, tenant=buyer_user.tenant)
    client = force_login(buyer_user)
    response = client.patch(
        f"/api/v1/orders/{order.pk}/status/", {"status": "delivered"}, format="json"
    )
    assert response.status_code == 400


def test_status_transition_to_cancelled_releases_inventory(
    db, force_login, buyer_user, product, monkeypatch
):
    order = Order.objects.create(buyer=buyer_user, tenant=buyer_user.tenant)
    from orders.models import OrderItem
    OrderItem.objects.create(
        order=order, product=product, seller=product.seller,
        quantity=2, unit_price=Decimal("10"),
    )
    released = []
    monkeypatch.setattr(
        "orders.services.release_inventory",
        lambda pid, qty: released.append((pid, qty)),
    )
    monkeypatch.setattr("orders.services.emit_platform_event.delay", lambda **k: None)
    monkeypatch.setattr("orders.services.notify_order_status_change", lambda **k: None)
    monkeypatch.setattr("orders.services.write_audit_log.delay", lambda **k: None)
    client = force_login(buyer_user)
    response = client.patch(
        f"/api/v1/orders/{order.pk}/status/", {"status": "cancelled"}, format="json"
    )
    assert response.status_code == 200
    assert released == [(str(product.pk), 2)]
