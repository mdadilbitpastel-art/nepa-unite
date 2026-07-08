"""Close delivered orders whose return/exchange window has elapsed.

Run manually or from cron:  python manage.py close_expired_orders
Also runs as a Celery task (orders.tasks.close_expired_return_windows).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from orders.tasks import close_expired_return_windows


class Command(BaseCommand):
    help = "Close delivered orders past their return/exchange window."

    def handle(self, *args, **options) -> None:
        closed = close_expired_return_windows()
        self.stdout.write(
            self.style.SUCCESS(f"Closed {closed} order(s) past their return window.")
        )
