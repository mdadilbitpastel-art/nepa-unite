import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("users", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sku", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("price", models.DecimalField(decimal_places=2, max_digits=10)),
                ("attributes", models.JSONField(blank=True, default=dict)),
                ("inventory_count", models.IntegerField(default=0)),
                ("status", models.CharField(choices=[("active", "Active"), ("inactive", "Inactive"), ("deleted", "Deleted")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("seller", models.ForeignKey(on_delete=models.deletion.PROTECT, related_name="products", to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(db_column="tenant_id", on_delete=models.deletion.PROTECT, related_name="products", to="users.tenant")),
            ],
            options={
                "db_table": "products_product",
            },
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(fields=("tenant", "sku"), name="uniq_product_sku_per_tenant"),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(check=models.Q(("inventory_count__gte", 0)), name="product_inventory_nonneg"),
        ),
        migrations.CreateModel(
            name="ProductImage",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("image_url", models.URLField()),
                ("is_primary", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("product", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="images", to="products.product")),
            ],
            options={"db_table": "products_productimage"},
        ),
    ]
