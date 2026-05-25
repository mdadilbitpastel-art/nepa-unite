"""HTML auth UI — session-based, dev-mode (Auth0 bypassed).

The JSON API endpoints in `users.views` still exist for the Next.js future.
These HTML views are independent and use Django's standard session login.
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.paginator import Paginator
from django.db import models, transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.views.decorators.http import require_http_methods

from orders.models import Order
from products.models import Product
from users.forms import (
    ForgotPasswordForm,
    LoginForm,
    ResetPasswordForm,
    SignupForm,
)
from users.models import CustomUser, Tenant

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Home — route to login or dashboard
# ---------------------------------------------------------------------------
# Roles that may use the operations console. Buyers live on the separate
# storefront frontend; auditors aren't onboarded here yet.
_STAFF_ROLES = (CustomUser.Role.ADMIN, CustomUser.Role.SELLER)

# Table pagination — 10 rows per page everywhere.
_PAGE_SIZE = 10


def _paginate(request, queryset):
    """Return a Django Page object for `?page=N` (defaults to 1)."""
    paginator = Paginator(queryset, _PAGE_SIZE)
    return paginator.get_page(request.GET.get("page", 1))


def _querystring_without_page(request) -> str:
    """Current GET querystring with the `page` param removed.

    Used by the pagination template so filter state (?status=…&q=…)
    survives across page navigations.
    """
    qs = request.GET.copy()
    qs.pop("page", None)
    return qs.urlencode()


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                tenant = Tenant.objects.create(
                    name=data["business_name"],
                    vertical_type=data["vertical_type"],
                    status=Tenant.Status.PENDING,
                )
                user = CustomUser(
                    email=data["email"],
                    auth0_sub=f"local|{uuid.uuid4().hex}",
                    role=data["role"],
                    tenant=tenant,
                    status=CustomUser.Status.PENDING,
                )
                user.set_password(data["password"])
                user.save()
            messages.success(
                request,
                "Account created. An administrator will review and approve it.",
            )
            # Log them in so they land on the pending screen.
            user.backend = "django.contrib.auth.backends.ModelBackend"
            login(request, user)
            return redirect("pending_approval")
    else:
        form = SignupForm()

    return render(request, "auth/signup.html", {"form": form})


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower()
            password = form.cleaned_data["password"]
            user = authenticate(request, username=email, password=password)
            if user is None:
                # Distinguish suspended from bad credentials for a clearer message.
                suspended = CustomUser.objects.filter(
                    email__iexact=email, status=CustomUser.Status.SUSPENDED
                ).exists()
                if suspended:
                    messages.error(
                        request,
                        "Your account has been suspended. "
                        "Contact support if you believe this is a mistake.",
                    )
                else:
                    messages.error(request, "Invalid email or password.")
            else:
                if user.role not in _STAFF_ROLES:
                    messages.error(
                        request,
                        "This sign-in is for staff only. Buyers should use "
                        "the NEPA Unite storefront.",
                    )
                else:
                    login(request, user)
                    if user.status == CustomUser.Status.PENDING:
                        return redirect("pending_approval")
                    return redirect("dashboard")
    else:
        form = LoginForm()

    return render(request, "auth/login.html", {"form": form})


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@require_http_methods(["POST", "GET"])
def logout_view(request):
    logout(request)
    messages.info(request, "You've been signed out.")
    return redirect("login")


# ---------------------------------------------------------------------------
# Forgot password — generates a token, prints the reset link to the log
# (in real deployments, this becomes an email send via SES).
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    sent = False
    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower()
            user = CustomUser.objects.filter(email__iexact=email).first()
            if user is not None:
                uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                reset_path = reverse(
                    "reset_password", args=[uidb64, token]
                )
                full_url = request.build_absolute_uri(reset_path)
                logger.warning(
                    "Password reset link for %s: %s", user.email, full_url
                )
                # In prod: notifications.tasks.send_ses_email.delay(...)
            # Always show the same message — don't leak whether the email exists.
            sent = True
    else:
        form = ForgotPasswordForm()

    return render(
        request, "auth/forgot_password.html", {"form": form, "sent": sent}
    )


# ---------------------------------------------------------------------------
# Reset password — token-gated
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
def reset_password_view(request, uidb64: str, token: str):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = CustomUser.objects.get(pk=uid)
    except (CustomUser.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "auth/reset_password.html", {
            "form": None,
            "invalid": True,
        })

    if request.method == "POST":
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["password"])
            user.save(update_fields=["password", "updated_at"])
            messages.success(request, "Password updated. You can sign in now.")
            return redirect("login")
    else:
        form = ResetPasswordForm()

    return render(request, "auth/reset_password.html", {
        "form": form,
        "invalid": False,
    })


# ---------------------------------------------------------------------------
# Pending approval
# ---------------------------------------------------------------------------
@login_required
def pending_approval_view(request):
    if request.user.status == CustomUser.Status.ACTIVE:
        return redirect("dashboard")
    return render(request, "auth/pending_approval.html")


# ---------------------------------------------------------------------------
# Dashboard — role-aware, single template branches on role
# ---------------------------------------------------------------------------
@login_required
def dashboard_view(request):
    user = request.user
    # Defense in depth: if a stale session predates the staff-only rule, kick
    # the user out instead of dropping them on a blank dashboard.
    if user.role not in _STAFF_ROLES:
        logout(request)
        messages.error(
            request,
            "This sign-in is for staff only. Buyers should use the storefront.",
        )
        return redirect("login")
    if user.status == CustomUser.Status.PENDING:
        return redirect("pending_approval")

    ctx: dict = {"user": user, "role": user.role}

    # Buyers live on the separate storefront frontend (Next.js); no buyer
    # dashboard data is rendered here — the template shows a pointer card.
    if user.role == CustomUser.Role.SELLER:
        import json
        from datetime import timedelta
        from django.db.models.functions import TruncDate

        seller_products = Product.objects.filter(seller=user)
        ctx["my_products_count"] = seller_products.count()
        ctx["active_products_count"] = seller_products.filter(status=Product.Status.ACTIVE).count()
        ctx["inactive_products_count"] = seller_products.filter(status=Product.Status.INACTIVE).count()
        ctx["low_stock_count"] = seller_products.filter(
            status=Product.Status.ACTIVE, inventory_count__lt=5
        ).count()

        seller_orders = Order.objects.filter(items__seller=user).distinct()
        ctx["pending_orders_count"] = seller_orders.filter(
            status__in=[Order.Status.CONFIRMED, Order.Status.FULFILLMENT]
        ).count()
        ctx["fulfilled_orders_count"] = seller_orders.filter(
            status__in=[Order.Status.DELIVERED, Order.Status.CLOSED]
        ).count()
        ctx["total_orders_count"] = seller_orders.count()
        ctx["total_revenue"] = (
            seller_orders.filter(status__in=[
                Order.Status.DELIVERED, Order.Status.CLOSED,
            ]).aggregate(total=models.Sum("total_amount"))["total"]
        ) or 0

        today = timezone.now().date()
        days_7_ago = today - timedelta(days=6)
        daily_revenue_qs = (
            seller_orders
            .filter(created_at__date__gte=days_7_ago)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(total=models.Sum("total_amount"))
            .order_by("day")
        )
        daily_map = {row["day"]: float(row["total"] or 0) for row in daily_revenue_qs}
        revenue_labels = []
        revenue_data = []
        for i in range(7):
            d = days_7_ago + timedelta(days=i)
            revenue_labels.append(d.strftime("%b %d"))
            revenue_data.append(daily_map.get(d, 0))
        ctx["revenue_labels_json"] = json.dumps(revenue_labels)
        ctx["revenue_data_json"] = json.dumps(revenue_data)

        daily_orders_qs = (
            seller_orders
            .filter(created_at__date__gte=days_7_ago)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=models.Count("id"))
            .order_by("day")
        )
        daily_orders_map = {row["day"]: row["count"] for row in daily_orders_qs}
        orders_data = []
        for i in range(7):
            d = days_7_ago + timedelta(days=i)
            orders_data.append(daily_orders_map.get(d, 0))
        ctx["orders_data_json"] = json.dumps(orders_data)

        order_status_counts = {}
        for s in Order.Status:
            c = seller_orders.filter(status=s.value).count()
            if c > 0:
                order_status_counts[s.label] = c
        ctx["order_status_labels_json"] = json.dumps(list(order_status_counts.keys()))
        ctx["order_status_data_json"] = json.dumps(list(order_status_counts.values()))
    elif user.role == CustomUser.Role.ADMIN:
        ctx["pending_members"] = list(
            CustomUser.objects.filter(status=CustomUser.Status.PENDING)
            .order_by("-created_at")[:10]
        )
        ctx["recent_orders"] = list(
            Order.objects.order_by("-created_at")[:10]
        )
        ctx["total_users"] = CustomUser.objects.count()
        ctx["total_products"] = Product.objects.count()
        ctx["total_orders"] = Order.objects.count()
    elif user.role == CustomUser.Role.AUDITOR:
        from core.models import AuditLog
        ctx["audit_events"] = list(
            AuditLog.objects.order_by("-created_at")[:25]
        )

    return render(request, "dashboard/index.html", ctx)


# ---------------------------------------------------------------------------
# Developer: API reference (themed wrapper around Swagger UI)
# ---------------------------------------------------------------------------
@login_required
def api_reference_view(request):
    api_groups = [
        {
            "name": "Authentication",
            "description": "Session and JWT-style auth endpoints.",
            "endpoints": [
                ("POST", "/api/v1/auth/register", "Create an account"),
                ("POST", "/api/v1/auth/login", "Issue an access token"),
                ("POST", "/api/v1/auth/refresh", "Refresh a token"),
                ("POST", "/api/v1/auth/logout", "Revoke the current session"),
            ],
        },
        {
            "name": "Members",
            "description": "User directory + admin approval flow.",
            "endpoints": [
                ("GET",  "/api/v1/members/", "List members"),
                ("GET",  "/api/v1/members/{id}/", "Retrieve a member"),
                ("GET",  "/api/v1/admin/members/", "Admin — list every member"),
                ("POST", "/api/v1/admin/members/{id}/approve/", "Approve a pending member"),
                ("POST", "/api/v1/admin/members/{id}/suspend/", "Suspend a member"),
            ],
        },
        {
            "name": "Products",
            "description": "Catalog CRUD + bulk import jobs.",
            "endpoints": [
                ("GET",    "/api/v1/products/", "List products"),
                ("POST",   "/api/v1/products/", "Create a product"),
                ("GET",    "/api/v1/products/{id}/", "Retrieve a product"),
                ("PATCH",  "/api/v1/products/{id}/", "Update a product"),
                ("DELETE", "/api/v1/products/{id}/", "Soft-delete a product"),
                ("GET",    "/api/v1/jobs/", "List bulk-import jobs"),
                ("GET",    "/api/v1/jobs/{id}/", "Retrieve a job"),
            ],
        },
        {
            "name": "Orders",
            "description": "Place, fulfill, and inspect orders.",
            "endpoints": [
                ("GET",   "/api/v1/orders/", "List orders"),
                ("POST",  "/api/v1/orders/", "Create an order"),
                ("GET",   "/api/v1/orders/{id}/", "Retrieve an order"),
                ("PATCH", "/api/v1/orders/{id}/", "Update an order"),
            ],
        },
        {
            "name": "Payments",
            "description": "Stripe payment intents, payouts, and invoices.",
            "endpoints": [
                ("POST", "/api/v1/payments/intent", "Create a payment intent"),
                ("POST", "/api/v1/payments/disburse", "Disburse funds to a seller"),
                ("GET",  "/api/v1/payments/{order_id}", "Payment status for an order"),
                ("POST", "/api/v1/sellers/onboard", "Start Stripe Connect onboarding"),
                ("GET",  "/api/v1/orders/{order_id}/invoice", "Download an order invoice"),
            ],
        },
        {
            "name": "Webhooks",
            "description": "Inbound provider callbacks.",
            "endpoints": [
                ("POST", "/api/v1/webhooks/stripe", "Stripe event sink"),
            ],
        },
        {
            "name": "System",
            "description": "Schema, docs, and operational probes.",
            "endpoints": [
                ("GET", "/api/schema/", "OpenAPI 3 schema (YAML)"),
                ("GET", "/api/docs/", "Interactive Swagger UI"),
                ("GET", "/api/health/", "Liveness + dependency check"),
            ],
        },
    ]

    base_url = f"{request.scheme}://{request.get_host()}"

    ctx = {
        "user": request.user,
        "role": request.user.role,
        "api_groups": api_groups,
        "base_url": base_url,
        "swagger_url": "/api/docs/",
        "schema_url": "/api/schema/",
    }
    return render(request, "dashboard/api_reference.html", ctx)


# ---------------------------------------------------------------------------
# System health (themed wrapper around /api/health/)
# ---------------------------------------------------------------------------
@login_required
def system_health_view(request):
    from core.views import HealthCheckView

    db_ok, db_error = HealthCheckView._check_db()
    redis_ok, redis_error = HealthCheckView._check_redis()
    overall = db_ok and redis_ok

    checks = [
        {
            "name": "PostgreSQL",
            "kind": "Primary database",
            "ok": db_ok,
            "error": db_error,
            "probe": "SELECT 1",
        },
        {
            "name": "Redis",
            "kind": "Cache + Celery broker",
            "ok": redis_ok,
            "error": redis_error,
            "probe": "SET/GET round-trip on a sentinel key",
        },
    ]

    # CSP forbids inline JS, so auto-refresh is driven by a query param
    # and rendered as a <meta http-equiv="refresh"> tag in the template.
    refresh_raw = request.GET.get("refresh", "").strip()
    try:
        refresh_seconds = int(refresh_raw) if refresh_raw else 0
    except ValueError:
        refresh_seconds = 0
    if refresh_seconds not in (0, 15, 30, 60):
        refresh_seconds = 0

    ctx = {
        "user": request.user,
        "role": request.user.role,
        "overall_ok": overall,
        "checks": checks,
        "checked_at": timezone.now(),
        "health_endpoint": "/api/health/",
        "refresh_seconds": refresh_seconds,
    }
    return render(request, "dashboard/system_health.html", ctx)


# ---------------------------------------------------------------------------
# Seller: kick off Stripe Connect onboarding from the HTML UI
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["POST"])
def seller_connect_stripe(request):
    user = request.user
    if user.role != CustomUser.Role.SELLER:
        return redirect("dashboard")

    from payments import stripe_service

    try:
        onboarding_url = stripe_service.create_seller_account(str(user.pk))
    except Exception as exc:  # noqa: BLE001 — Stripe SDK raises many subclasses
        logger.warning("Stripe onboarding init failed for %s: %s", user.email, exc)
        messages.error(
            request,
            "Couldn't start Stripe onboarding right now. Either Stripe isn't "
            "configured in this environment, or the API rejected the request. "
            "Contact support if this keeps happening.",
        )
        return redirect("seller_products")
    return HttpResponseRedirect(onboarding_url)


# ---------------------------------------------------------------------------
# Seller: my products
# ---------------------------------------------------------------------------
@login_required
def seller_products_view(request):
    user = request.user
    if user.role not in (CustomUser.Role.SELLER, CustomUser.Role.ADMIN):
        return redirect("dashboard")

    status_filter = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()

    base_qs = Product.objects.select_related("tenant", "seller")
    if user.role == CustomUser.Role.SELLER:
        base_qs = base_qs.filter(seller=user)
    products_qs = base_qs.order_by("-created_at")

    if status_filter == "low_stock":
        products_qs = products_qs.filter(status=Product.Status.ACTIVE, inventory_count__lt=5)
    elif status_filter in Product.Status.values:
        products_qs = products_qs.filter(status=status_filter)
    if query:
        products_qs = products_qs.filter(
            models.Q(name__icontains=query) | models.Q(sku__icontains=query)
        )

    stats_qs = base_qs.values_list("status", "inventory_count")
    total = active = inactive = low_stock = 0
    for status, inventory in stats_qs:
        total += 1
        if status == Product.Status.ACTIVE:
            active += 1
            if inventory is not None and inventory < 5:
                low_stock += 1
        elif status == Product.Status.INACTIVE:
            inactive += 1

    page = _paginate(request, products_qs)
    ctx = {
        "user": user,
        "role": user.role,
        "products": page.object_list,
        "page": page,
        "elided_range": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "qs_prefix": _querystring_without_page(request),
        "status_filter": status_filter,
        "q": query,
        "stats": {
            "total": total,
            "active": active,
            "inactive": inactive,
            "low_stock": low_stock,
        },
        # Sellers without a Stripe Connect account can't list products;
        # surface the blocker right at the top of the page. Suppressed when
        # the gate flag is off (Stripe not yet provisioned in this env).
        "stripe_onboarding_required": (
            settings.STRIPE_GATE_ENABLED
            and user.role == CustomUser.Role.SELLER
            and not user.stripe_account_id
        ),
    }
    return render(request, "dashboard/products.html", ctx)


# ---------------------------------------------------------------------------
# Seller: create / edit / delete products (HTML mirrors of the JSON CRUD API)
# ---------------------------------------------------------------------------
def _product_writeable_or_redirect(request, *, require_owner=None):
    """Shared guards for the product form + delete views.

    Returns either a redirect response (caller should short-circuit) or
    None when the user is allowed to mutate the listing.
    """
    user = request.user
    if user.role not in (CustomUser.Role.SELLER, CustomUser.Role.ADMIN):
        return redirect("dashboard")
    if user.tenant_id is None:
        messages.error(request, "Your account isn't attached to a business yet.")
        return redirect("seller_products")
    if (
        settings.STRIPE_GATE_ENABLED
        and user.role == CustomUser.Role.SELLER
        and not user.stripe_account_id
    ):
        messages.error(
            request,
            "Complete Stripe Connect onboarding before listing a product.",
        )
        return redirect("seller_products")
    if (
        require_owner is not None
        and user.role == CustomUser.Role.SELLER
        and require_owner.seller_id != user.pk
    ):
        messages.error(request, "You can only edit your own products.")
        return redirect("seller_products")
    return None


@login_required
@require_http_methods(["GET", "POST"])
def seller_product_create(request):
    guard = _product_writeable_or_redirect(request)
    if guard is not None:
        return guard

    from products.forms import ProductForm
    from products.tasks import reindex_product

    user = request.user
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, tenant=user.tenant)
        if form.is_valid():
            product = form.save(commit=False)
            product.tenant = user.tenant
            product.seller = user
            product.save()
            reindex_product.delay(str(product.pk))
            messages.success(request, f"Created {product.sku} — {product.name}.")
            return redirect("seller_products")
    else:
        form = ProductForm(tenant=user.tenant)

    return render(
        request,
        "dashboard/product_form.html",
        {"user": user, "role": user.role, "form": form, "is_edit": False},
    )


@login_required
@require_http_methods(["GET", "POST"])
def seller_product_edit(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    guard = _product_writeable_or_redirect(request, require_owner=product)
    if guard is not None:
        return guard
    if product.status == Product.Status.DELETED:
        messages.error(request, "This product has been deleted — restore it via the API first.")
        return redirect("seller_products")

    from products.forms import ProductForm
    from products.tasks import reindex_product

    user = request.user
    if request.method == "POST":
        form = ProductForm(
            request.POST, request.FILES, instance=product, tenant=product.tenant
        )
        if form.is_valid():
            product = form.save()
            reindex_product.delay(str(product.pk))
            messages.success(request, f"Updated {product.sku}.")
            return redirect("seller_products")
    else:
        form = ProductForm(instance=product, tenant=product.tenant)

    return render(
        request,
        "dashboard/product_form.html",
        {
            "user": user, "role": user.role, "form": form,
            "product": product, "is_edit": True,
        },
    )


@login_required
@require_http_methods(["POST"])
def seller_product_toggle_status(request, product_id):
    """Flip a product between Active and Inactive in one click."""
    product = get_object_or_404(Product, pk=product_id)
    guard = _product_writeable_or_redirect(request, require_owner=product)
    if guard is not None:
        return guard
    if product.status == Product.Status.DELETED:
        return redirect("seller_products")

    from products.tasks import reindex_product

    if product.status == Product.Status.ACTIVE:
        product.status = Product.Status.INACTIVE
        msg = f"Hidden {product.sku} from the catalog."
        msg_kind = "warning"
    else:  # INACTIVE → ACTIVE
        product.status = Product.Status.ACTIVE
        msg = f"Published {product.sku} to the catalog."
        msg_kind = "success"
    product.save(update_fields=["status", "updated_at"])
    reindex_product.delay(str(product.pk))
    getattr(messages, msg_kind)(request, msg)
    return redirect("seller_products")


@login_required
@require_http_methods(["POST"])
def seller_product_delete(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    guard = _product_writeable_or_redirect(request, require_owner=product)
    if guard is not None:
        return guard

    from products.tasks import remove_product_from_index

    if product.status != Product.Status.DELETED:
        product.status = Product.Status.DELETED
        product.save(update_fields=["status", "updated_at"])
        remove_product_from_index.delay(str(product.pk))
        messages.warning(request, f"Deleted {product.sku} — {product.name}.")
    return redirect("seller_products")


# ---------------------------------------------------------------------------
# Orders — role-aware: buyer sees own, seller sees incoming, admin sees all
# ---------------------------------------------------------------------------
@login_required
def orders_view(request):
    user = request.user
    if user.status != CustomUser.Status.ACTIVE:
        return redirect("pending_approval")

    status_filter = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()

    if user.role == CustomUser.Role.BUYER:
        base_qs = Order.objects.filter(buyer=user)
    elif user.role == CustomUser.Role.SELLER:
        base_qs = Order.objects.filter(items__seller=user).distinct()
    else:  # admin, auditor
        base_qs = Order.objects.all()

    orders_qs = base_qs.select_related("buyer", "tenant").order_by("-created_at")

    if status_filter in Order.Status.values:
        orders_qs = orders_qs.filter(status=status_filter)
    if query:
        orders_qs = orders_qs.filter(buyer__email__icontains=query)

    status_counts = {value: 0 for value, _ in Order.Status.choices}
    total = 0
    for (status,) in base_qs.values_list("status"):
        total += 1
        if status in status_counts:
            status_counts[status] += 1

    status_buckets = [
        {"value": value, "label": label, "count": status_counts.get(value, 0)}
        for value, label in Order.Status.choices
    ]

    page = _paginate(request, orders_qs)
    ctx = {
        "user": user,
        "role": user.role,
        "orders": page.object_list,
        "page": page,
        "elided_range": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "qs_prefix": _querystring_without_page(request),
        "status_filter": status_filter,
        "q": query,
        "stats": {
            "total": total,
            "confirmed": status_counts.get(Order.Status.CONFIRMED, 0),
            "fulfillment": status_counts.get(Order.Status.FULFILLMENT, 0),
            "delivered": status_counts.get(Order.Status.DELIVERED, 0),
        },
        "status_buckets": status_buckets,
    }
    return render(request, "dashboard/orders.html", ctx)


# ---------------------------------------------------------------------------
# Audit log (admin + auditor)
# ---------------------------------------------------------------------------
@login_required
def audit_log_view(request):
    user = request.user
    if user.role not in (CustomUser.Role.ADMIN, CustomUser.Role.AUDITOR):
        return redirect("dashboard")

    from core.models import AuditLog

    entity_filter = request.GET.get("entity", "").strip()
    actor_query = request.GET.get("actor", "").strip()

    events_qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    if entity_filter:
        events_qs = events_qs.filter(entity_type__iexact=entity_filter)
    if actor_query:
        events_qs = events_qs.filter(actor__email__icontains=actor_query)

    entity_types = sorted(
        {
            row["entity_type"]
            for row in AuditLog.objects.values("entity_type").distinct()
            if row["entity_type"]
        }
    )

    page = _paginate(request, events_qs)
    ctx = {
        "user": user,
        "role": user.role,
        "events": page.object_list,
        "page": page,
        "elided_range": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "qs_prefix": _querystring_without_page(request),
        "entity_filter": entity_filter,
        "actor_query": actor_query,
        "entity_types": entity_types,
        "total_events": AuditLog.objects.count(),
    }
    return render(request, "dashboard/audit_log.html", ctx)


# ---------------------------------------------------------------------------
# Admin: members directory — full list with filters and inline actions
# ---------------------------------------------------------------------------
@login_required
def admin_members_view(request):
    if request.user.role != CustomUser.Role.ADMIN:
        return redirect("dashboard")

    status_filter = request.GET.get("status", "").strip()
    role_filter = request.GET.get("role", "").strip()
    query = request.GET.get("q", "").strip()

    members_qs = (
        CustomUser.objects.select_related("tenant").order_by("-created_at")
    )
    if status_filter in CustomUser.Status.values:
        members_qs = members_qs.filter(status=status_filter)
    if role_filter in CustomUser.Role.values:
        members_qs = members_qs.filter(role=role_filter)
    if query:
        members_qs = members_qs.filter(email__icontains=query)

    counts_qs = CustomUser.objects.values_list("status").all()
    counts = {"pending": 0, "active": 0, "suspended": 0}
    total = 0
    for (status,) in counts_qs:
        total += 1
        if status in counts:
            counts[status] += 1

    page = _paginate(request, members_qs)
    ctx = {
        "user": request.user,
        "role": request.user.role,
        "members": page.object_list,
        "page": page,
        "elided_range": page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        "qs_prefix": _querystring_without_page(request),
        "status_filter": status_filter,
        "role_filter": role_filter,
        "q": query,
        "stats": {
            "total": total,
            "active": counts["active"],
            "pending": counts["pending"],
            "suspended": counts["suspended"],
        },
        "role_choices": CustomUser.Role.choices,
    }
    return render(request, "dashboard/members.html", ctx)


def _safe_redirect(request, fallback_url_name: str) -> HttpResponseRedirect:
    """Redirect to a same-origin `next` path if provided, otherwise fallback."""
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url.startswith("/") and not next_url.startswith("//"):
        return HttpResponseRedirect(next_url)
    return HttpResponseRedirect(reverse(fallback_url_name))


# ---------------------------------------------------------------------------
# Admin: approve / suspend buttons used from the admin dashboard
# ---------------------------------------------------------------------------
@login_required
@require_http_methods(["POST"])
def admin_approve_member(request, member_id):
    if request.user.role != CustomUser.Role.ADMIN:
        return HttpResponseRedirect(reverse("dashboard"))
    member = get_object_or_404(CustomUser, pk=member_id)
    member.status = CustomUser.Status.ACTIVE
    member.save(update_fields=["status", "updated_at"])
    # First member approved for a still-pending tenant → activate the tenant too.
    if member.tenant_id and member.tenant.status == Tenant.Status.PENDING:
        member.tenant.status = Tenant.Status.ACTIVE
        member.tenant.save(update_fields=["status"])
    # Sellers need to finish Stripe Connect onboarding before they can be paid;
    # send them the nudge email so they know what to do next. Suppressed
    # when the gate flag is off (Stripe not yet provisioned).
    if (
        settings.STRIPE_GATE_ENABLED
        and member.role == CustomUser.Role.SELLER
        and not member.stripe_account_id
    ):
        from notifications.tasks import send_seller_onboarding_email
        send_seller_onboarding_email.delay(member.email)
    messages.success(request, f"Approved {member.email}.")
    return _safe_redirect(request, "dashboard")


@login_required
@require_http_methods(["POST"])
def admin_suspend_member(request, member_id):
    if request.user.role != CustomUser.Role.ADMIN:
        return HttpResponseRedirect(reverse("dashboard"))
    # Don't let an admin lock themselves out.
    if str(request.user.id) == str(member_id):
        messages.error(request, "You can't suspend your own account.")
        return _safe_redirect(request, "dashboard")
    member = get_object_or_404(CustomUser, pk=member_id)
    member.status = CustomUser.Status.SUSPENDED
    member.save(update_fields=["status", "updated_at"])
    messages.warning(request, f"Suspended {member.email}.")
    return _safe_redirect(request, "dashboard")
