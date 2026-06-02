"""Auth0 JWT authentication — account-state enforcement.

Only ACTIVE accounts may authenticate against the API. Suspended/pending
accounts are rejected at the authentication layer (every request, every role).
The Auth0 token validation + user resolution are mocked; we only assert the
status gate here.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from users.authentication import Auth0JWTAuthentication
from users.models import CustomUser


def _request():
    return APIRequestFactory().get("/", HTTP_AUTHORIZATION="Bearer faketoken")


def _make(tenant, status, sub):
    return CustomUser.objects.create(
        email=f"{sub}@example.com", auth0_sub=f"auth0|{sub}",
        role=CustomUser.Role.BUYER, tenant=tenant, status=status,
    )


def _authenticate(user):
    with patch("users.authentication.validate_token", return_value={"sub": user.auth0_sub}), \
         patch("users.authentication.resolve_user", return_value=user):
        return Auth0JWTAuthentication().authenticate(_request())


def test_active_user_authenticates(db, tenant):
    user = _make(tenant, CustomUser.Status.ACTIVE, "active")
    result = _authenticate(user)
    assert result is not None
    assert result[0] == user


def test_suspended_user_is_rejected(db, tenant):
    user = _make(tenant, CustomUser.Status.SUSPENDED, "susp")
    with pytest.raises(exceptions.AuthenticationFailed):
        _authenticate(user)


def test_pending_user_is_rejected(db, tenant):
    user = _make(tenant, CustomUser.Status.PENDING, "pend")
    with pytest.raises(exceptions.AuthenticationFailed):
        _authenticate(user)


def test_no_auth_header_returns_none(db):
    # No credentials → None (lets AllowAny endpoints through).
    assert Auth0JWTAuthentication().authenticate(APIRequestFactory().get("/")) is None
