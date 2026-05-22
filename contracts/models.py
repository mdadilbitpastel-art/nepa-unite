from __future__ import annotations

import uuid

from django.db import models


class Contract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    pricing_tiers = models.JSONField(default=list, blank=True)
    admin_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    valid_from = models.DateField()
    valid_until = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contracts_contract"
