"""Return/exchange status state machine.

Seller-managed with admin override. `refunded`, `exchange_completed`,
`rejected` and `cancelled` are terminal. Type-appropriateness (a return may
only reach `refunded`, an exchange only `exchange_shipped`/`exchange_completed`)
is enforced in orders/returns_service.py, not by the graph alone.
"""

from __future__ import annotations

from orders.models import ReturnRequest

S = ReturnRequest.Status

# Non-terminal statuses — a return in one of these is still "in progress" and
# keeps occupying its order item (blocks a second request, and is what the
# order list surfaces as the row's effective status after delivery).
ACTIVE_STATUSES: set[str] = {
    S.REQUESTED, S.APPROVED, S.PICKUP_SCHEDULED, S.PICKED_UP, S.RECEIVED,
    S.EXCHANGE_SHIPPED,
}

RETURN_TRANSITIONS: dict[str, set[str]] = {
    S.REQUESTED: {S.APPROVED, S.REJECTED, S.CANCELLED},
    S.APPROVED: {S.PICKUP_SCHEDULED, S.REJECTED, S.CANCELLED},
    S.PICKUP_SCHEDULED: {S.PICKED_UP, S.REJECTED, S.CANCELLED},
    S.PICKED_UP: {S.RECEIVED},
    S.RECEIVED: {S.REFUNDED, S.EXCHANGE_SHIPPED, S.REJECTED},
    S.EXCHANGE_SHIPPED: {S.EXCHANGE_COMPLETED},
    S.REFUNDED: set(),
    S.EXCHANGE_COMPLETED: set(),
    S.REJECTED: set(),
    S.CANCELLED: set(),
}


class InvalidReturnTransitionError(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Cannot transition return from {current!r} to {target!r}"
        )
        self.current = current
        self.target = target


def can_transition(current: str, target: str) -> bool:
    return target in RETURN_TRANSITIONS.get(current, set())


def assert_return_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise InvalidReturnTransitionError(current, target)
