"""JWT authentication — account-state enforcement.

Only ACTIVE accounts may authenticate against the API. Suspended/pending
accounts are rejected at the authentication layer (every request, every role).
Tokens are real self-issued SimpleJWT access tokens; we assert the status gate.
"""

from __future__ import annotations

import pytest
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import AccessToken

from users.authentication import JWTAuthentication
from users.models import CustomUser


def _make(tenant, status, sub):
    return CustomUser.objects.create(
        email=f"{sub}@example.com", auth0_sub=f"local|{sub}",
        role=CustomUser.Role.BUYER, tenant=tenant, status=status,
    )


def _authenticate(user):
    token = str(AccessToken.for_user(user))
    request = APIRequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}")
    return JWTAuthentication().authenticate(request)


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
    assert JWTAuthentication().authenticate(APIRequestFactory().get("/")) is None
