"""Product search and contract-pricing helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from contracts.models import Contract
from products.models import Product

logger = logging.getLogger(__name__)


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
    price_min: float | None = None,
    price_max: float | None = None,
    contract_status: str | None = None,
    in_stock: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchResult:
    """Search via Elasticsearch, falling back to a Postgres ILIKE query.

    The fallback is deliberately simpler: no facets, no fuzziness, no
    autocomplete — just enough to keep browsing usable when ES is down.
    A WARNING is logged so we get paged.
    """
    try:
        from products.documents import ProductDocument
        from elasticsearch_dsl.query import MultiMatch, Range, Term

        s = ProductDocument.search().filter("term", status=Product.Status.ACTIVE)
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

        s.aggs.bucket("by_category", "terms", field="category", size=50)
        s.aggs.bucket("by_region", "terms", field="region", size=50)
        s.aggs.bucket("by_contract_status", "terms", field="contract_status", size=50)

        start = (page - 1) * page_size
        s = s[start:start + page_size]

        response = s.execute()
        items = [hit.to_dict() | {"id": hit.meta.id} for hit in response]
        facets = {}
        for bucket_name in ("by_category", "by_region", "by_contract_status"):
            buckets = getattr(response.aggregations, bucket_name).buckets
            facets[bucket_name] = {b.key: b.doc_count for b in buckets}
        return SearchResult(
            items=items,
            total=response.hits.total.value,
            page=page,
            page_size=page_size,
            facets=facets,
            used_fallback=False,
        )
    except Exception as exc:  # noqa: BLE001 — broad: any ES failure -> fallback
        logger.warning("Elasticsearch unavailable, falling back to Postgres: %s", exc)
        return _pg_fallback_search(
            q=q,
            category=category,
            region=region,
            price_min=price_min,
            price_max=price_max,
            in_stock=in_stock,
            page=page,
            page_size=page_size,
        )


def _pg_fallback_search(
    *,
    q: str | None,
    category: str | None,
    region: str | None,
    price_min: float | None,
    price_max: float | None,
    in_stock: bool | None,
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
    if price_min is not None:
        qs = qs.filter(price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(price__lte=price_max)
    if in_stock is True:
        qs = qs.filter(inventory_count__gt=0)

    total = qs.count()
    start = (page - 1) * page_size
    items = list(qs.order_by("-created_at")[start:start + page_size].values(
        "id", "sku", "name", "description", "price",
        "attributes", "inventory_count", "status",
    ))
    return SearchResult(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        facets={},
        used_fallback=True,
    )


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
