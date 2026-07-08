"""Commission schedule, ledger lifecycle, and admin API tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from commissions import services
from commissions.models import Commission, CommissionRate
from orders.models import Order, OrderItem
from products.models import Product


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def product(db, seller_user, tenant):
    return Product.objects.create(
        tenant=tenant, seller=seller_user, sku="COMM-1", name="Drill",
        description="x", price=Decimal("50.00"), inventory_count=100,
        attributes={"category": "Power Tools"},
    )


@pytest.fixture
def order(db, buyer_user, tenant, product, seller_user):
    o = Order.objects.create(
        buyer=buyer_user, tenant=tenant, total_amount=Decimal("100.00"),
    )
    OrderItem.objects.create(
        order=o, product=product, seller=seller_user,
        quantity=2, unit_price=Decimal("50.00"),
    )
    return o


# ---------------------------------------------------------------------------
# Rate resolution + computation
# ---------------------------------------------------------------------------
def test_no_rate_means_commission_free(db):
    # No CommissionRate row for the category => 0% (free).
    percent, amount = services.compute_commission("Power Tools", Decimal("100.00"))
    assert percent == Decimal("0")
    assert amount == Decimal("0.00")


def test_category_rate_overrides_default(db):
    CommissionRate.objects.create(category="Power Tools", percent=Decimal("12.00"))
    percent, amount = services.compute_commission("Power Tools", Decimal("100.00"))
    assert percent == Decimal("12.00")
    assert amount == Decimal("12.00")


def test_inactive_rate_is_commission_free(db):
    CommissionRate.objects.create(
        category="Power Tools", percent=Decimal("12.00"), is_active=False
    )
    percent, amount = services.compute_commission("Power Tools", Decimal("100.00"))
    assert percent == Decimal("0")
    assert amount == Decimal("0.00")


def test_min_fee_floor_applied(db):
    CommissionRate.objects.create(
        category="Power Tools", percent=Decimal("1.00"), min_fee=Decimal("3.00")
    )
    _, amount = services.compute_commission("Power Tools", Decimal("100.00"))
    # 1% of 100 = 1.00, floored up to the 3.00 minimum.
    assert amount == Decimal("3.00")


# ---------------------------------------------------------------------------
# Ledger lifecycle
# ---------------------------------------------------------------------------
def test_accrue_creates_pending_commission_per_item(db, order):
    CommissionRate.objects.create(category="Power Tools", percent=Decimal("10.00"))
    created = services.accrue_for_order(order)
    assert len(created) == 1
    comm = Commission.objects.get(order=order)
    assert comm.status == Commission.Status.PENDING
    assert comm.base_amount == Decimal("100.00")
    assert comm.rate_percent == Decimal("10.00")
    assert comm.commission_amount == Decimal("10.00")
    assert comm.category == "Power Tools"


def test_accrue_is_idempotent(db, order):
    services.accrue_for_order(order)
    services.accrue_for_order(order)
    assert Commission.objects.filter(order=order).count() == 1


def test_earn_marks_delivered(db, order):
    services.accrue_for_order(order)
    updated = services.earn_for_order(order)
    assert updated == 1
    comm = Commission.objects.get(order=order)
    assert comm.status == Commission.Status.EARNED
    assert comm.earned_at is not None


def test_reverse_marks_reversed(db, order):
    services.accrue_for_order(order)
    services.earn_for_order(order)
    updated = services.reverse_for_order(order)
    assert updated == 1
    comm = Commission.objects.get(order=order)
    assert comm.status == Commission.Status.REVERSED
    assert comm.reversed_at is not None


def test_commission_earned_on_close_not_delivery(db, order, admin_user):
    """Commission is realized only when the order CLOSES (after the return
    window), not at delivery — end-to-end through the order state machine."""
    from orders.services import transition_order
    services.accrue_for_order(order)
    order.status = Order.Status.SHIPPED
    order.save(update_fields=["status"])
    transition_order(order=order, target_status=Order.Status.DELIVERED, actor=admin_user)
    # Still pending during the return/exchange window.
    assert Commission.objects.get(order=order).status == Commission.Status.PENDING
    transition_order(order=order, target_status=Order.Status.CLOSED, actor=admin_user)
    assert Commission.objects.get(order=order).status == Commission.Status.EARNED


def test_reverse_for_item_reverses_single_commission(db, order):
    """A refunded item's commission is reversed so it never earns at close."""
    services.accrue_for_order(order)
    item = order.items.first()
    updated = services.reverse_for_item(item)
    assert updated == 1
    comm = Commission.objects.get(order_item=item)
    assert comm.status == Commission.Status.REVERSED
    assert comm.reversed_at is not None


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------
def test_commission_list_admin_only(db, force_login, buyer_user):
    client = force_login(buyer_user)
    assert client.get("/api/v1/commissions/").status_code == 403


