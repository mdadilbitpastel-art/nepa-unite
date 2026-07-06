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


def test_intent_endpoint_reuses_open_intent(db, force_login, buyer_user, order):
    """Re-POSTing /payments/intent reuses the open intent (no duplicate rows)."""
    Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_open",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )
    client = force_login(buyer_user)
    reusable = SimpleNamespace(
        id="pi_open", client_secret="cs_open", status="requires_payment_method"
    )
    with patch("payments.stripe_service.stripe.PaymentIntent.retrieve",
               return_value=reusable), \
         patch("payments.stripe_service.stripe.PaymentIntent.create") as create:
        response = client.post(
            "/api/v1/payments/intent", {"order_id": str(order.pk)}, format="json"
        )
    assert response.status_code == 201, response.content
    assert response.json()["client_secret"] == "cs_open"
    create.assert_not_called()
    assert order.payments.count() == 1


# ---------------------------------------------------------------------------
# POST /api/v1/payments/{order_id}/sync  (webhook-free reconciliation)
# ---------------------------------------------------------------------------
def test_buyer_syncs_and_confirms_order(db, force_login, buyer_user, order):
    order.stripe_payment_intent_id = "pi_sync"
    order.save(update_fields=["stripe_payment_intent_id"])
    Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_sync",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )
    client = force_login(buyer_user)
    succeeded = SimpleNamespace(id="pi_sync", status="succeeded")
    with patch("payments.stripe_service.stripe.PaymentIntent.retrieve",
               return_value=succeeded):
        response = client.post(f"/api/v1/payments/{order.pk}/sync", {}, format="json")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["payment_intent_status"] == "succeeded"
    assert body["order_status"] == Order.Status.CONFIRMED
    order.refresh_from_db()
    assert order.status == Order.Status.CONFIRMED


def test_sync_returns_null_status_without_intent(db, force_login, buyer_user, order):
    client = force_login(buyer_user)
    response = client.post(f"/api/v1/payments/{order.pk}/sync", {}, format="json")
    assert response.status_code == 200, response.content
    assert response.json()["payment_intent_status"] is None


