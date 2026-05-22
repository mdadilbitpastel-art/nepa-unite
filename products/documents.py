"""Elasticsearch / OpenSearch document for products."""

from __future__ import annotations

from django.conf import settings
from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter

from products.models import Product


_autocomplete = analyzer(
    "autocomplete",
    tokenizer="standard",
    filter=[
        "lowercase",
        token_filter(
            "autocomplete_edge_ngram",
            type="edge_ngram",
            min_gram=2,
            max_gram=20,
        ),
    ],
)


@registry.register_document
class ProductDocument(Document):
    name = fields.TextField(
        analyzer=_autocomplete,
        search_analyzer="standard",
        fields={"raw": fields.KeywordField()},
    )
    description = fields.TextField()
    category = fields.KeywordField(attr="category_value")
    price = fields.FloatField()
    inventory_count = fields.IntegerField()
    tenant_id = fields.KeywordField()
    seller_id = fields.KeywordField()
    status = fields.KeywordField()
    region = fields.KeywordField(attr="region_value")
    contract_status = fields.KeywordField(attr="contract_status_value")
    in_stock = fields.BooleanField(attr="in_stock_value")

    class Index:
        name = settings.PRODUCT_SEARCH_INDEX
        settings = {"number_of_shards": 1, "number_of_replicas": 0}

    class Django:
        model = Product
        fields = []

    def prepare_tenant_id(self, instance: Product) -> str:
        return str(instance.tenant_id)

    def prepare_seller_id(self, instance: Product) -> str:
        return str(instance.seller_id)
