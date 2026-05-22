"""Background tasks for the contracts app. (Placeholder.)"""

from celery import shared_task


@shared_task
def reconcile_admin_fees(contract_id: str) -> None:  # pragma: no cover
    return None
