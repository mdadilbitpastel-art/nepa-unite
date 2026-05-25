"""Shared pytest fixtures for the users app."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from users.models import CustomUser, Tenant, WorkflowTemplate


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(
        name="Acme Dental",
        vertical_type=WorkflowTemplate.Vertical.DENTAL,
        status=Tenant.Status.ACTIVE,
    )


def _make_user(role: str, tenant: Tenant, **kwargs) -> CustomUser:
    suffix = uuid.uuid4().hex[:8]
    return CustomUser.objects.create(
        email=kwargs.get("email", f"{role}-{suffix}@example.com"),
        auth0_sub=kwargs.get("auth0_sub", f"auth0|{suffix}"),
        role=role,
        tenant=tenant,
        status=kwargs.get("status", CustomUser.Status.ACTIVE),
    )


@pytest.fixture
def admin_user(db, tenant):
    return _make_user(CustomUser.Role.ADMIN, tenant)


@pytest.fixture
def buyer_user(db, tenant):
    return _make_user(CustomUser.Role.BUYER, tenant)


@pytest.fixture
def seller_user(db, tenant):
    # Stripe-onboarded by default so product CRUD tests can list freely;
    # tests that exercise onboarding itself use `seller_user_no_stripe`.
    user = _make_user(CustomUser.Role.SELLER, tenant)
    user.stripe_account_id = "acct_test_seller"
    user.save(update_fields=["stripe_account_id", "updated_at"])
    return user


@pytest.fixture
def seller_user_no_stripe(db, tenant):
    """Approved seller that hasn't completed Stripe Connect yet."""
    return _make_user(CustomUser.Role.SELLER, tenant)


@pytest.fixture
def auditor_user(db, tenant):
    return _make_user(CustomUser.Role.AUDITOR, tenant)


@pytest.fixture
def force_login(api_client):
    """Bypass the Auth0 JWT flow and force-authenticate a user."""
    def _login(user):
        api_client.force_authenticate(user=user)
        return api_client
    return _login


@pytest.fixture
def mock_celery_eager(settings):
    """Force Celery tasks to run synchronously in tests."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    return settings


@pytest.fixture
def mock_send_email():
    with patch("users.views.send_welcome_email") as welcome, \
         patch("users.views.send_approval_email") as approval, \
         patch("users.views.send_suspension_email") as suspension:
        yield {"welcome": welcome, "approval": approval, "suspension": suspension}
