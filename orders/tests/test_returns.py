"""End-to-end coverage for the return/exchange lifecycle."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from orders.models import Order, OrderItem, ReturnRequest
from products.models import Product

RETURNS = "/api/v1/returns/"


def _status_url(rr_id) -> str:
    return f"{RETURNS}{rr_id}/status/"


@pytest.fixture
def product(db, tenant, seller_user):
    return Product.objects.create(
        tenant=tenant, seller=seller_user, sku="RET-1", name="Return Test Drill",
        price=Decimal("100.00"), inventory_count=50, is_returnable=True,
        is_exchangeable=True, return_window_days=7,
    )


@pytest.fixture
def delivered_order(db, tenant, buyer_user, seller_user, product):
    order = Order.objects.create(
        buyer=buyer_user, tenant=tenant, status=Order.Status.DELIVERED,
        total_amount=Decimal("200.00"), delivered_at=timezone.now(),
    )
    item = OrderItem.objects.create(
        order=order, product=product, seller=seller_user,
        quantity=2, unit_price=Decimal("100.00"),
    )
    return order, item


def test_buyer_creates_and_seller_drives_full_return(
    force_login, buyer_user, seller_user, delivered_order
):
    _, item = delivered_order

    # Buyer opens a return.
    client = force_login(buyer_user)
    resp = client.post(RETURNS, {
        "order_item": str(item.id), "type": "return",
        "reason": "defective", "reason_note": "Battery dead", "quantity": 2,
    }, format="json")
    assert resp.status_code == 201, resp.content
    rr_id = resp.data["id"]
    assert resp.data["status"] == "requested"
    assert Decimal(resp.data["refund_amount"]) == Decimal("200.00")

    # Seller walks it to refunded.
    seller = force_login(seller_user)
    for target in [
        "approved", "pickup_scheduled", "picked_up", "received", "refunded",
    ]:
        r = seller.patch(_status_url(rr_id), {"status": target}, format="json")
        assert r.status_code == 200, (target, r.content)
        assert r.data["status"] == target

    rr = ReturnRequest.objects.get(pk=rr_id)
    assert rr.status == ReturnRequest.Status.REFUNDED
    # Timeline: requested + 5 transitions.
    assert rr.events.count() == 6


def test_buyer_cannot_approve_own_return(
    force_login, buyer_user, delivered_order
):
    _, item = delivered_order
    client = force_login(buyer_user)
    rr_id = client.post(RETURNS, {
        "order_item": str(item.id), "type": "return", "reason": "size_fit",
    }, format="json").data["id"]
    # Buyers may only cancel, not approve.
    r = client.patch(_status_url(rr_id), {"status": "approved"}, format="json")
    assert r.status_code == 403


def test_return_blocked_after_window_closes(
    force_login, buyer_user, delivered_order
):
    order, item = delivered_order
    order.delivered_at = timezone.now() - timezone.timedelta(days=30)
    order.save(update_fields=["delivered_at"])
    client = force_login(buyer_user)
    r = client.post(RETURNS, {
        "order_item": str(item.id), "type": "return", "reason": "defective",
    }, format="json")
    assert r.status_code == 400


def test_delivered_order_auto_closes_after_window(buyer_user, delivered_order):
    from orders.returns_service import (
        close_order_if_window_expired,
        item_return_eligible,
    )

    order, item = delivered_order
    # Push delivery beyond the 7-day product window.
    order.delivered_at = timezone.now() - timezone.timedelta(days=30)
    order.save(update_fields=["delivered_at"])

    assert close_order_if_window_expired(order) is True
    order.refresh_from_db()
    assert order.status == Order.Status.CLOSED
    # A closed order no longer offers return/exchange.
    assert item_return_eligible(item) is False


def test_closed_order_is_not_return_eligible(buyer_user, delivered_order):
    from orders.returns_service import item_return_eligible

    order, item = delivered_order
    order.status = Order.Status.CLOSED
    order.save(update_fields=["status"])
    assert item_return_eligible(item) is False


def test_exchange_flow_reaches_completed(
    force_login, buyer_user, seller_user, delivered_order
):
    _, item = delivered_order
    buyer = force_login(buyer_user)
    rr_id = buyer.post(RETURNS, {
        "order_item": str(item.id), "type": "exchange", "reason": "wrong_item",
        "quantity": 1,
    }, format="json").data["id"]

    seller = force_login(seller_user)
    for target in [
        "approved", "pickup_scheduled", "picked_up", "received",
        "exchange_shipped", "exchange_completed",
    ]:
        r = seller.patch(_status_url(rr_id), {"status": target}, format="json")
        assert r.status_code == 200, (target, r.content)
    assert ReturnRequest.objects.get(pk=rr_id).status == "exchange_completed"
