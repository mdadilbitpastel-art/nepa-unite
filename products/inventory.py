"""Atomic inventory reservation / release backed by a Redis distributed lock.

We hold a per-product Redis lock (SET NX EX) around the read-decrement-write,
because PostgreSQL row-level locking alone won't help us coordinate across
multiple Django workers when the same item is hot.

Counter-intuitively, the lock guards the *Python-side* check; the DB still
has the inventory_count >= 0 CHECK constraint as the ultimate guarantee.
"""

from __future__ import annotations

import time
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django_redis import get_redis_connection

from core.dispatch import safe_dispatch
from products.models import Product
from products.tasks import low_stock_alert


class InsufficientInventoryError(Exception):
    def __init__(self, product_id: str, requested: int, available: int) -> None:
        super().__init__(
            f"Insufficient inventory for {product_id}: "
            f"requested={requested}, available={available}"
        )
        self.product_id = product_id
        self.requested = requested
        self.available = available


class LockAcquireError(Exception):
    pass


# Sentinel returned when no distributed lock is taken (single-service deploy
# with no Redis). The DB row lock (select_for_update) plus the
# inventory_count >= 0 CHECK constraint are sufficient with a single worker.
_NO_LOCK = "__no_redis_lock__"


def _redis_enabled() -> bool:
    return bool(getattr(settings, "REDIS_URL", ""))


def _lock_key(product_id: str) -> str:
    return f"lock:inventory:{product_id}"


def _acquire(product_id: str, ttl: int, wait_seconds: float = 2.0) -> str | None:
    """Acquire a redis lock; returns a token to use on release, or None on timeout.

    When Redis isn't configured (no REDIS_URL), skip the distributed lock and
    return a sentinel — the surrounding transaction's select_for_update still
    serialises concurrent decrements on a single worker.
    """
    if not _redis_enabled():
        return _NO_LOCK
    client = get_redis_connection("default")
    token = uuid.uuid4().hex
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if client.set(_lock_key(product_id), token, nx=True, ex=ttl):
            return token
        time.sleep(0.02)
    return None


def _release(product_id: str, token: str) -> None:
    """Release only if we still own the lock (Lua-equivalent guard)."""
    if token == _NO_LOCK or not _redis_enabled():
        return
    client = get_redis_connection("default")
    lua = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('del', KEYS[1]) else return 0 end"
    )
    client.eval(lua, 1, _lock_key(product_id), token)


@transaction.atomic
def reserve_inventory(product_id: str, quantity: int) -> int:
    """Decrement inventory atomically; returns the new count.

    Raises InsufficientInventoryError if not enough is in stock.
    """
    if quantity <= 0:
        raise ValueError("quantity must be > 0")

    token = _acquire(product_id, settings.INVENTORY_LOCK_TTL)
    if token is None:
        raise LockAcquireError(f"Could not acquire inventory lock for {product_id}")
    try:
        product = Product.objects.select_for_update().get(pk=product_id)
        if product.status != Product.Status.ACTIVE:
            raise InsufficientInventoryError(product_id, quantity, 0)
        if product.inventory_count < quantity:
            raise InsufficientInventoryError(
                product_id, quantity, product.inventory_count
            )
        product.inventory_count = F("inventory_count") - quantity
        product.save(update_fields=["inventory_count", "updated_at"])
        product.refresh_from_db(fields=["inventory_count"])
        if product.inventory_count < settings.LOW_STOCK_THRESHOLD:
            safe_dispatch(low_stock_alert, str(product.pk))
        return product.inventory_count
    finally:
        _release(product_id, token)


@transaction.atomic
def release_inventory(product_id: str, quantity: int) -> int:
    """Increment inventory atomically (e.g. on order cancel/refund)."""
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    token = _acquire(product_id, settings.INVENTORY_LOCK_TTL)
    if token is None:
        raise LockAcquireError(f"Could not acquire inventory lock for {product_id}")
    try:
        product = Product.objects.select_for_update().get(pk=product_id)
        product.inventory_count = F("inventory_count") + quantity
        product.save(update_fields=["inventory_count", "updated_at"])
        product.refresh_from_db(fields=["inventory_count"])
        return product.inventory_count
    finally:
        _release(product_id, token)
