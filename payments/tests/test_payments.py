"""Stripe Connect endpoint tests (Stripe SDK mocked)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from orders.models import Order, OrderItem
from payments.models import Payment
from products.models import Product


@pytest.fixture
def product(db, seller_user, tenant):
    return Product.objects.create(
        tenant=tenant, seller=seller_user, sku="PAY-1", name="Pay test",
        description="x", price=Decimal("50.00"), inventory_count=10,
    )


@pytest.fixture
def order(db, buyer_user, tenant, product, seller_user):
    o = Order.objects.create(
        buyer=buyer_user, tenant=tenant,
        total_amount=Decimal("100.00"),
    )
    OrderItem.objects.create(
        order=o, product=product, seller=seller_user,
        quantity=2, unit_price=Decimal("50.00"),
    )
    return o


# ---------------------------------------------------------------------------
# POST /api/v1/payments/intent
# ---------------------------------------------------------------------------
def test_buyer_creates_payment_intent(db, force_login, buyer_user, order):
    client = force_login(buyer_user)
    fake_intent = SimpleNamespace(
        id="pi_test_123", client_secret="cs_test_xyz"
    )
    with patch("payments.stripe_service.stripe.PaymentIntent.create",
               return_value=fake_intent):
        response = client.post(
            "/api/v1/payments/intent",
            {"order_id": str(order.pk)},
            format="json",
        )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["client_secret"] == "cs_test_xyz"
    assert body["payment_intent_id"] == "pi_test_123"
    assert Payment.objects.filter(order=order,
                                  stripe_payment_intent_id="pi_test_123").exists()


def test_buyer_cannot_create_intent_for_other_buyer(
    db, force_login, buyer_user, order, tenant
):
    from users.models import CustomUser
    other = CustomUser.objects.create(
        email="other@example.com", auth0_sub="auth0|other",
        role=CustomUser.Role.BUYER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    client = force_login(other)
    response = client.post(
        "/api/v1/payments/intent", {"order_id": str(order.pk)}, format="json"
    )
    assert response.status_code == 403


def test_seller_cannot_create_intent(db, force_login, seller_user, order):
    client = force_login(seller_user)
    response = client.post(
        "/api/v1/payments/intent", {"order_id": str(order.pk)}, format="json"
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/payments/disburse  (admin only)
# ---------------------------------------------------------------------------
def test_admin_disburses_to_seller(db, force_login, admin_user, order):
    client = force_login(admin_user)
    with patch("payments.stripe_service.disburse_to_seller") as fn:
        response = client.post(
            "/api/v1/payments/disburse",
            {"order_item_id": str(order.items.first().pk)},
            format="json",
        )
    assert response.status_code == 202
    fn.assert_called_once()


def test_buyer_cannot_disburse(db, force_login, buyer_user, order):
    client = force_login(buyer_user)
    response = client.post(
        "/api/v1/payments/disburse",
        {"order_item_id": str(order.items.first().pk)},
        format="json",
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/payments/{order_id}
# ---------------------------------------------------------------------------
def test_buyer_lists_their_payments(db, force_login, buyer_user, order):
    Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_x",
        amount=Decimal("100"), platform_fee=Decimal("5"),
    )
    client = force_login(buyer_user)
    response = client.get(f"/api/v1/payments/{order.pk}")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_buyer_cannot_list_other_payments(db, force_login, buyer_user, order, tenant):
    from users.models import CustomUser
    other = CustomUser.objects.create(
        email="o2@example.com", auth0_sub="auth0|o2",
        role=CustomUser.Role.BUYER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    client = force_login(other)
    response = client.get(f"/api/v1/payments/{order.pk}")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/sellers/onboard
# ---------------------------------------------------------------------------
def test_seller_can_request_onboarding(db, force_login, seller_user):
    client = force_login(seller_user)
    with patch("payments.stripe_service.stripe.Account.create",
               return_value=SimpleNamespace(id="acct_test")) as account_create, \
         patch("payments.stripe_service.stripe.AccountLink.create",
               return_value=SimpleNamespace(url="https://stripe.com/onboard/abc")):
        response = client.post("/api/v1/sellers/onboard", {}, format="json")
    assert response.status_code == 200
    assert response.json()["onboarding_url"] == "https://stripe.com/onboard/abc"
    seller_user.refresh_from_db()
    assert seller_user.stripe_account_id == "acct_test"
    account_create.assert_called_once()


def test_buyer_cannot_request_onboarding(db, force_login, buyer_user):
    client = force_login(buyer_user)
    response = client.post("/api/v1/sellers/onboard", {}, format="json")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# process_refund (service-level test)
# ---------------------------------------------------------------------------
def test_process_refund_marks_refunded_and_releases(db, order, monkeypatch):
    payment = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_refundme",
        amount=Decimal("100"), platform_fee=Decimal("5"),
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
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED
    assert order.status == Order.Status.CANCELLED
    assert len(released) == 1
