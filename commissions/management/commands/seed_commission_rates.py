"""Bootstrap the category commission schedule from the product taxonomy.

Creates one CommissionRate per distinct category in
``products.categories.INDUSTRY_CATEGORIES`` (skipping any that already exist),
so admins have a full schedule to tune from a sane starting percentage.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand

from commissions.models import CommissionRate
from products.categories import INDUSTRY_CATEGORIES


class Command(BaseCommand):
    help = "Seed CommissionRate rows for every product category."

    def add_arguments(self, parser):
        parser.add_argument(
            "--percent",
            type=Decimal,
            default=Decimal("5.00"),
            help="Default commission percent for each category (default: 5.00).",
        )

    def handle(self, *args, **options):
        percent: Decimal = options["percent"]
        categories = {
            cat for cats in INDUSTRY_CATEGORIES.values() for cat in cats
        }
        created = 0
        for category in sorted(categories):
            _, was_created = CommissionRate.objects.get_or_create(
                category=category,
                defaults={"percent": percent},
            )
            created += int(was_created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} new commission rate(s) "
                f"({len(categories)} categories total)."
            )
        )
