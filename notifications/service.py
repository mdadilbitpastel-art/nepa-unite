"""Unified notification service: in-app row + email via Celery (AWS SES)."""

from __future__ import annotations

from notifications.models import Notification
from notifications.tasks import send_ses_email


def notify(
    *,
    recipient,
    kind: str,
    title: str,
    body: str = "",
    payload: dict | None = None,
    send_email: bool = True,
) -> Notification:
    """Persist an in-app notification and optionally send an email.

    Email goes via SES (Celery), so the caller's request stays fast.
    """
    note = Notification.objects.create(
        recipient=recipient,
        kind=kind,
        title=title,
        body=body,
        payload=payload or {},
    )
    if send_email and recipient.email:
        send_ses_email.delay(
            to_email=recipient.email,
            subject=title,
            body=body or title,
        )
    return note


def notify_order_status_change(*, order, new_status: str) -> None:
    """Send the buyer + each seller a notification when an order moves."""
    title = f"Order #{order.id} is now {new_status}"
    body = title
    notify(
        recipient=order.buyer,
        kind=Notification.Kind.ORDER_STATUS,
        title=title,
        body=body,
        payload={"order_id": str(order.id), "status": new_status},
    )
    seller_ids = (
        order.items.values_list("seller_id", flat=True).distinct()
    )
    from users.models import CustomUser
    for seller in CustomUser.objects.filter(pk__in=list(seller_ids)):
        notify(
            recipient=seller,
            kind=Notification.Kind.ORDER_STATUS,
            title=title,
            body=body,
            payload={"order_id": str(order.id), "status": new_status},
        )
