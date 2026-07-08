"""Unified notification service: in-app row + email via Celery (AWS SES)."""

from __future__ import annotations

from django.conf import settings

from notifications.models import Notification
from notifications.tasks import send_ses_email


def _dispatch_email(*, to_email: str, subject: str, body: str) -> None:
    """Send the SES email without ever blocking the request.

    With a real Celery worker ``.delay()`` is already async. On single-service
    deploys (no worker → eager mode) ``.delay()`` would run the SES call
    synchronously inside the request, making actions like raising or approving a
    return feel slow/stuck. In that case we push it onto a background thread so
    the HTTP response returns immediately and the UI updates without a reload.
    """
    if settings.CELERY_TASK_ALWAYS_EAGER:
        from core.dispatch import run_in_background

        run_in_background(
            send_ses_email.delay, to_email=to_email, subject=subject, body=body
        )
    else:
        send_ses_email.delay(to_email=to_email, subject=subject, body=body)


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

    Email goes via SES off the request path, so the caller's request stays fast.
    """
    note = Notification.objects.create(
        recipient=recipient,
        kind=kind,
        title=title,
        body=body,
        payload=payload or {},
    )
    if send_email and recipient.email:
        _dispatch_email(to_email=recipient.email, subject=title, body=body or title)
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
