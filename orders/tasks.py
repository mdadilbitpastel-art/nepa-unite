"""Background tasks for the orders app."""

from celery import shared_task


@shared_task
def recalculate_order_total(order_id: str) -> None:  # pragma: no cover
    return None


@shared_task
def close_expired_return_windows() -> int:
    """Close every delivered order whose return/exchange window has elapsed.

    Idempotent — safe to run on any schedule. Returns the number of orders
    closed. Also invoked lazily on order reads (see OrderViewSet.retrieve), so
    orders still close on time even without a beat scheduler running.
    """
    from orders.models import Order
    from orders.returns_service import close_order_if_window_expired

    closed = 0
    qs = Order.objects.filter(
        status=Order.Status.DELIVERED, delivered_at__isnull=False
    ).prefetch_related("items__product")
    for order in qs:
        if close_order_if_window_expired(order):
            closed += 1
    return closed
