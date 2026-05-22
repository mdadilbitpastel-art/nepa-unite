"""Order status state machine.

Each non-terminal state can transition to `cancelled`. Otherwise only the
explicitly-listed forward transitions are allowed.
"""

from __future__ import annotations

from orders.models import Order


TRANSITIONS: dict[str, set[str]] = {
    Order.Status.DRAFT: {Order.Status.CONFIRMED, Order.Status.CANCELLED},
    Order.Status.CONFIRMED: {Order.Status.FULFILLMENT, Order.Status.CANCELLED},
    Order.Status.FULFILLMENT: {Order.Status.SHIPPED, Order.Status.CANCELLED},
    Order.Status.SHIPPED: {Order.Status.DELIVERED, Order.Status.CANCELLED},
    Order.Status.DELIVERED: {Order.Status.CLOSED, Order.Status.CANCELLED},
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
