"""Inventory service: happy path, insufficient stock, concurrent reservations,
and low-stock alert firing.
"""

from __future__ import annotations

import threading
from decimal import Decimal
from unittest.mock import patch

import pytest

from products.inventory import (
    InsufficientInventoryError,
    release_inventory,
    reserve_inventory,
)
from products.models import Product


def _make_product(seller, tenant, *, count: int) -> Product:
    return Product.objects.create(
        tenant=tenant, seller=seller,
        sku=f"INV-{count}", name="Inventory test",
        description="x", price=Decimal("1.00"),
        inventory_count=count,
    )


def test_reserve_decrements(db, seller_user, tenant):
    product = _make_product(seller_user, tenant, count=10)
    new_count = reserve_inventory(str(product.pk), 3)
    assert new_count == 7


def test_reserve_raises_when_insufficient(db, seller_user, tenant):
    product = _make_product(seller_user, tenant, count=2)
    with pytest.raises(InsufficientInventoryError) as excinfo:
        reserve_inventory(str(product.pk), 5)
    assert excinfo.value.available == 2


def test_release_increments(db, seller_user, tenant):
    product = _make_product(seller_user, tenant, count=5)
    new_count = release_inventory(str(product.pk), 4)
    assert new_count == 9


def test_low_stock_alert_fires_below_threshold(
    db, seller_user, tenant, settings
):
    settings.LOW_STOCK_THRESHOLD = 3
    product = _make_product(seller_user, tenant, count=5)
    with patch("products.inventory.low_stock_alert") as alert:
        reserve_inventory(str(product.pk), 3)  # 5 -> 2
        alert.delay.assert_called_once_with(str(product.pk))


def test_low_stock_alert_not_fired_above_threshold(
    db, seller_user, tenant, settings
):
    settings.LOW_STOCK_THRESHOLD = 3
    product = _make_product(seller_user, tenant, count=10)
    with patch("products.inventory.low_stock_alert") as alert:
        reserve_inventory(str(product.pk), 1)
        alert.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Concurrency: 20 threads each try to reserve 1 from a count of 10.
# Exactly 10 should succeed, 10 should raise InsufficientInventoryError, and
# the final inventory_count must be 0 — not negative.
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_are_atomic(db, seller_user, tenant):
    product = _make_product(seller_user, tenant, count=10)
    successes = []
    failures = []

    def worker():
        from django.db import connection
        try:
            reserve_inventory(str(product.pk), 1)
            successes.append(1)
        except InsufficientInventoryError:
            failures.append(1)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    product.refresh_from_db()
    assert product.inventory_count == 0
    assert len(successes) == 10
    assert len(failures) == 10
