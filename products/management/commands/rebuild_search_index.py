"""python manage.py rebuild_search_index

Wipes and rebuilds the Elasticsearch product index from PostgreSQL.
Use after schema/analyzer changes or when the index drifts.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from products.documents import ProductDocument
from products.models import Product


class Command(BaseCommand):
    help = "Wipe and rebuild the product Elasticsearch index from PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Also index inactive products (default: only active).",
        )

    def handle(self, *args, **options):
        index = ProductDocument._index
        self.stdout.write(f"Deleting index '{index._name}' (if it exists)...")
        index.delete(ignore=404)

        self.stdout.write(f"Creating index '{index._name}'...")
        index.create()

        qs = Product.objects.all()
        if not options["include_inactive"]:
            qs = qs.filter(status=Product.Status.ACTIVE)

        self.stdout.write(f"Indexing {qs.count()} products...")
        ProductDocument().update(qs, action="index")
        self.stdout.write(self.style.SUCCESS("Done."))
