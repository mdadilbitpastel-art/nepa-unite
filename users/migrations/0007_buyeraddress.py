import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0006_add_seller_buyer_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="BuyerAddress",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(blank=True, default="", max_length=64)),
                ("recipient_name", models.CharField(max_length=255)),
                ("phone", models.CharField(max_length=30)),
                ("line1", models.CharField(max_length=255)),
                ("line2", models.CharField(blank=True, default="", max_length=255)),
                ("city", models.CharField(max_length=100)),
                ("state", models.CharField(max_length=100)),
                ("zip_code", models.CharField(max_length=20)),
                ("country", models.CharField(default="US", max_length=100)),
                ("is_default", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="addresses",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "db_table": "users_buyeraddress",
                "ordering": ["-is_default", "-updated_at"],
            },
        ),
    ]
