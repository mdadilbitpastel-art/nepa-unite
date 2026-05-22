import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("users", "0001_initial"),
        ("products", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("confirmed", "Confirmed"), ("fulfillment", "Fulfillment"), ("shipped", "Shipped"), ("delivered", "Delivered"), ("closed", "Closed"), ("cancelled", "Cancelled")], default="draft", max_length=16)),
                ("total_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("stripe_payment_intent_id", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("buyer", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="orders", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(db_column="tenant_id", on_delete=models.deletion.PROTECT, related_name="orders", to="users.tenant")),
            ],
            options={"db_table": "orders_order"},
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("fulfillment_status", models.CharField(choices=[("pending", "Pending"), ("fulfilled", "Fulfilled"), ("cancelled", "Cancelled")], default="pending", max_length=16)),
                ("order", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="items", to="orders.order")),
                ("product", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="order_items", to="products.product")),
                ("seller", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="sold_items", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "orders_orderitem"},
        ),
    ]