def test_buyer_cannot_sync_other_buyers_order(
    db, force_login, buyer_user, order, tenant
):
    from users.models import CustomUser
    other = CustomUser.objects.create(
        email="sync-other@example.com", auth0_sub="auth0|sync-other",
        role=CustomUser.Role.BUYER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    client = force_login(other)
    response = client.post(f"/api/v1/payments/{order.pk}/sync", {}, format="json")
    assert response.status_code == 403


def test_seller_cannot_sync_order(db, force_login, seller_user, order):
    client = force_login(seller_user)
    response = client.post(f"/api/v1/payments/{order.pk}/sync", {}, format="json")
    assert response.status_code == 403


def test_sync_requires_auth(db, api_client, order):
    response = api_client.post(f"/api/v1/payments/{order.pk}/sync", {}, format="json")
    assert response.status_code in (401, 403)


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
def test_seller_can_request_onboarding(db, force_login, seller_user_no_stripe):
    client = force_login(seller_user_no_stripe)
    with patch("payments.stripe_service.stripe.Account.create",
               return_value=SimpleNamespace(id="acct_test")) as account_create, \
         patch("payments.stripe_service.stripe.AccountLink.create",
               return_value=SimpleNamespace(url="https://stripe.com/onboard/abc")):
        response = client.post("/api/v1/sellers/onboard", {}, format="json")
    assert response.status_code == 200
    assert response.json()["onboarding_url"] == "https://stripe.com/onboard/abc"
    seller_user_no_stripe.refresh_from_db()
    assert seller_user_no_stripe.stripe_account_id == "acct_test"
    account_create.assert_called_once()


def test_buyer_cannot_request_onboarding(db, force_login, buyer_user):
    client = force_login(buyer_user)
    response = client.post("/api/v1/sellers/onboard", {}, format="json")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/payments/config  (public — frontend Stripe.js init)
# ---------------------------------------------------------------------------
def test_payment_config_is_public_and_returns_publishable_key(db, api_client, settings):
    settings.STRIPE_PUBLISHABLE_KEY = "pk_test_xyz"
    settings.STRIPE_SECRET_KEY = "sk_test_xyz"
    response = api_client.get("/api/v1/payments/config")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["publishable_key"] == "pk_test_xyz"
    assert body["currency"] == "usd"
    assert body["configured"] is True


def test_payment_config_reports_unconfigured(db, api_client, settings):
    settings.STRIPE_PUBLISHABLE_KEY = ""
    settings.STRIPE_SECRET_KEY = ""
    response = api_client.get("/api/v1/payments/config")
    assert response.status_code == 200
    assert response.json()["configured"] is False


# ---------------------------------------------------------------------------
# get_or_create_payment_intent — idempotent reuse for the checkout page
# ---------------------------------------------------------------------------
def test_get_or_create_reuses_open_intent(db, order):
    Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_open",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )
    from payments import stripe_service

    reusable = SimpleNamespace(
        id="pi_open", client_secret="cs_open", status="requires_payment_method"
    )
    with patch("payments.stripe_service.stripe.PaymentIntent.retrieve",
               return_value=reusable) as retrieve, \
         patch("payments.stripe_service.stripe.PaymentIntent.create") as create:
        result = stripe_service.get_or_create_payment_intent(str(order.pk))

    assert result["client_secret"] == "cs_open"
    retrieve.assert_called_once_with("pi_open")
    create.assert_not_called()
    # No duplicate Payment row spawned.
    assert order.payments.count() == 1


def test_get_or_create_makes_new_intent_when_none_pending(db, order):
    from payments import stripe_service

    fresh = SimpleNamespace(id="pi_new", client_secret="cs_new")
    with patch("payments.stripe_service.stripe.PaymentIntent.create",
               return_value=fresh) as create:
        result = stripe_service.get_or_create_payment_intent(str(order.pk))

    assert result["payment_intent_id"] == "pi_new"
    create.assert_called_once()
    assert order.payments.filter(stripe_payment_intent_id="pi_new").exists()


def test_get_or_create_replaces_already_paid_intent(db, order):
    Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_done",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )
    from payments import stripe_service

    # The pending row points at an intent Stripe already settled — not reusable.
    settled = SimpleNamespace(id="pi_done", client_secret="cs_done", status="succeeded")
    fresh = SimpleNamespace(id="pi_fresh", client_secret="cs_fresh")
    with patch("payments.stripe_service.stripe.PaymentIntent.retrieve",
               return_value=settled), \
         patch("payments.stripe_service.stripe.PaymentIntent.create",
               return_value=fresh) as create:
        result = stripe_service.get_or_create_payment_intent(str(order.pk))

    assert result["payment_intent_id"] == "pi_fresh"
    create.assert_called_once()


# ---------------------------------------------------------------------------
# sync_payment_status — webhook-free reconciliation on checkout return
# ---------------------------------------------------------------------------
def test_sync_marks_completed_and_confirms_order(db, order):
    order.stripe_payment_intent_id = "pi_sync"
    order.save(update_fields=["stripe_payment_intent_id"])
    payment = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_sync",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )
    from payments import stripe_service

    succeeded = SimpleNamespace(id="pi_sync", status="succeeded")
    with patch("payments.stripe_service.stripe.PaymentIntent.retrieve",
               return_value=succeeded):
        status = stripe_service.sync_payment_status(str(order.pk))

    assert status == "succeeded"
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == Payment.Status.COMPLETED
    assert order.status == Order.Status.CONFIRMED


def test_sync_without_intent_returns_none(db, order):
    from payments import stripe_service
    assert stripe_service.sync_payment_status(str(order.pk)) is None


def test_sync_confirms_against_paid_duplicate_intent(db, order):
    """Regression: a duplicate intent was created and the order recorded the
    *unpaid* one, but the buyer paid the other. Sync must reconcile all of the
    order's intents, confirm the order, and repoint it at the paid intent."""
    from payments import stripe_service

    # Order points at the unpaid duplicate.
    order.stripe_payment_intent_id = "pi_unpaid"
    order.save(update_fields=["stripe_payment_intent_id"])
    paid = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_paid",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )
    unpaid = Payment.objects.create(
        order=order, stripe_payment_intent_id="pi_unpaid",
        amount=Decimal("100"), platform_fee=Decimal("5"),
        status=Payment.Status.PENDING,
    )

    def fake_retrieve(pid):
        status = "succeeded" if pid == "pi_paid" else "requires_payment_method"
        return SimpleNamespace(id=pid, status=status)

    with patch("payments.stripe_service.stripe.PaymentIntent.retrieve",
               side_effect=fake_retrieve):
        result = stripe_service.sync_payment_status(str(order.pk))

    assert result == "succeeded"
    order.refresh_from_db()
    paid.refresh_from_db()
    unpaid.refresh_from_db()
    assert order.status == Order.Status.CONFIRMED
    assert order.stripe_payment_intent_id == "pi_paid"
    assert paid.status == Payment.Status.COMPLETED
    assert unpaid.status == Payment.Status.PENDING


# ---------------------------------------------------------------------------
# Health probe (admin dashboard)
# ---------------------------------------------------------------------------
def test_stripe_mode_from_key(settings):
    from payments import stripe_service
    settings.STRIPE_SECRET_KEY = "sk_test_abc"
    assert stripe_service.stripe_mode() == "test"
    settings.STRIPE_SECRET_KEY = "sk_live_abc"
    assert stripe_service.stripe_mode() == "live"
    settings.STRIPE_SECRET_KEY = ""
    assert stripe_service.stripe_mode() == "unset"


def test_stripe_health_unconfigured(settings):
    from payments import stripe_service
    settings.STRIPE_SECRET_KEY = ""
    ok, error = stripe_service.stripe_health()
    assert ok is False
    assert "not configured" in error


def test_stripe_health_ok(settings):
    from payments import stripe_service
    settings.STRIPE_SECRET_KEY = "sk_test_abc"
    with patch("payments.stripe_service.stripe.Balance.retrieve") as retrieve:
        ok, error = stripe_service.stripe_health()
    assert ok is True
    assert error is None
    retrieve.assert_called_once()


def test_stripe_health_reports_api_error(settings):
    from payments import stripe_service
    settings.STRIPE_SECRET_KEY = "sk_test_bad"
    with patch("payments.stripe_service.stripe.Balance.retrieve",
               side_effect=Exception("Invalid API Key")):
        ok, error = stripe_service.stripe_health()
    assert ok is False
    assert "Invalid API Key" in error


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
