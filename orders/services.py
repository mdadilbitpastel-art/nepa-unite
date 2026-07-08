"""Order creation + status transitions — both wrap the inventory service."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.dispatch import run_in_background
from core.tasks import write_audit_log
from notifications.service import notify_order_status_change
from notifications.tasks import send_new_order_notification, send_order_status_email
from orders.models import Order, OrderActivityLog, OrderItem
from orders.state import assert_transition
from products.inventory import (
    InsufficientInventoryError,
    release_inventory,
    reserve_inventory,
)
from products.models import Product
from webhooks.tasks import emit_platform_event


class OrderCreationError(Exception):
    pass


REQUIRED_SHIPPING_FIELDS = [
    "shipping_name",
    "shipping_phone",
    "shipping_address_line1",
    "shipping_city",
    "shipping_state",
    "shipping_zip",
]


@transaction.atomic
def create_order(*, buyer, items: list[dict], shipping: dict | None = None) -> Order:
    """Create an Order + OrderItems, reserving inventory as we go.

    Each item is {"product_id": str, "quantity": int}. We resolve each product
    by id (must be active), reserve the requested quantity, and snapshot the
    unit price into the order item.

    On any failure during the loop, the transaction rolls back and any
    successfully-reserved inventory is released to keep counts honest.
    """
    if not items:
        raise OrderCreationError("Order must contain at least one item.")

    shipping = shipping or {}
    missing = [f for f in REQUIRED_SHIPPING_FIELDS if not shipping.get(f, "").strip()]
    if missing:
        raise OrderCreationError(f"Missing required shipping fields: {', '.join(missing)}")

    products: dict[str, Product] = {}
    for entry in items:
        pid = entry.get("product_id")
        try:
            product = Product.objects.select_related("seller").get(pk=pid)
        except Product.DoesNotExist:
            raise OrderCreationError(f"Product {pid} not found.")
        if product.status != Product.Status.ACTIVE:
            raise OrderCreationError(f"Product {pid} is not active.")
        products[str(pid)] = product

    order = Order.objects.create(
        buyer=buyer,
        tenant=buyer.tenant,
        shipping_name=shipping.get("shipping_name", "").strip(),
        shipping_phone=shipping.get("shipping_phone", "").strip(),
        shipping_address_line1=shipping.get("shipping_address_line1", "").strip(),
        shipping_address_line2=shipping.get("shipping_address_line2", "").strip(),
        shipping_city=shipping.get("shipping_city", "").strip(),
        shipping_state=shipping.get("shipping_state", "").strip(),
        shipping_zip=shipping.get("shipping_zip", "").strip(),
        buyer_notes=shipping.get("buyer_notes", "").strip(),
    )

    reserved: list[tuple[str, int]] = []
    total = Decimal("0.00")
    try:
        for entry in items:
            pid = str(entry["product_id"])
            qty = int(entry["quantity"])
            if qty <= 0:
                raise OrderCreationError("Quantity must be positive.")
            product = products[pid]
            if qty < product.min_order_qty:
                raise OrderCreationError(
                    f"{product.name} requires a minimum order of {product.min_order_qty} units."
                )
            reserve_inventory(pid, qty)
            reserved.append((pid, qty))
            OrderItem.objects.create(
                order=order,
                product=product,
                seller=product.seller,
                quantity=qty,
                unit_price=product.price,
            )
            total += Decimal(qty) * product.price
    except InsufficientInventoryError as exc:
        # Release whatever we did reserve before re-raising.
        for pid, qty in reserved:
            try:
                release_inventory(pid, qty)
            except Exception:  # noqa: BLE001
                pass
        raise OrderCreationError(str(exc))
    except Exception:
        for pid, qty in reserved:
            try:
                release_inventory(pid, qty)
            except Exception:  # noqa: BLE001
                pass
        raise

    order.total_amount = total
    order.save(update_fields=["total_amount", "updated_at"])
    return order


@transaction.atomic
def transition_order(*, order: Order, target_status: str, actor, note: str = "") -> Order:
    """Move `order` to `target_status` if allowed; release inventory on cancel."""
    assert_transition(order.status, target_status)

    if target_status == Order.Status.CANCELLED:
        for item in order.items.all():
            try:
                release_inventory(str(item.product_id), item.quantity)
            except Exception:  # noqa: BLE001 - we still want to mark cancelled
                pass
        order.items.exclude(
            fulfillment_status=OrderItem.FulfillmentStatus.CANCELLED
        ).update(fulfillment_status=OrderItem.FulfillmentStatus.CANCELLED)

    if target_status in (Order.Status.FULFILLMENT, Order.Status.SHIPPED,
                         Order.Status.DELIVERED, Order.Status.CLOSED):
        order.items.filter(
            fulfillment_status=OrderItem.FulfillmentStatus.PENDING
        ).update(fulfillment_status=OrderItem.FulfillmentStatus.FULFILLED)

    # Commission ledger follows the order lifecycle: realized once delivered,
    # reversed if the order is cancelled. Both calls are idempotent and no-op
    # when no commission was accrued (e.g. cancelled before payment).
    from commissions.services import earn_for_order, reverse_for_order
    if target_status == Order.Status.DELIVERED:
        earn_for_order(order)
    elif target_status == Order.Status.CANCELLED:
        reverse_for_order(order)

    previous = order.status
    order.status = target_status
    order.status_changed_at = timezone.now()
    update_fields = ["status", "status_changed_at", "updated_at"]
    # Stamp the delivery time once — anchors the per-item return window.
    if target_status == Order.Status.DELIVERED and order.delivered_at is None:
        order.delivered_at = timezone.now()
        update_fields.append("delivered_at")
    order.save(update_fields=update_fields)

    OrderActivityLog.objects.create(
        order=order,
        actor=actor,
        from_status=previous,
        to_status=target_status,
        note=note,
    )

    order_pk = str(order.pk)
    actor_pk = str(actor.pk) if actor else None
    actor_role = getattr(actor, "role", "")
    seller_emails = list(
        order.items.values_list("seller__email", flat=True).distinct()
    )
    order_total = str(order.total_amount)

    def _side_effects():
        write_audit_log.delay(
            actor_id=actor_pk,
            action="order.status_transition",
            entity_type="Order",
            entity_id=order_pk,
            payload={"from": previous, "to": target_status},
        )
        emit_platform_event.delay(
            event_type=f"order.{target_status}",
            payload={"order_id": order_pk, "status": target_status},
        )
        try:
            notify_order_status_change(order=order, new_status=target_status)
        except Exception:  # noqa: BLE001
            pass
        if target_status == Order.Status.CONFIRMED:
            for email in seller_emails:
                send_new_order_notification.delay(email, order_pk, order_total)
        elif actor_role == "admin" and note:
            for email in seller_emails:
                send_order_status_email.delay(email, order_pk, target_status, note)
        if target_status == Order.Status.DELIVERED:
            try:
                from payments.tasks import generate_invoice_pdf
                generate_invoice_pdf.delay(order_pk)
            except Exception:  # noqa: BLE001
                pass

    def _post_commit():
        # With a Celery worker these .delay() calls are async and cheap. Without
        # one (eager mode on single-service deploys) they run synchronously —
        # SMTP/webhooks/PDFs would block the HTTP response and leave the browser
        # spinning after the status is already committed. Push them off-thread.
        if settings.CELERY_TASK_ALWAYS_EAGER:
            run_in_background(_side_effects)
        else:
            _side_effects()

    transaction.on_commit(_post_commit)
    return order
