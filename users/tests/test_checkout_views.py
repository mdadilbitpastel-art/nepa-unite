"""HTML buyer checkout views (Stripe Payment Element flow, Stripe mocked)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from orders.models import Order, OrderItem
from products.models import Product


@pytest.fixture
def draft_order(db, buyer_user, tenant, seller_user):
    product = Product.objects.create(
        tenant=tenant, seller=seller_user, sku="CHK-1", name="Checkout test",
        description="x", price=Decimal("25.00"), inventory_count=10,
    )
    order = Order.objects.create(
        buyer=buyer_user, tenant=tenant,
        total_amount=Decimal("50.00"),
        status=Order.Status.DRAFT,
    )
    OrderItem.objects.create(
        order=order, product=product, seller=seller_user,
        quantity=2, unit_price=Decimal("25.00"),
    )
    return order


@pytest.fixture
def stripe_keys(settings):
    settings.STRIPE_PUBLISHABLE_KEY = "pk_test_dummy"
    settings.STRIPE_SECRET_KEY = "sk_test_dummy"
    return settings


def _session_client(user):
    client = Client()
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# Pay button visibility on the order detail page
# ---------------------------------------------------------------------------
def test_buyer_can_pay_flag_on_draft_order(db, buyer_user, draft_order):
    client = _session_client(buyer_user)
    response = client.get(reverse("order_detail", args=[draft_order.pk]))
    assert response.status_code == 200
    assert response.context["can_pay"] is True


def test_seller_does_not_see_pay_flag(db, seller_user, draft_order):
    client = _session_client(seller_user)
    response = client.get(reverse("order_detail", args=[draft_order.pk]))
    assert response.status_code == 200
    assert response.context["can_pay"] is False


# ---------------------------------------------------------------------------
# GET checkout page
# ---------------------------------------------------------------------------
def test_buyer_opens_checkout_page(db, buyer_user, draft_order, stripe_keys):
    client = _session_client(buyer_user)
    with patch(
        "payments.stripe_service.get_or_create_payment_intent",
        return_value={"client_secret": "cs_test_abc", "payment_intent_id": "pi_1"},
    ) as init:
        response = client.get(reverse("order_pay", args=[draft_order.pk]))
    assert response.status_code == 200
    assert response.context["client_secret"] == "cs_test_abc"
    assert response.context["stripe_publishable_key"] == "pk_test_dummy"
    init.assert_called_once_with(str(draft_order.pk))


def test_seller_cannot_open_checkout(db, seller_user, draft_order, stripe_keys):
    client = _session_client(seller_user)
    response = client.get(reverse("order_pay", args=[draft_order.pk]))
    assert response.status_code == 302
    assert reverse("order_detail", args=[draft_order.pk]) in response.url


def test_checkout_blocked_for_already_paid_order(db, buyer_user, draft_order, stripe_keys):
    draft_order.status = Order.Status.CONFIRMED
    draft_order.save(update_fields=["status"])
    client = _session_client(buyer_user)
    response = client.get(reverse("order_pay", args=[draft_order.pk]))
    assert response.status_code == 302


def test_checkout_unconfigured_keys_redirect(db, buyer_user, draft_order, settings):
    settings.STRIPE_PUBLISHABLE_KEY = ""
    settings.STRIPE_SECRET_KEY = ""
    client = _session_client(buyer_user)
    response = client.get(reverse("order_pay", args=[draft_order.pk]))
    assert response.status_code == 302


# ---------------------------------------------------------------------------
# Post-payment return / reconciliation
# ---------------------------------------------------------------------------
def test_return_view_reconciles_and_redirects(db, buyer_user, draft_order):
    client = _session_client(buyer_user)
    with patch(
        "payments.stripe_service.sync_payment_status", return_value="succeeded"
    ) as sync:
        response = client.get(reverse("order_pay_return", args=[draft_order.pk]))
    assert response.status_code == 302
    assert reverse("order_detail", args=[draft_order.pk]) in response.url
    sync.assert_called_once_with(str(draft_order.pk))
