"""Order creation + status transitions — both wrap the inventory service."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from core.tasks import write_audit_log
from notifications.service import notify_order_status_change
from orders.models import Order, OrderItem
from orders.state import assert_transition
from products.inventory import InsufficientInventoryError, release_inventory, reserve_inventory
from products.models import Product


class OrderCreationError(Exception):
    pass


@transaction.atomic
def create_order(*, buyer, items: list[dict]) -> Order:
    """Create an Order + OrderItems, reserving inventory as we go.

    Each item is {"product_id": str, "quantity": int}. We resolve each product
    by id (must be active), reserve the requested quantity, and snapshot the
    unit price into the order item.

    On any failure during the loop, the transaction rolls back and any
    successfully-reserved inventory is released to keep counts honest.
    """
    if not items:
        raise OrderCreationError("Order must contain at least one item.")

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

    order = Order.objects.create(buyer=buyer, tenant=buyer.tenant)

    reserved: list[tuple[str, int]] = []
    total = Decimal("0.00")
    try:
        for entry in items:
            pid = str(entry["product_id"])
            qty = int(entry["quantity"])
            if qty <= 0:
                raise OrderCreationError("Quantity must be positive.")
            reserve_inventory(pid, qty)
            reserved.append((pid, qty))
            product = products[pid]
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
def transition_order(*, order: Order, target_status: str, actor) -> Order:
    """Move `order` to `target_status` if allowed; release inventory on cancel."""
    assert_transition(order.status, target_status)

    if target_status == Order.Status.CANCELLED:
        for item in order.items.all():
            try:
                release_inventory(str(item.product_id), item.quantity)
            except Exception:  # noqa: BLE001 - we still want to mark cancelled
                pass

    previous = order.status
    order.status = target_status
    order.save(update_fields=["status", "updated_at"])

    write_audit_log.delay(
        actor_id=str(actor.pk) if actor else None,
        action="order.status_transition",
        entity_type="Order",
        entity_id=str(order.pk),
        payload={"from": previous, "to": target_status},
    )

    # Fire outgoing webhook + notifications.
    from webhooks.tasks import emit_platform_event
    emit_platform_event.delay(
        event_type=f"order.{target_status}",
        payload={"order_id": str(order.pk), "status": target_status},
    )
    notify_order_status_change(order=order, new_status=target_status)

    # On delivery, queue invoice generation.
    if target_status == Order.Status.DELIVERED:
        from payments.tasks import generate_invoice_pdf
        generate_invoice_pdf.delay(str(order.pk))
    return order
