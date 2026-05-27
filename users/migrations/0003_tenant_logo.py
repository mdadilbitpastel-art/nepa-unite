from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_customuser_stripe_account_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="logo",
            field=models.ImageField(blank=True, default="", upload_to="tenant_logos/"),
        ),
    ]
