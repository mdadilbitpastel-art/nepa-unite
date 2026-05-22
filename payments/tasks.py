"""Background tasks for the payments app. (Placeholder — to be filled in.)"""

from celery import shared_task


@shared_task
def generate_invoice_pdf(order_id: str) -> None:
    """Render the invoice PDF, upload to S3, and persist the Invoice row."""
    from payments.invoice_service import generate_invoice
    generate_invoice(order_id)
