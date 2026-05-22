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
            name="WebhookEndpoint",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("url", models.URLField(max_length=2048)),
                ("secret", models.CharField(help_text="HMAC signing secret", max_length=128)),
                ("event_types", models.JSONField(blank=True, default=list, help_text="Subset of event types this endpoint receives; empty = all")),
                ("is_active", models.BooleanField(default=True)),
                ("failure_count", models.PositiveIntegerField(default=0)),
                ("last_delivery_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="webhook_endpoints", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "webhooks_endpoint"},
        ),
        migrations.CreateModel(
            name="WebhookDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("event_type", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("delivered", "Delivered"), ("failed", "Failed")], default="pending", max_length=16)),
                ("attempt", models.PositiveIntegerField(default=0)),
                ("last_status_code", models.IntegerField(blank=True, null=True)),
                ("last_response", models.TextField(blank=True, default="")),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("endpoint", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="deliveries", to="webhooks.webhookendpoint")),
            ],
            options={"db_table": "webhooks_delivery"},
        ),
        migrations.AddIndex(
            model_name="webhookdelivery",
            index=models.Index(fields=["status", "next_retry_at"], name="webhook_status_retry_idx"),
        ),
    ]
