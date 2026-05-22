from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class WebhookEndpoint(models.Model):
    """A platform member's registered webhook endpoint."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webhook_endpoints",
    )
    url = models.URLField(max_length=2048)
    secret = models.CharField(max_length=128, help_text="HMAC signing secret")
    event_types = models.JSONField(
        default=list,
        blank=True,
        help_text="Subset of event types this endpoint receives; empty = all",
    )
    is_active = models.BooleanField(default=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "webhooks_endpoint"


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempt = models.PositiveIntegerField(default=0)
    last_status_code = models.IntegerField(null=True, blank=True)
    last_response = models.TextField(blank=True, default="")
    next_retry_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "webhooks_delivery"
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
        ]
