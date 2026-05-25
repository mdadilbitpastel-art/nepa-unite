from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="primary_image",
            field=models.ImageField(
                blank=True, null=True, upload_to="products/%Y/%m/"
            ),
        ),
    ]
