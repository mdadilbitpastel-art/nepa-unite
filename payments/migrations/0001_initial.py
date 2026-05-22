import uuid

from django.db import migrations, models

import payments.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("stripe_payment_intent_id", models.CharField(max_length=255, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("platform_fee", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed"), ("refunded", "Refunded"), ("disputed", "Disputed")], default="pending", max_length=16)),
                ("disbursed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="payments", to="orders.order")),
            ],
            options={"db_table": "payments_payment"},
        ),
        migrations.CreateModel(
            name="Invoice",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("invoice_number", models.CharField(default=payments.models._generate_invoice_number, max_length=32, unique=True)),
                ("s3_key", models.CharField(blank=True, default="", max_length=512)),
                ("pre_signed_url", models.URLField(blank=True, default="", max_length=2048)),
                ("pre_signed_url_expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="invoices", to="orders.order")),
            ],
            options={"db_table": "payments_invoice"},
        ),
    ]
