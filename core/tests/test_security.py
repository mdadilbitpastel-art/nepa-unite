"""Security tests: security headers, public-vs-private endpoints, RLS tenant isolation."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import connection
from django.urls import URLPattern, URLResolver, get_resolver

from products.models import Product
from users.models import CustomUser, Tenant, WorkflowTemplate


PUBLIC_PATHS = {
    "/api/health/",
    "/api/schema/",
    "/api/docs/",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/products/search/",
    "/api/v1/webhooks/stripe",
    # HTML auth UI — intentionally public; logout works whether or not signed in.
    "/",
    "/login/",
    "/signup/",
    "/logout/",
    "/forgot-password/",
}


# ---------------------------------------------------------------------------
# Security headers — every response must carry them.
# ---------------------------------------------------------------------------
def test_security_headers_present_on_health(db, api_client):
    response = api_client.get("/api/health/")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in response
    assert "Content-Security-Policy" in response


# ---------------------------------------------------------------------------
# Auth audit — any non-public endpoint must reject anonymous requests.
# ---------------------------------------------------------------------------
def _collect_paths(resolver, prefix=""):
    paths = []
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            paths.extend(_collect_paths(entry, prefix + str(entry.pattern)))
        elif isinstance(entry, URLPattern):
            paths.append(prefix + str(entry.pattern))
    return paths


def test_every_private_endpoint_requires_auth(db, api_client):
    paths = _collect_paths(get_resolver())
    failures = []
    for raw in paths:
        # Skip dynamic patterns — we can't synthesize an id here.
        if "<" in raw or "(?P" in raw:
            continue
        candidate = "/" + raw.lstrip("^").rstrip("$")
        if candidate in PUBLIC_PATHS:
            continue
        if candidate.startswith("/admin/"):
            continue
        response = api_client.get(candidate)
        # Acceptable: 401/403 (API auth), 404/405 (no such method), 302 (HTML
        # @login_required redirects anonymous users to /login/).
        if response.status_code == 302 and response.url.startswith("/login/"):
            continue
        if response.status_code not in (401, 403, 404, 405):
            failures.append((candidate, response.status_code))
    assert not failures, f"Endpoints that did not enforce auth: {failures}"


# ---------------------------------------------------------------------------
# RLS — two tenants must not see each other's data.
# ---------------------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_rls_isolates_two_tenants():
    tenant_a = Tenant.objects.create(
        name="Tenant A", vertical_type=WorkflowTemplate.Vertical.DENTAL,
        status=Tenant.Status.ACTIVE,
    )
    tenant_b = Tenant.objects.create(
        name="Tenant B", vertical_type=WorkflowTemplate.Vertical.LAW_OFFICE,
        status=Tenant.Status.ACTIVE,
    )
    seller_a = CustomUser.objects.create(
        email="a@a.com", auth0_sub="auth0|a",
        role=CustomUser.Role.SELLER, tenant=tenant_a,
        status=CustomUser.Status.ACTIVE,
    )
    seller_b = CustomUser.objects.create(
        email="b@b.com", auth0_sub="auth0|b",
        role=CustomUser.Role.SELLER, tenant=tenant_b,
        status=CustomUser.Status.ACTIVE,
    )
    Product.objects.create(
        tenant=tenant_a, seller=seller_a, sku="A-1",
        name="A product", description="x",
        price=Decimal("10"), inventory_count=5,
    )
    Product.objects.create(
        tenant=tenant_b, seller=seller_b, sku="B-1",
        name="B product", description="x",
        price=Decimal("10"), inventory_count=5,
    )

    if connection.vendor != "postgresql":
        pytest.skip("RLS only enforced on PostgreSQL")

    # RLS is *bypassed* for superusers and roles with the BYPASSRLS attribute.
    # The default `nepa` user in our local Postgres image is a superuser, so
    # this test would falsely report a leak. In production we connect with a
    # dedicated non-privileged role. Skip here and exercise the policy with
    # the migration's RunSQL — we additionally assert the policy is installed.
    with connection.cursor() as cur:
        cur.execute(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        if cur.fetchone()[0]:
            pytest.skip(
                "Current DB role bypasses RLS (superuser/BYPASSRLS) — "
                "test is meaningful only with a non-privileged app role"
            )

        cur.execute(
            "SELECT COUNT(*) FROM pg_policies "
            "WHERE tablename = 'products_product' AND policyname = 'tenant_isolation'"
        )
        assert cur.fetchone()[0] == 1, "RLS policy missing on products_product"

        # The real isolation check (only runs when role can be filtered).
        cur.execute("BEGIN")
        cur.execute("SET LOCAL app.bypass_rls = 'off'")
        cur.execute("SET LOCAL app.current_tenant = %s", [str(tenant_a.pk)])
        cur.execute("SELECT COUNT(*) FROM products_product")
        a_count = cur.fetchone()[0]
        cur.execute("SET LOCAL app.current_tenant = %s", [str(tenant_b.pk)])
        cur.execute("SELECT COUNT(*) FROM products_product")
        b_count = cur.fetchone()[0]
        cur.execute("COMMIT")

    assert a_count == 1
    assert b_count == 1
