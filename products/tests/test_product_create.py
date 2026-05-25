from __future__ import annotations

import pytest

from products.models import Product


@pytest.fixture
def payload():
    return {
        "sku": "WIDGET-1",
        "name": "Widget",
        "description": "A widget",
        "price": "9.99",
        "attributes": {"color": "blue"},
        "inventory_count": 10,
    }


def test_seller_can_create_product(db, force_login, seller_user, payload):
    client = force_login(seller_user)
    response = client.post("/api/v1/products/", payload, format="json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["sku"] == "WIDGET-1"
    assert body["seller"] == str(seller_user.pk)
    assert body["tenant"] == str(seller_user.tenant_id)
    assert Product.objects.filter(pk=body["id"]).exists()


def test_buyer_cannot_create_product(db, force_login, buyer_user, payload):
    client = force_login(buyer_user)
    response = client.post("/api/v1/products/", payload, format="json")
    assert response.status_code == 403


def test_admin_cannot_create_product_via_seller_endpoint(
    db, force_login, admin_user, payload
):
    """Spec is seller-only; admins use a separate flow."""
    client = force_login(admin_user)
    response = client.post("/api/v1/products/", payload, format="json")
    assert response.status_code == 403


def test_unauthenticated_cannot_create_product(db, api_client, payload):
    response = api_client.post("/api/v1/products/", payload, format="json")
    assert response.status_code in (401, 403)


def test_create_rejects_negative_inventory(db, force_login, seller_user, payload):
    client = force_login(seller_user)
    payload["inventory_count"] = -1
    response = client.post("/api/v1/products/", payload, format="json")
    assert response.status_code == 400
    assert "inventory_count" in response.json()


def test_create_rejects_non_positive_price(db, force_login, seller_user, payload):
    client = force_login(seller_user)
    payload["price"] = "0"
    response = client.post("/api/v1/products/", payload, format="json")
    assert response.status_code == 400


def test_create_rejects_duplicate_sku_for_same_tenant(
    db, force_login, seller_user, payload
):
    client = force_login(seller_user)
    first = client.post("/api/v1/products/", payload, format="json")
    assert first.status_code == 201
    second = client.post("/api/v1/products/", payload, format="json")
    assert second.status_code == 400
    assert "sku" in second.json()


def test_seller_without_stripe_cannot_create_product(
    db, force_login, seller_user_no_stripe, payload, settings
):
    # Gate is feature-flagged off in dev; force it on for this test so we
    # actually exercise the 403 path the way prod will see it.
    settings.STRIPE_GATE_ENABLED = True
    client = force_login(seller_user_no_stripe)
    response = client.post("/api/v1/products/", payload, format="json")
    assert response.status_code == 403, response.content
    body = response.json()
    assert body["code"] == "stripe_onboarding_required"
    assert not Product.objects.filter(seller=seller_user_no_stripe).exists()
