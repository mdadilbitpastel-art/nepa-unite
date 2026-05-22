"""Background tasks for the users app. (Email work lives in notifications.tasks.)"""

from celery import shared_task


@shared_task
def sync_user_with_auth0(user_id: str) -> None:  # pragma: no cover
    return None
