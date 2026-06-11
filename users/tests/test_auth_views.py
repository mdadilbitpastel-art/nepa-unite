"""Endpoint tests for /api/v1/auth/{register,login,refresh,logout}.

Auth is self-issued JWT (djangorestframework-simplejwt) — no external IdP, so
these exercise the real token flow rather than mocking a provider.
"""

from __future__ import annotations

import pytest

from rest_framework_simplejwt.tokens import RefreshToken

from users.models import CustomUser, Tenant


@pytest.fixture
def active_buyer_with_password(db, tenant):
    """An approved buyer with a known password, ready to log in."""
    user = CustomUser(
        email="loginuser@example.com",
        auth0_sub="local|loginuser",
        role=CustomUser.Role.BUYER,
        tenant=tenant,
        status=CustomUser.Status.ACTIVE,
    )
    user.set_password("supersecret")
    user.save()
    return user


# ---------------------------------------------------------------------------
# /api/v1/auth/register
# ---------------------------------------------------------------------------
def test_register_creates_active_buyer_and_tenant(db, api_client, mock_send_email):
    payload = {
        "email": "new@example.com",
        "password": "supersecret",
        "role": "buyer",
        "business_name": "Acme Co",
        "vertical_type": "dental",
    }
    response = api_client.post("/api/v1/auth/register", payload, format="json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "buyer"
    # Buyers self-onboard instantly.
    assert body["status"] == "active"

    user = CustomUser.objects.get(email="new@example.com")
    assert user.status == CustomUser.Status.ACTIVE
    # Identity is local now — no external sub.
    assert user.auth0_sub.startswith("local|")
    # Password is stored hashed and usable.
    assert user.check_password("supersecret")
    assert Tenant.objects.filter(pk=user.tenant_id).exists()
    mock_send_email["welcome"].delay.assert_called_once_with("new@example.com")


def test_register_seller_is_pending(db, api_client, mock_send_email):
    response = api_client.post(
        "/api/v1/auth/register",
        {"email": "seller@example.com", "password": "supersecret",
         "role": "seller", "business_name": "S Co", "vertical_type": "dental"},
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["status"] == "pending"


def test_register_rejects_admin_self_signup(db, api_client):
    response = api_client.post(
        "/api/v1/auth/register",
        {"email": "x@y.com", "password": "supersecret",
         "role": "admin", "business_name": "X", "vertical_type": "dental"},
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.json()


def test_register_rejects_duplicate_email(db, api_client, buyer_user):
    response = api_client.post(
        "/api/v1/auth/register",
        {"email": buyer_user.email, "password": "supersecret",
         "role": "buyer", "business_name": "X", "vertical_type": "dental"},
        format="json",
    )
    assert response.status_code == 400


def test_register_rejects_short_password(db, api_client):
    response = api_client.post(
        "/api/v1/auth/register",
        {"email": "n@n.com", "password": "short",
         "role": "buyer", "business_name": "X", "vertical_type": "dental"},
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /api/v1/auth/login
# ---------------------------------------------------------------------------
def test_login_returns_tokens(db, api_client, active_buyer_with_password):
    response = api_client.post(
        "/api/v1/auth/login",
        {"email": "loginuser@example.com", "password": "supersecret"},
        format="json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


def test_login_invalid_credentials_returns_401(db, api_client, active_buyer_with_password):
    response = api_client.post(
        "/api/v1/auth/login",
        {"email": "loginuser@example.com", "password": "wrong"},
        format="json",
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /api/v1/auth/refresh
# ---------------------------------------------------------------------------
def test_refresh_returns_new_access_token(db, api_client, active_buyer_with_password):
    login = api_client.post(
        "/api/v1/auth/login",
        {"email": "loginuser@example.com", "password": "supersecret"},
        format="json",
    )
    refresh_token = login.json()["refresh_token"]

    response = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": refresh_token}, format="json"
    )
    assert response.status_code == 200, response.content
    assert response.json()["access_token"]


def test_refresh_invalid_token_returns_401(db, api_client):
    response = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": "not-a-real-token"}, format="json"
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /api/v1/auth/logout
# ---------------------------------------------------------------------------
def test_logout_requires_authentication(db, api_client):
    response = api_client.post(
        "/api/v1/auth/logout", {"refresh_token": "r"}, format="json"
    )
    assert response.status_code in (401, 403)


def test_logout_blacklists_refresh_token(db, force_login, buyer_user):
    client = force_login(buyer_user)
    refresh = str(RefreshToken.for_user(buyer_user))

    response = client.post(
        "/api/v1/auth/logout", {"refresh_token": refresh}, format="json"
    )
    assert response.status_code == 200

    # The blacklisted token can no longer be refreshed.
    again = client.post(
        "/api/v1/auth/refresh", {"refresh_token": refresh}, format="json"
    )
    assert again.status_code == 401
