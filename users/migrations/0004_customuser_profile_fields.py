from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0003_tenant_logo"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="customuser",
            name="last_name",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="customuser",
            name="phone",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
