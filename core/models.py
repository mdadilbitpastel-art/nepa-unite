from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AuditLogQuerySet(models.QuerySet):
    """Append-only — disallow update/delete."""

    def update(self, **kwargs):  # noqa: D401
        raise NotImplementedError("AuditLog is append-only")

    def delete(self):  # noqa: D401
        raise NotImplementedError("AuditLog is append-only")


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=128)
    entity_type = models.CharField(max_length=128)
    entity_id = models.UUIDField()
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        db_table = "core_auditlog"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise RuntimeError("AuditLog rows are append-only")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):  # noqa: D401
        raise RuntimeError("AuditLog rows are append-only")


class Job(models.Model):
    """Async job tracker for things like bulk product upload."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=64)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED
    )
    total = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_job"
