"""locust -f locustfile.py — load test the NEPA Unite API.

Usage:
    locust -f locustfile.py --host=https://staging.nepaunite.com \
           BuyerUser SellerUser AdminUser

Performance targets (enforce via Locust events.quitting on CI):
    * search API p95 < 500ms
    * order creation p95 < 1000ms
    * total error rate < 0.1%
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, events, task


BUYER_TOKEN = os.environ.get("LOCUST_BUYER_TOKEN", "")
SELLER_TOKEN = os.environ.get("LOCUST_SELLER_TOKEN", "")
ADMIN_TOKEN = os.environ.get("LOCUST_ADMIN_TOKEN", "")

SEARCH_QUERIES = ["widget", "drill", "chair", "lamp", "filter", "labcoat"]


class _AuthUser(HttpUser):
    abstract = True
    wait_time = between(0.5, 2.5)
    token: str = ""

    def on_start(self):
        if self.token:
            self.client.headers["Authorization"] = f"Bearer {self.token}"


class BuyerUser(_AuthUser):
    """Searches, places an order."""
    token = BUYER_TOKEN
    weight = 6

    @task(3)
    def search_products(self):
        q = random.choice(SEARCH_QUERIES)
        with self.client.get(
            f"/api/v1/products/search/?q={q}", name="search"
        ) as resp:
            if resp.elapsed.total_seconds() > 0.5:
                resp.failure(f"search > 500ms ({resp.elapsed.total_seconds():.3f}s)")

    @task(1)
    def create_order(self):
        product_id = os.environ.get("LOCUST_BUYER_PRODUCT_ID", "")
        if not product_id:
            return
        with self.client.post(
            "/api/v1/orders/",
            json={"items": [{"product_id": product_id, "quantity": 1}]},
            name="create_order",
            catch_response=True,
        ) as resp:
            if resp.elapsed.total_seconds() > 1.0:
                resp.failure(f"order create > 1s ({resp.elapsed.total_seconds():.3f}s)")


class SellerUser(_AuthUser):
    """Lists a fresh product, updates inventory."""
    token = SELLER_TOKEN
    weight = 3

    @task
    def create_product(self):
        sku = f"LOAD-{uuid.uuid4().hex[:8]}"
        self.client.post(
            "/api/v1/products/",
            json={
                "sku": sku,
                "name": f"Load product {sku}",
                "description": "x",
                "price": "9.99",
                "attributes": {},
                "inventory_count": 100,
            },
            name="create_product",
        )

    @task
    def update_inventory(self):
        product_id = os.environ.get("LOCUST_SELLER_PRODUCT_ID", "")
        if not product_id:
            return
        self.client.patch(
            f"/api/v1/products/{product_id}/",
            json={"inventory_count": random.randint(10, 100)},
            name="update_inventory",
        )


class AdminUser(_AuthUser):
    """Lists every order, approves pending members."""
    token = ADMIN_TOKEN
    weight = 1

    @task(3)
    def list_orders(self):
        self.client.get("/api/v1/orders/", name="list_orders_admin")

    @task(1)
    def approve_member(self):
        member_id = os.environ.get("LOCUST_PENDING_MEMBER_ID", "")
        if not member_id:
            return
        self.client.post(
            f"/api/v1/admin/members/{member_id}/approve/",
            name="approve_member",
        )


# ---------------------------------------------------------------------------
# SLO enforcement — fail the run if we miss any target.
# ---------------------------------------------------------------------------
@events.quitting.add_listener
def _check_slos(environment, **_):
    stats = environment.stats
    failures = []

    error_rate = (
        stats.total.num_failures / max(stats.total.num_requests, 1)
    )
    if error_rate > 0.001:
        failures.append(f"error rate {error_rate:.4%} > 0.1%")

    search = stats.get("search", "GET")
    if search.num_requests and search.get_response_time_percentile(0.95) > 500:
        failures.append(
            f"search p95 {search.get_response_time_percentile(0.95):.0f}ms > 500ms"
        )

    order = stats.get("create_order", "POST")
    if order.num_requests and order.get_response_time_percentile(0.95) > 1000:
        failures.append(
            f"order create p95 "
            f"{order.get_response_time_percentile(0.95):.0f}ms > 1000ms"
        )

    if failures:
        for msg in failures:
            print(f"SLO FAILURE: {msg}")
        environment.process_exit_code = 1
    else:
        print("SLOs passed.")
