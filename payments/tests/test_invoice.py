"""Invoice generation + pre-signed URL refresh."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from orders.models import Order, OrderItem
from payments.models import Invoice
from products.models import Product


@pytest.fixture
def order(db, buyer_user, tenant, seller_user):
    product = Product.objects.create(
        tenant=tenant, seller=seller_user, sku="INV-1",
        name="Invoice test", description="x",
        price=Decimal("10"), inventory_count=10,
    )
    order = Order.objects.create(
        buyer=buyer_user, tenant=tenant,
        total_amount=Decimal("20"),
        stripe_payment_intent_id="pi_test",
    )
    OrderItem.objects.create(
        order=order, product=product, seller=seller_user,
        quantity=2, unit_price=Decimal("10"),
    )
    return order


def test_generate_invoice_uploads_and_persists(db, order):
    from payments.invoice_service import generate_invoice

    with patch("payments.invoice_service._s3_client") as client_factory:
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://s3/presigned"
        invoice = generate_invoice(str(order.pk))

    client.put_object.assert_called_once()
    assert invoice.s3_key.endswith(f"{order.pk}.pdf")
    assert invoice.pre_signed_url == "https://s3/presigned"
    assert invoice.pre_signed_url_expires_at > timezone.now()


def test_generate_invoice_is_idempotent(db, order):
    from payments.invoice_service import generate_invoice
    with patch("payments.invoice_service._s3_client") as client_factory:
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://s3/p"
        first = generate_invoice(str(order.pk))
        second = generate_invoice(str(order.pk))
    assert first.pk == second.pk
    # Only one upload total.
    assert client.put_object.call_count == 1


def test_buyer_can_download_their_invoice(db, force_login, buyer_user, order):
    from payments.invoice_service import generate_invoice
    with patch("payments.invoice_service._s3_client") as client_factory:
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://s3/p"
        generate_invoice(str(order.pk))

    api = force_login(buyer_user)
    with patch("payments.invoice_service._s3_client") as client_factory:
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://s3/p2"
        response = api.get(f"/api/v1/orders/{order.pk}/invoice")
    assert response.status_code == 200
    assert response.json()["s3_key"].endswith(f"{order.pk}.pdf")


def test_invoice_endpoint_refreshes_expired_url(db, force_login, buyer_user, order):
    invoice = Invoice.objects.create(
        order=order, s3_key="invoices/2020/01/old.pdf",
        pre_signed_url="https://old", pre_signed_url_expires_at=timezone.now() - timedelta(hours=1),
    )
    api = force_login(buyer_user)
    with patch("payments.invoice_service._s3_client") as client_factory:
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://fresh"
        response = api.get(f"/api/v1/orders/{order.pk}/invoice")
    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.pre_signed_url == "https://fresh"
    assert invoice.pre_signed_url_expires_at > timezone.now()


def test_non_owner_cannot_download_invoice(db, force_login, order, tenant):
    from users.models import CustomUser
    intruder = CustomUser.objects.create(
        email="x@x.com", auth0_sub="auth0|x",
        role=CustomUser.Role.BUYER, tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    api = force_login(intruder)
    response = api.get(f"/api/v1/orders/{order.pk}/invoice")
    assert response.status_code == 403
