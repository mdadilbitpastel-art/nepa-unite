"""HTML auth UI — session-based, dev-mode (Auth0 bypassed).

The JSON API endpoints in `users.views` still exist for the Next.js future.
These HTML views are independent and use Django's standard session login.
"""

from __future__ import annotations

import logging
import uuid

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    if user.status == CustomUser.Status.PENDING:
        return redirect("pending_approval")

    ctx: dict = {"user": user, "role": user.role}

    if user.role == CustomUser.Role.BUYER:
        ctx["recent_orders"] = list(
            Order.objects.filter(buyer=user).order_by("-created_at")[:5]
        )
        ctx["products_preview"] = list(
            Product.objects.filter(status=Product.Status.ACTIVE)
            .order_by("-created_at")[:6]
        )
    elif user.role == CustomUser.Role.SELLER:
        ctx["my_products"] = list(
            Product.objects.filter(seller=user).order_by("-created_at")[:10]
        )
        ctx["my_orders"] = list(
            Order.objects.filter(items__seller=user)
            .distinct()
            .order_by("-created_at")[:5]
        )
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
    messages.success(request, f"Approved {member.email}.")
    return redirect("dashboard")


@login_required
@require_http_methods(["POST"])
def admin_suspend_member(request, member_id):
    if request.user.role != CustomUser.Role.ADMIN:
        return HttpResponseRedirect(reverse("dashboard"))
    member = get_object_or_404(CustomUser, pk=member_id)
    member.status = CustomUser.Status.SUSPENDED
    member.save(update_fields=["status", "updated_at"])
    messages.warning(request, f"Suspended {member.email}.")
    return redirect("dashboard")
