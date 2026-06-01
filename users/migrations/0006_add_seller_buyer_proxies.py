from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_tenant_address_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="Seller",
            fields=[],
            options={
                "verbose_name": "Seller",
                "verbose_name_plural": "Sellers",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("users.customuser",),
            managers=[],
        ),
        migrations.CreateModel(
            name="Buyer",
            fields=[],
            options={
                "verbose_name": "Buyer",
                "verbose_name_plural": "Buyers",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("users.customuser",),
            managers=[],
        ),
    ]
