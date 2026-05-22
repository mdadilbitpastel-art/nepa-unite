"""Background tasks for the core app — primarily audit log writes."""

import uuid

from celery import shared_task

from core.models import AuditLog


@shared_task
def write_audit_log(
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict | None = None,
) -> None:
    AuditLog.objects.create(
        actor_id=uuid.UUID(actor_id) if actor_id else None,
        action=action,
        entity_type=entity_type,
        entity_id=uuid.UUID(entity_id),
        payload=payload or {},
    )


@shared_task
def users_tasks_placeholder() -> None:  # pragma: no cover
    return None