def test_commission_list_and_summary(db, order, admin_user, force_login):
    CommissionRate.objects.create(category="Power Tools", percent=Decimal("10.00"))
    services.accrue_for_order(order)
    services.earn_for_order(order)
    client = force_login(admin_user)

    resp = client.get("/api/v1/commissions/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["commission_amount"] == "10.00"

    summary = client.get("/api/v1/commissions/summary/")
    assert summary.status_code == 200
    body = summary.json()
    assert body["earned"]["count"] == 1
    assert body["earned_total"] == "10.00"


def test_admin_can_manage_rates(db, admin_user, force_login):
    client = force_login(admin_user)
    resp = client.post(
        "/api/v1/commissions/rates/",
        {"category": "Implants", "percent": "15.00", "min_fee": "2.00"},
        format="json",
    )
    assert resp.status_code == 201
    rate_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/commissions/rates/{rate_id}/", {"percent": "18.00"}, format="json"
    )
    assert resp.status_code == 200
    assert CommissionRate.objects.get(pk=rate_id).percent == Decimal("18.00")

    assert client.delete(f"/api/v1/commissions/rates/{rate_id}/").status_code == 204


def test_rates_forbidden_for_seller(db, seller_user, force_login):
    client = force_login(seller_user)
    assert client.get("/api/v1/commissions/rates/").status_code == 403


# ---------------------------------------------------------------------------
# Dashboard HTML page
# ---------------------------------------------------------------------------
def test_dashboard_commissions_page_renders_for_admin(client, db, order, admin_user):
    CommissionRate.objects.create(category="Power Tools", percent=Decimal("10.00"))
    services.accrue_for_order(order)
    services.earn_for_order(order)
    client.force_login(admin_user)
    resp = client.get("/dashboard/commissions/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Earned commission" in body
    assert "Power Tools" in body


def test_dashboard_commissions_page_redirects_non_admin(client, db, seller_user):
    client.force_login(seller_user)
    resp = client.get("/dashboard/commissions/")
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Commission rates management page
# ---------------------------------------------------------------------------
def test_rates_page_renders_for_admin(client, db, admin_user):
    CommissionRate.objects.create(category="Lighting", percent=Decimal("8.00"))
    client.force_login(admin_user)
    resp = client.get("/dashboard/commissions/rates/")
    assert resp.status_code == 200
    assert "Lighting" in resp.content.decode()


def test_rates_page_inline_edit(client, db, admin_user):
    rate = CommissionRate.objects.create(category="Lighting", percent=Decimal("8.00"))
    client.force_login(admin_user)
    resp = client.post(
        "/dashboard/commissions/rates/",
        {"rate_id": str(rate.id), "percent": "12.5", "min_fee": "1.00", "is_active": "on"},
    )
    assert resp.status_code == 302
    rate.refresh_from_db()
    assert rate.percent == Decimal("12.5")
    assert rate.min_fee == Decimal("1.00")
    assert rate.is_active is True


def test_rates_page_add_new(client, db, admin_user):
    client.force_login(admin_user)
    resp = client.post(
        "/dashboard/commissions/rates/",
        {"action": "add", "category": "Brand New Cat", "percent": "9", "min_fee": "0"},
    )
    assert resp.status_code == 302
    assert CommissionRate.objects.filter(category="Brand New Cat").exists()


def test_rates_page_rejects_bad_percent(client, db, admin_user):
    rate = CommissionRate.objects.create(category="Lighting", percent=Decimal("8.00"))
    client.force_login(admin_user)
    client.post(
        "/dashboard/commissions/rates/",
        {"rate_id": str(rate.id), "percent": "150", "min_fee": "0"},
    )
    rate.refresh_from_db()
    assert rate.percent == Decimal("8.00")  # unchanged — out of range


def test_rates_page_forbidden_for_non_admin(client, db, seller_user):
    client.force_login(seller_user)
    assert client.get("/dashboard/commissions/rates/").status_code == 302


def test_rates_bulk_set_all(client, db, admin_user):
    for cat in ("Lighting", "Fixtures", "Plumbing"):
        CommissionRate.objects.create(category=cat, percent=Decimal("8.00"))
    client.force_login(admin_user)
    resp = client.post(
        "/dashboard/commissions/rates/", {"action": "set_all", "percent": "10"}
    )
    assert resp.status_code == 302
    percents = set(CommissionRate.objects.values_list("percent", flat=True))
    assert percents == {Decimal("10.00")}


def test_order_detail_shows_earnings_for_admin(client, db, admin_user, order):
    CommissionRate.objects.create(category="Power Tools", percent=Decimal("10.00"))
    services.accrue_for_order(order)
    client.force_login(admin_user)
    resp = client.get(f"/dashboard/orders/{order.id}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Earnings breakdown" in body
    assert "Seller net" in body


def test_order_detail_hides_earnings_for_buyer(client, db, buyer_user, order):
    client.force_login(buyer_user)
    resp = client.get(f"/dashboard/orders/{order.id}/")
    assert resp.status_code == 200
    assert "Earnings breakdown" not in resp.content.decode()


def test_rates_bulk_set_respects_search_filter(client, db, admin_user):
    CommissionRate.objects.create(category="Power Tools", percent=Decimal("8.00"))
    CommissionRate.objects.create(category="Lighting", percent=Decimal("8.00"))
    client.force_login(admin_user)
    # Only "Tools" matches the ?q filter.
    client.post(
        "/dashboard/commissions/rates/?q=tool",
        {"action": "set_all", "percent": "15"},
    )
    assert CommissionRate.objects.get(category="Power Tools").percent == Decimal("15.00")
    assert CommissionRate.objects.get(category="Lighting").percent == Decimal("8.00")
