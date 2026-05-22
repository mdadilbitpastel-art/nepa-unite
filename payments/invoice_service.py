"""Invoice PDF generation + S3 upload + pre-signed URL management."""

from __future__ import annotations

import io
import logging
from datetime import timedelta
from decimal import Decimal

import boto3
from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from orders.models import Order
from payments.models import Invoice

logger = logging.getLogger(__name__)

PRESIGN_TTL = 24 * 60 * 60  # 24 hours
TAX_RATE = Decimal("0.06")  # PA state sales tax


def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
    )


def _render_pdf(order: Order) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER)
    styles = getSampleStyleSheet()

    story = [
        Paragraph("<b>NEPA Unite</b>", styles["Title"]),
        Paragraph("Regional B2B Marketplace — Northeastern Pennsylvania",
                  styles["Normal"]),
        Spacer(1, 0.2 * inch),
        Paragraph(f"<b>Invoice for Order #{order.pk}</b>", styles["Heading2"]),
        Paragraph(f"Buyer: {order.buyer.email}", styles["Normal"]),
        Paragraph(f"Tenant: {order.tenant.name if order.tenant_id else '—'}",
                  styles["Normal"]),
        Paragraph(f"Date: {timezone.now().date().isoformat()}", styles["Normal"]),
        Paragraph(
            f"Stripe payment intent: {order.stripe_payment_intent_id or '—'}",
            styles["Normal"],
        ),
        Spacer(1, 0.2 * inch),
    ]

    rows = [["SKU", "Description", "Qty", "Unit price", "Tax", "Line total"]]
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    for item in order.items.select_related("product").all():
        line = Decimal(item.quantity) * item.unit_price
        tax = (line * TAX_RATE).quantize(Decimal("0.01"))
        subtotal += line
        tax_total += tax
        rows.append([
            item.product.sku,
            item.product.name,
            str(item.quantity),
            f"${item.unit_price:.2f}",
            f"${tax:.2f}",
            f"${(line + tax):.2f}",
        ])
    total = subtotal + tax_total
    rows.append(["", "", "", "Subtotal", "", f"${subtotal:.2f}"])
    rows.append(["", "", "", "Tax (6%)", "", f"${tax_total:.2f}"])
    rows.append(["", "", "", "Total", "", f"${total:.2f}"])

    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def _s3_key_for(order: Order) -> str:
    now = timezone.now()
    return f"invoices/{now.year}/{now.month:02d}/{order.pk}.pdf"


def _build_presigned_url(s3_key: str) -> tuple[str, timezone.datetime]:
    client = _s3_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.AWS_S3_INVOICES_BUCKET, "Key": s3_key},
        ExpiresIn=PRESIGN_TTL,
    )
    expires = timezone.now() + timedelta(seconds=PRESIGN_TTL)
    return url, expires


def generate_invoice(order_id: str) -> Invoice:
    """Render + upload + record an Invoice for an order. Idempotent: returns
    the existing Invoice if one already exists for this order."""
    order = Order.objects.select_related("buyer", "tenant").prefetch_related(
        "items__product"
    ).get(pk=order_id)
    existing = order.invoices.order_by("-created_at").first()
    if existing is not None:
        return existing

    pdf_bytes = _render_pdf(order)
    s3_key = _s3_key_for(order)

    s3 = _s3_client()
    s3.put_object(
        Bucket=settings.AWS_S3_INVOICES_BUCKET,
        Key=s3_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )
    url, expires = _build_presigned_url(s3_key)
    return Invoice.objects.create(
        order=order,
        s3_key=s3_key,
        pre_signed_url=url,
        pre_signed_url_expires_at=expires,
    )


def refresh_pre_signed_url(invoice: Invoice) -> Invoice:
    url, expires = _build_presigned_url(invoice.s3_key)
    invoice.pre_signed_url = url
    invoice.pre_signed_url_expires_at = expires
    invoice.save(update_fields=["pre_signed_url", "pre_signed_url_expires_at"])
    return invoice
