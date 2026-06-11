"""Helpers for dispatching Celery tasks from inside request handlers.

On single-service deploys (no Redis / no Celery worker) tasks run eagerly,
i.e. synchronously inside the web request. A failure in a best-effort side
effect — a welcome email, an audit-log write, a search reindex — should never
turn an otherwise successful request into a 500. ``safe_dispatch`` swallows and
logs any dispatch/execution error so the caller can carry on.
"""

from __future__ import annotations

import logging
import threading

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


def run_in_background(fn, *args, **kwargs) -> None:
    """Run ``fn(*args, **kwargs)`` in a daemon thread, off the request path.

    On deploys with a real Celery worker, tasks dispatched inside ``fn`` are
    already async — but on single-service deploys (eager mode) they run
    synchronously, so slow side effects (SMTP, outbound webhooks, PDF builds)
    would block the HTTP response and leave the browser spinning even though the
    user-visible work (e.g. the DB status change) is already committed. Running
    them in a background thread lets the response return immediately.

    The thread closes its DB connections on exit so it doesn't leak them, and
    swallows+logs any error (these are best-effort effects).
    """
    def _runner() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Background task failed: %s", getattr(fn, "__name__", fn)
            )
        finally:
            # Each thread gets its own DB connections; close them so they
            # aren't left open for the life of the (daemon) thread.
            from django.db import connections

            connections.close_all()

    threading.Thread(target=_runner, daemon=True).start()
