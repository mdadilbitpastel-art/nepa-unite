"""Endpoint tests for /api/v1/members/{id} and the admin approve/suspend flow."""

from __future__ import annotations

import pytest

from core.models import AuditLog
from users.models import CustomUser


# ---------------------------------------------------------------------------
# GET /api/v1/members/{id}
# ---------------------------------------------------------------------------
def test_member_can_view_own_profile(db, force_login, buyer_user):
    client = force_login(buyer_user)
    response = client.get(f"/api/v1/members/{buyer_user.pk}/")
    assert response.status_code == 200
    assert response.json()["email"] == buyer_user.email


def test_buyer_cannot_view_other_profile(db, force_login, buyer_user, seller_user):
    client = force_login(buyer_user)
    response = client.get(f"/api/v1/members/{seller_user.pk}/")
    assert response.status_code == 403


def test_seller_cannot_view_other_profile(db, force_login, seller_user, buyer_user):
    client = force_login(seller_user)
    response = client.get(f"/api/v1/members/{buyer_user.pk}/")
    assert response.status_code == 403


def test_admin_can_view_any_profile(db, force_login, admin_user, buyer_user):
    client = force_login(admin_user)
    response = client.get(f"/api/v1/members/{buyer_user.pk}/")
    assert response.status_code == 200


def test_unauthenticated_cannot_view(db, api_client, buyer_user):
    response = api_client.get(f"/api/v1/members/{buyer_user.pk}/")
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PATCH /api/v1/members/{id}
# ---------------------------------------------------------------------------
def test_member_can_update_own_email(db, force_login, buyer_user):
    client = force_login(buyer_user)
    response = client.patch(
        f"/api/v1/members/{buyer_user.pk}/",
        {"email": "newemail@example.com"},
        format="json",
    )
    assert response.status_code == 200
    buyer_user.refresh_from_db()
    assert buyer_user.email == "newemail@example.com"


def test_buyer_cannot_update_other(db, force_login, buyer_user, seller_user):
    client = force_login(buyer_user)
    response = client.patch(
        f"/api/v1/members/{seller_user.pk}/",
        {"email": "hacker@example.com"},
        format="json",
    )
    assert response.status_code == 403


def test_admin_can_update_any(db, force_login, admin_user, buyer_user):
    client = force_login(admin_user)
    response = client.patch(
        f"/api/v1/members/{buyer_user.pk}/",
        {"email": "admin-edit@example.com"},
        format="json",
    )
    assert response.status_code == 200


def test_member_update_rejects_duplicate_email(
    db, force_login, buyer_user, seller_user
):
    client = force_login(buyer_user)
    response = client.patch(
        f"/api/v1/members/{buyer_user.pk}/",
        {"email": seller_user.email},
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/admin/members/{id}/approve
# ---------------------------------------------------------------------------
def test_admin_can_approve_pending_member(
    db, force_login, admin_user, tenant, mock_celery_eager, mock_send_email
):
    pending = CustomUser.objects.create(
        email="pending@example.com",
        auth0_sub="auth0|pending",
        role=CustomUser.Role.BUYER,
        tenant=tenant,
        status=CustomUser.Status.PENDING,
    )
    client = force_login(admin_user)
    response = client.post(f"/api/v1/admin/members/{pending.pk}/approve/")
    assert response.status_code == 200
    pending.refresh_from_db()
    assert pending.status == CustomUser.Status.ACTIVE
    mock_send_email["approval"].delay.assert_called_once_with(pending.email)


def test_non_admin_cannot_approve(db, force_login, buyer_user, seller_user):
    client = force_login(buyer_user)
    response = client.post(f"/api/v1/admin/members/{seller_user.pk}/approve/")
    assert response.status_code == 403


def test_approve_writes_audit_log(
    db, force_login, admin_user, tenant, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    pending = CustomUser.objects.create(
        email="p2@example.com",
        auth0_sub="auth0|p2",
        role=CustomUser.Role.BUYER,
        tenant=tenant,
        status=CustomUser.Status.PENDING,
    )
    client = force_login(admin_user)
    client.post(f"/api/v1/admin/members/{pending.pk}/approve/")
    assert AuditLog.objects.filter(
        action="member.approve", entity_id=pending.pk
    ).exists()


# ---------------------------------------------------------------------------
# POST /api/v1/admin/members/{id}/suspend
# ---------------------------------------------------------------------------
def test_admin_can_suspend_member(
    db, force_login, admin_user, buyer_user, mock_celery_eager, mock_send_email
):
    client = force_login(admin_user)
    response = client.post(f"/api/v1/admin/members/{buyer_user.pk}/suspend/")
    assert response.status_code == 200
    buyer_user.refresh_from_db()
    assert buyer_user.status == CustomUser.Status.SUSPENDED
    mock_send_email["suspension"].delay.assert_called_once_with(buyer_user.email)


def test_non_admin_cannot_suspend(db, force_login, seller_user, buyer_user):
    client = force_login(seller_user)
    response = client.post(f"/api/v1/admin/members/{buyer_user.pk}/suspend/")
    assert response.status_code == 403
