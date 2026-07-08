from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Kind(models.TextChoices):
        ORDER_STATUS = "order_status", "Order status"
        PAYMENT = "payment", "Payment"
        ACCOUNT = "account", "Account"
        SYSTEM = "system", "System"
        RETURN = "return", "Return"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications_notification"
        indexes = [
            models.Index(fields=["recipient", "created_at"]),
        ]
