"""Product search and contract-pricing helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from contracts.models import Contract
from products.models import Product, ProductReview

logger = logging.getLogger(__name__)

# Sorts that depend on review aggregates or the MRP discount expression —
# Elasticsearch doesn't index those, so requesting one routes the whole
# query through the Postgres path where the data lives.
_PG_ONLY_SORTS = {"rating_desc", "discount_desc"}


def _enrich_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach `rating_avg`, `review_count` and `mrp` to result rows.

    Works uniformly for ES hits and Postgres rows: one aggregate query for
    ratings + one for MRP, keyed by product id. Keeps the search service the
    single source of truth for these display fields regardless of backend.
    """
    ids = [it.get("id") for it in items if it.get("id")]
    if not ids:
        return items

    ratings: dict[str, tuple[float, int]] = {}
    for row in (
        ProductReview.objects.filter(product_id__in=ids)
        .values("product_id")
        .annotate(avg=Avg("rating"), count=Count("id"))
    ):
        ratings[str(row["product_id"])] = (
            round(float(row["avg"]), 1) if row["avg"] else 0.0,
            row["count"],
        )

    mrps = {
        str(pid): (str(mrp) if mrp is not None else None)
        for pid, mrp in Product.objects.filter(id__in=ids).values_list("id", "mrp")
    }

    for it in items:
        pid = str(it.get("id"))
        avg, count = ratings.get(pid, (0.0, 0))
        it["rating_avg"] = avg
        it["review_count"] = count
        if not it.get("mrp"):
            it["mrp"] = mrps.get(pid)
    return items


@dataclass
class SearchResult:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    facets: dict[str, dict[str, int]]
    used_fallback: bool


def search_products(
    *,
    q: str | None = None,
    category: str | None = None,
    region: str | None = None,
    brand: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    min_rating: float | None = None,
    contract_status: str | None = None,
    in_stock: bool | None = None,
    sort: str = "relevance",
    page: int = 1,
    page_size: int = 20,
) -> SearchResult:
    """Search via Elasticsearch, falling back to a Postgres ILIKE query.

    The fallback is deliberately simpler: no facets, no fuzziness, no
    autocomplete — just enough to keep browsing usable when ES is down.
    A WARNING is logged so we get paged.

    Rating/discount sorts, min_rating and brand filters depend on data ES
    doesn't index, so any of those routes the query straight to Postgres.
    """
    pg_only = (
        sort in _PG_ONLY_SORTS
        or min_rating is not None
        or bool(brand)
    )
    if not pg_only:
        try:
            from products.documents import ProductDocument
            from elasticsearch_dsl.query import MultiMatch, Range, Term

            s = ProductDocument.search().filter(
                "term", status=Product.Status.ACTIVE
            )
            if q:
                s = s.query(MultiMatch(query=q, fields=["name^3", "description"],
                                       fuzziness="AUTO"))
            if category:
                s = s.filter(Term(category=category))
            if region:
                s = s.filter(Term(region=region))
            if contract_status:
                s = s.filter(Term(contract_status=contract_status))
            if in_stock is True:
                s = s.filter(Term(in_stock=True))
            if price_min is not None or price_max is not None:
                rng: dict[str, float] = {}
                if price_min is not None:
                    rng["gte"] = price_min
                if price_max is not None:
                    rng["lte"] = price_max
                s = s.filter(Range(price=rng))

            # ES handles relevance + price ordering; other sorts are pg_only.
            if sort == "price_asc":
                s = s.sort("price")
            elif sort == "price_desc":
                s = s.sort("-price")

            s.aggs.bucket("by_category", "terms", field="category", size=50)
            s.aggs.bucket("by_region", "terms", field="region", size=50)
            s.aggs.bucket(
                "by_contract_status", "terms", field="contract_status", size=50
            )

            start = (page - 1) * page_size
            s = s[start:start + page_size]

            response = s.execute()
            items = [hit.to_dict() | {"id": hit.meta.id} for hit in response]
            facets = {}
            for bucket_name in ("by_category", "by_region", "by_contract_status"):
                buckets = getattr(response.aggregations, bucket_name).buckets
                facets[bucket_name] = {b.key: b.doc_count for b in buckets}
            return SearchResult(
                items=_enrich_items(items),
                total=response.hits.total.value,
                page=page,
                page_size=page_size,
                facets=facets,
                used_fallback=False,
            )
        except Exception as exc:  # noqa: BLE001 — any ES failure -> fallback
            logger.warning(
                "Elasticsearch unavailable, falling back to Postgres: %s", exc
            )

    return _pg_fallback_search(
        q=q,
        category=category,
        region=region,
        brand=brand,
        price_min=price_min,
        price_max=price_max,
        min_rating=min_rating,
        in_stock=in_stock,
        sort=sort,
        page=page,
        page_size=page_size,
    )


