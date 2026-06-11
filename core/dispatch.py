"""Helpers for dispatching Celery tasks from inside request handlers.

On single-service deploys (no Redis / no Celery worker) tasks run eagerly,
i.e. synchronously inside the web request. A failure in a best-effort side
effect — a welcome email, an audit-log write, a search reindex — should never
turn an otherwise successful request into a 500. ``safe_dispatch`` swallows and
logs any dispatch/execution error so the caller can carry on.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def safe_dispatch(task, *args, **kwargs) -> None:
    """Fire a Celery task, swallowing (and logging) any failure.

    Use only for best-effort side effects whose failure must not break the
    request. For work the response correctness depends on, call the task
    directly and let the error propagate.
    """
    try:
        task.delay(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to dispatch task %s", getattr(task, "name", task))
