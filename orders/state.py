"""Order status state machine.

An order may be cancelled only up to (and including) `shipped` — i.e. any time
*before* it is delivered. Once it reaches `delivered`, cancellation is no longer
possible; the buyer's recourse is the return/exchange flow (see
orders/returns_state.py), and the order can only move on to `closed`. Otherwise
only the explicitly-listed forward transitions are allowed.
"""

from __future__ import annotations

from orders.models import Order


TRANSITIONS: dict[str, set[str]] = {
    Order.Status.DRAFT: {Order.Status.CONFIRMED, Order.Status.CANCELLED},
    Order.Status.CONFIRMED: {Order.Status.FULFILLMENT, Order.Status.CANCELLED},
    Order.Status.FULFILLMENT: {Order.Status.SHIPPED, Order.Status.CANCELLED},
    Order.Status.SHIPPED: {Order.Status.DELIVERED, Order.Status.CANCELLED},
    # Delivered is past the point of no cancel — only forward to closed.
    Order.Status.DELIVERED: {Order.Status.CLOSED},
    Order.Status.CLOSED: set(),
    Order.Status.CANCELLED: set(),
}


class InvalidTransitionError(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Cannot transition order from {current!r} to {target!r}")
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def assert_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
