"""Return/exchange business logic — creation + seller/admin-managed lifecycle.

Kept separate from orders/services.py (order lifecycle) so the two state
machines stay independent. All money/inventory side-effects run inside the
transaction; buyer/seller notifications fire after commit.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from notifications.models import Notification
from notifications.service import notify
from orders.models import Order, OrderItem, ReturnEvent, ReturnRequest
from orders.returns_state import ACTIVE_STATUSES as _ACTIVE_STATUSES
from orders.returns_state import assert_return_transition
from products.inventory import release_inventory, reserve_inventory

S = ReturnRequest.Status


def relevant_return_for_order(order: Order):
    """The return/exchange that best represents an order in a list row.

    Prefers the most recent still-in-progress request; falls back to the most
    recent overall. Returns None when the order has no returns. Reuses the
    prefetched, Meta-ordered (newest-first) `returns` set, so it adds no query
    when `returns` is prefetched.
    """
    returns = list(order.returns.all())
    if not returns:
        return None
    active = [r for r in returns if r.status in _ACTIVE_STATUSES]
    return active[0] if active else returns[0]


def order_effective_status(order: Order) -> dict:
    """The single status a list row should show for an order.

    Before delivery it is the order's own status. Once delivered/closed and a
    return/exchange exists, it surfaces that (e.g. "Pickup scheduled",
    "Refunded", "Replacement shipped") so the row reflects what is actually
    happening. `kind` is "order", "return" or "exchange" so the UI can colour
    the badge accordingly.
    """
    rr = relevant_return_for_order(order)
    if rr is not None and order.status in (
        Order.Status.DELIVERED, Order.Status.CLOSED
    ):
        return {
            "code": rr.status,
            "label": rr.get_status_display(),
            # Single self-contained label for a list row, e.g. "Exchange
            # requested", "Return rejected" — the type + the return status.
            "full_label": f"{rr.get_type_display()} {rr.get_status_display().lower()}",
            "kind": rr.type,             # "return" | "exchange"
            "return_id": str(rr.id),
            "order_status": order.status,
        }
    return {
        "code": order.status,
        "label": order.get_status_display(),
        "full_label": order.get_status_display(),
        "kind": "order",
        "return_id": None,
        "order_status": order.status,
    }


def item_return_window_open(order_item: OrderItem) -> bool:
    """True if the item's order is delivered and still inside the window.

    Only a `delivered` order qualifies — once it is `closed` the return /
    exchange validity is over and the option disappears.
    """
    order = order_item.order
    if order.status != Order.Status.DELIVERED:
        return False
    if order.delivered_at is None:
        return False
    days = order_item.product.return_window_days or 0
    deadline = order.delivered_at + timezone.timedelta(days=days)
    return timezone.now() <= deadline


def order_return_deadline(order: Order):
    """Latest per-item return-window deadline for the order (or None).

    An order can close only after EVERY item's window has elapsed, so we take
    the max window across items that are returnable/exchangeable.
    """
    if order.delivered_at is None:
        return None
    windows = [
        (i.product.return_window_days or 0)
        for i in order.items.all()
        if i.product.is_returnable or i.product.is_exchangeable
    ]
    # Nothing returnable → the window is effectively zero from delivery.
    max_days = max(windows) if windows else 0
    return order.delivered_at + timezone.timedelta(days=max_days)


def order_window_expired(order: Order) -> bool:
    """True when a delivered order is past its return/exchange validity."""
    if order.status != Order.Status.DELIVERED:
        return False
    deadline = order_return_deadline(order)
    return deadline is not None and timezone.now() > deadline


def close_order_if_window_expired(order: Order, actor=None) -> bool:
    """Auto-close a delivered order once its return validity has elapsed.

    Called lazily on order reads and in bulk by the periodic task, so the
    order flips to `closed` (and the return option disappears) right after the
    window ends without requiring a scheduler.
    """
    if not order_window_expired(order):
        return False
    from orders.services import transition_order
    try:
        transition_order(
            order=order,
            target_status=Order.Status.CLOSED,
            actor=actor,
            note="Return/exchange window elapsed",
        )
        return True
    except Exception:  # noqa: BLE001 - never break a read on close failure
        return False


def item_return_eligible(order_item: OrderItem) -> bool:
    """Whether a buyer may still raise a return/exchange for this item."""
    product = order_item.product
    if not (product.is_returnable or product.is_exchangeable):
        return False
    if order_item.fulfillment_status == OrderItem.FulfillmentStatus.CANCELLED:
        return False
    if not item_return_window_open(order_item):
        return False
    return not order_item.returns.filter(status__in=_ACTIVE_STATUSES).exists()


@transaction.atomic
def create_return(
    *,
    buyer,
    order_item: OrderItem,
    type: str,
    reason: str,
    reason_note: str = "",
    quantity: int = 1,
    exchange_product=None,
) -> ReturnRequest:
    """Validate and open a return/exchange for one order item."""
    order = order_item.order
    if order.buyer_id != buyer.pk:
        raise PermissionDenied("You can only return items from your own orders.")

    product = order_item.product
    if type == ReturnRequest.Type.EXCHANGE and not product.is_exchangeable:
        raise ValidationError("This product is not eligible for exchange.")
    if type == ReturnRequest.Type.RETURN and not product.is_returnable:
        raise ValidationError("This product is not eligible for return.")
    if not item_return_window_open(order_item):
        raise ValidationError(
            "The return window for this item has closed or the order "
            "has not been delivered yet."
        )
    if order_item.returns.filter(status__in=_ACTIVE_STATUSES).exists():
        raise ValidationError("An active return already exists for this item.")
    if quantity < 1 or quantity > order_item.quantity:
        raise ValidationError(
            f"Quantity must be between 1 and {order_item.quantity}."
        )

    is_return = type == ReturnRequest.Type.RETURN
    refund_amount = (
        (order_item.unit_price * quantity) if is_return else Decimal("0.00")
    )
    if type == ReturnRequest.Type.EXCHANGE and exchange_product is None:
        exchange_product = product  # default: swap for the same product

    rr = ReturnRequest.objects.create(
        order=order,
        order_item=order_item,
        buyer=buyer,
        seller=order_item.seller,
        tenant=order.tenant,
        type=type,
        reason=reason,
        reason_note=reason_note,
        quantity=quantity,
        refund_amount=refund_amount,
        exchange_product=exchange_product if not is_return else None,
        status=S.REQUESTED,
    )
    ReturnEvent.objects.create(
        return_request=rr, actor=buyer, from_status="", to_status=S.REQUESTED,
        note=reason_note,
    )

    def _notify():
        notify(
            recipient=rr.seller,
            kind=Notification.Kind.RETURN,
            title=f"New {type} request for {product.name}",
            body=f"A buyer raised a {type} ({reason}) for order #{order.id}.",
            payload={"return_id": str(rr.pk), "order_id": str(order.pk)},
        )

    transaction.on_commit(_notify)
    return rr


def _require_type(rr: ReturnRequest, target: str) -> None:
    if target == S.REFUNDED and rr.type != ReturnRequest.Type.RETURN:
        raise ValidationError("Only a return can be refunded.")
    if target in (S.EXCHANGE_SHIPPED, S.EXCHANGE_COMPLETED) and (
        rr.type != ReturnRequest.Type.EXCHANGE
    ):
        raise ValidationError("Only an exchange can be shipped/completed.")


@transaction.atomic
def transition_return(
    *,
    return_request: ReturnRequest,
    target_status: str,
    actor,
    note: str = "",
    pickup_scheduled_at=None,
) -> ReturnRequest:
    """Advance a return through its lifecycle, running money/stock effects."""
    rr = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)
    assert_return_transition(rr.status, target_status)
    _require_type(rr, target_status)

    previous = rr.status
    update_fields = ["status", "status_changed_at", "updated_at"]

    if target_status == S.PICKUP_SCHEDULED:
        rr.pickup_scheduled_at = pickup_scheduled_at or timezone.now()
        update_fields.append("pickup_scheduled_at")

    if target_status == S.REFUNDED:
        from payments.stripe_service import create_return_refund
        rr.stripe_refund_id = create_return_refund(rr) or ""
        update_fields.append("stripe_refund_id")
        # Returned units go back on the shelf.
        try:
            release_inventory(str(rr.order_item.product_id), rr.quantity)
        except Exception:  # noqa: BLE001
            pass

    if target_status == S.EXCHANGE_SHIPPED:
        # Restock the returned unit, reserve the replacement.
        try:
            release_inventory(str(rr.order_item.product_id), rr.quantity)
        except Exception:  # noqa: BLE001
            pass
        if rr.exchange_product_id:
            try:
                reserve_inventory(str(rr.exchange_product_id), rr.quantity)
            except Exception:  # noqa: BLE001
                pass

    if note and target_status in (S.REJECTED, S.APPROVED, S.RECEIVED):
        rr.resolution_note = note
        update_fields.append("resolution_note")

    rr.status = target_status
    rr.status_changed_at = timezone.now()
    rr.save(update_fields=update_fields)

    ReturnEvent.objects.create(
        return_request=rr, actor=actor, from_status=previous,
        to_status=target_status, note=note,
    )

    # Notify the counterparty: buyer-driven cancel notifies the seller;
    # every seller/admin action notifies the buyer.
    actor_role = getattr(actor, "role", "")
    recipient = rr.seller if actor_role == "buyer" else rr.buyer
    order_id = str(rr.order_id)
    rr_id = str(rr.pk)
    label = rr.get_status_display()

    def _notify():
        notify(
            recipient=recipient,
            kind=Notification.Kind.RETURN,
            title=f"{rr.type.title()} #{rr_id[:8]} is now {label}",
            body=f"Your {rr.type} for order #{order_id} was updated to {label}.",
            payload={"return_id": rr_id, "order_id": order_id,
                     "status": target_status},
        )

    transaction.on_commit(_notify)
    return rr
