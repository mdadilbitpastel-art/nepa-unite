"""Backfill the commission ledger for orders that predate the feature.

The live lifecycle books commission when a payment succeeds and marks it earned
on delivery. Orders placed *before* commissions existed never hit those hooks,
so this command replays the same rules over existing orders:

* ``confirmed / fulfillment / shipped / delivered / closed`` -> accrue (PENDING)
* ``delivered / closed``                                     -> mark EARNED
* ``draft / cancelled``                                      -> skipped

Idempotent: re-running only fills gaps (one commission per order item) and never
double-books. Use ``--dry-run`` to preview counts without writing.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from commissions.models import Commission
from commissions.services import accrue_for_order, earn_for_order
from orders.models import Order

ACCRUE_STATUSES = [
    Order.Status.CONFIRMED,
    Order.Status.FULFILLMENT,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
    Order.Status.CLOSED,
]
EARNED_STATUSES = [Order.Status.DELIVERED, Order.Status.CLOSED]


class Command(BaseCommand):
    help = "Backfill commission ledger rows for pre-existing orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the ledger.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        orders = Order.objects.filter(status__in=ACCRUE_STATUSES).prefetch_related(
            "items"
        )

        accrued = 0
        earned = 0
        for order in orders:
            if dry_run:
                missing = order.items.exclude(
                    pk__in=Commission.objects.filter(order=order).values("order_item")
                ).count()
                accrued += missing
                if order.status in EARNED_STATUSES:
                    earned += order.items.count()
                continue

            with transaction.atomic():
                created = accrue_for_order(order)
                accrued += len(created)
                if order.status in EARNED_STATUSES:
                    earned += earn_for_order(order)

        verb = "Would book" if dry_run else "Booked"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {accrued} new commission row(s) across "
                f"{orders.count()} order(s); {earned} marked earned."
            )
        )
