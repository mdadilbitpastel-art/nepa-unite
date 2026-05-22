import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_enable_rls"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Job",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("running", "Running"), ("success", "Success"), ("failed", "Failed")], default="queued", max_length=16)),
                ("total", models.PositiveIntegerField(default=0)),
                ("succeeded", models.PositiveIntegerField(default=0)),
                ("failed", models.PositiveIntegerField(default=0)),
                ("errors", models.JSONField(blank=True, default=list)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "core_job"},
        ),
    ]
