"""Background tasks for the orders app. (Placeholder — to be filled in.)"""

from celery import shared_task


@shared_task
def recalculate_order_total(order_id: str) -> None:  # pragma: no cover
    return None
