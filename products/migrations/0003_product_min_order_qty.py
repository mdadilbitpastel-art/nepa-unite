from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0002_product_primary_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="min_order_qty",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
