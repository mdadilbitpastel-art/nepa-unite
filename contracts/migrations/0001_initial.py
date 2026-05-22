import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="Contract",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("vendor_name", models.CharField(max_length=255)),
                ("title", models.CharField(max_length=255)),
                ("pricing_tiers", models.JSONField(blank=True, default=list)),
                ("admin_fee_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("valid_from", models.DateField()),
                ("valid_until", models.DateField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "contracts_contract"},
        ),
    ]
