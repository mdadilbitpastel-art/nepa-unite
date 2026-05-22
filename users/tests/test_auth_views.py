"""Endpoint tests for /api/v1/auth/{register,login,refresh,logout}."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from users.models import CustomUser, Tenant


@pytest.fixture
def auth0_mocks():
    with patch("users.views.auth0_client.create_user") as create, \
         patch("users.views.auth0_client.login") as login, \
         patch("users.views.auth0_client.refresh") as refresh, \
         patch("users.views.auth0_client.revoke_refresh_token") as revoke:
        create.return_value = {"user_id": "auth0|new-user"}
        login.return_value = {
            "access_token": "access-x",
            "refresh_token": "refresh-x",
            "expires_in": 3600,
        }
        refresh.return_value = {"access_token": "access-y", "expires_in": 3600}
        yield {"create": create, "login": login, "refresh": refresh, "revoke": revoke}


# ---------------------------------------------------------------------------
# /api/v1/auth/register
# ---------------------------------------------------------------------------
def test_register_creates_pending_user_and_tenant(db, api_client, auth0_mocks, mock_send_email):
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
    assert body["status"] == "pending"

    user = CustomUser.objects.get(email="new@example.com")
    assert user.status == CustomUser.Status.PENDING
    assert user.auth0_sub == "auth0|new-user"
    assert Tenant.objects.filter(pk=user.tenant_id).exists()
    mock_send_email["welcome"].delay.assert_called_once_with("new@example.com")


def test_register_rejects_admin_self_signup(db, api_client, auth0_mocks):
    response = api_client.post(
        "/api/v1/auth/register",
        {"email": "x@y.com", "password": "supersecret",
         "role": "admin", "business_name": "X", "vertical_type": "dental"},
        format="json",
    )
    assert response.status_code == 400
    assert "role" in response.json()


def test_register_rejects_duplicate_email(db, api_client, auth0_mocks, buyer_user):
    response = api_client.post(
        "/api/v1/auth/register",
        {"email": buyer_user.email, "password": "supersecret",
         "role": "buyer", "business_name": "X", "vertical_type": "dental"},
        format="json",
    )
    assert response.status_code == 400


def test_register_rejects_short_password(db, api_client, auth0_mocks):
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
def test_login_returns_tokens(db, api_client, auth0_mocks):
    response = api_client.post(
        "/api/v1/auth/login",
        {"email": "a@b.com", "password": "supersecret"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "access-x"


def test_login_invalid_credentials_returns_401(db, api_client, auth0_mocks):
    from users.auth0_client import Auth0APIError
    auth0_mocks["login"].side_effect = Auth0APIError("bad creds", 403)
    response = api_client.post(
        "/api/v1/auth/login",
        {"email": "a@b.com", "password": "wrong"},
        format="json",
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /api/v1/auth/refresh
# ---------------------------------------------------------------------------
def test_refresh_returns_new_access_token(db, api_client, auth0_mocks):
    response = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": "r"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "access-y"


def test_refresh_invalid_token_returns_401(db, api_client, auth0_mocks):
    from users.auth0_client import Auth0APIError
    auth0_mocks["refresh"].side_effect = Auth0APIError("nope", 401)
    response = api_client.post(
        "/api/v1/auth/refresh", {"refresh_token": "bad"}, format="json"
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


def test_logout_revokes_refresh_token(db, force_login, buyer_user, auth0_mocks):
    client = force_login(buyer_user)
    response = client.post(
        "/api/v1/auth/logout", {"refresh_token": "r"}, format="json"
    )
    assert response.status_code == 200
    auth0_mocks["revoke"].assert_called_once_with("r")