def _pg_fallback_search(
    *,
    q: str | None,
    category: str | None,
    region: str | None,
    brand: str | None,
    price_min: float | None,
    price_max: float | None,
    min_rating: float | None,
    in_stock: bool | None,
    sort: str,
    page: int,
    page_size: int,
) -> SearchResult:
    qs = Product.objects.filter(status=Product.Status.ACTIVE)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if category:
        qs = qs.filter(attributes__category=category)
    if region:
        qs = qs.filter(attributes__region=region)
    if brand:
        qs = qs.filter(attributes__brand=brand)
    if price_min is not None:
        qs = qs.filter(price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(price__lte=price_max)
    if in_stock is True:
        qs = qs.filter(inventory_count__gt=0)

    # Aggregate rating is needed for both the min_rating filter and the
    # rating sort; annotate once.
    qs = qs.annotate(_avg_rating=Avg("reviews__rating"))
    if min_rating is not None:
        qs = qs.filter(_avg_rating__gte=min_rating)

    qs = _apply_pg_sort(qs, sort)

    total = qs.count()
    start = (page - 1) * page_size
    page_objs = list(qs[start:start + page_size])
    items = [
        {
            "id": str(p.id),
            "sku": p.sku,
            "name": p.name,
            "description": p.description,
            "price": str(p.price),
            "mrp": str(p.mrp) if p.mrp is not None else None,
            "attributes": p.attributes,
            "inventory_count": p.inventory_count,
            "min_order_qty": p.min_order_qty,
            "status": p.status,
            # Relative /media/... URL; the frontend resolves it to the API host.
            "primary_image_url": p.primary_image.url if p.primary_image else None,
        }
        for p in page_objs
    ]
    return SearchResult(
        items=_enrich_items(items),
        total=total,
        page=page,
        page_size=page_size,
        facets={},
        used_fallback=True,
    )


def _apply_pg_sort(qs, sort: str):
    """Translate a `sort` token into Postgres ordering.

    `nulls_last` keeps products without ratings / MRP at the bottom of the
    respective sorts instead of leading the list.
    """
    if sort == "price_asc":
        return qs.order_by("price", "-created_at")
    if sort == "price_desc":
        return qs.order_by("-price", "-created_at")
    if sort == "newest":
        return qs.order_by("-created_at")
    if sort == "rating_desc":
        return qs.order_by(F("_avg_rating").desc(nulls_last=True), "-created_at")
    if sort == "discount_desc":
        # Discount magnitude = mrp - price; rows without an MRP sort last.
        return qs.annotate(_discount=F("mrp") - F("price")).order_by(
            F("_discount").desc(nulls_last=True), "-created_at"
        )
    # relevance (and any unknown value): newest-first is the sensible default
    # for the Postgres path, which has no relevance score.
    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Contract pricing
# ---------------------------------------------------------------------------
def contract_price_for_buyer(product: Product, buyer) -> Decimal | None:
    """Return the negotiated price for a buyer under an active GPO contract,
    or None if no contract applies."""
    today = timezone.now().date()
    contracts = Contract.objects.filter(
        is_active=True,
        valid_from__lte=today,
        valid_until__gte=today,
    )
    best: Decimal | None = None
    for contract in contracts:
        for tier in (contract.pricing_tiers or []):
            if not _tier_applies(tier, product, buyer):
                continue
            try:
                tier_price = Decimal(str(tier["price"]))
            except (KeyError, ValueError):
                continue
            if best is None or tier_price < best:
                best = tier_price
    return best


def _tier_applies(tier: dict, product: Product, buyer) -> bool:
    """A tier applies when its `match` block selects this product/buyer."""
    match = tier.get("match", {})
    sku = match.get("sku")
    if sku and sku != product.sku:
        return False
    category = match.get("category")
    if category and category != product.category_value:
        return False
    tenant_id = match.get("tenant_id")
    if tenant_id and str(tenant_id) != str(buyer.tenant_id):
        return False
    return True
