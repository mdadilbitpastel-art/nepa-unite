"""Thin Auth0 Management + Auth API client.

We only call the four endpoints we need from Django:
- POST /api/v2/users          (Management; create a user during registration)
- POST /oauth/token            (Auth; password-grant for login, refresh, M2M)
- POST /oauth/revoke           (Auth; revoke refresh tokens on logout)

Token caching for the M2M (management) credential lives in the Django cache.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

MGMT_TOKEN_CACHE_KEY = "auth0:mgmt_token"


class Auth0APIError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _base() -> str:
    return f"https://{settings.AUTH0_DOMAIN}"


def _get_mgmt_token() -> str:
    token = cache.get(MGMT_TOKEN_CACHE_KEY)
    if token:
        return token
    resp = requests.post(
        f"{_base()}/oauth/token",
        json={
            "client_id": settings.AUTH0_MGMT_CLIENT_ID,
            "client_secret": settings.AUTH0_MGMT_CLIENT_SECRET,
            "audience": settings.AUTH0_MGMT_AUDIENCE,
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise Auth0APIError(
            f"Failed to obtain Auth0 management token: {resp.text}",
            resp.status_code,
        )
    data = resp.json()
    cache.set(
        MGMT_TOKEN_CACHE_KEY,
        data["access_token"],
        # Refresh ~5 min before expiry.
        max(int(data.get("expires_in", 3600)) - 300, 60),
    )
    return data["access_token"]


def create_user(email: str, password: str) -> dict[str, Any]:
    """Create an Auth0 user via the Management API. Returns the user JSON."""
    token = _get_mgmt_token()
    resp = requests.post(
        f"{_base()}/api/v2/users",
        json={
            "email": email,
            "password": password,
            "connection": "Username-Password-Authentication",
            "email_verified": False,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code not in (200, 201):
        raise Auth0APIError(
            f"Auth0 create_user failed: {resp.text}", resp.status_code
        )
    return resp.json()


def login(email: str, password: str) -> dict[str, Any]:
    """Resource-Owner-Password grant. Returns access + refresh tokens."""
    resp = requests.post(
        f"{_base()}/oauth/token",
        json={
            "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
            "username": email,
            "password": password,
            "audience": settings.AUTH0_AUDIENCE,
            "scope": "openid profile email offline_access",
            "realm": "Username-Password-Authentication",
            "client_id": settings.AUTH0_MGMT_CLIENT_ID,
            "client_secret": settings.AUTH0_MGMT_CLIENT_SECRET,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise Auth0APIError(f"Auth0 login failed: {resp.text}", resp.status_code)
    return resp.json()


def refresh(refresh_token: str) -> dict[str, Any]:
    resp = requests.post(
        f"{_base()}/oauth/token",
        json={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.AUTH0_MGMT_CLIENT_ID,
            "client_secret": settings.AUTH0_MGMT_CLIENT_SECRET,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise Auth0APIError(f"Auth0 refresh failed: {resp.text}", resp.status_code)
    return resp.json()


def revoke_refresh_token(refresh_token: str) -> None:
    resp = requests.post(
        f"{_base()}/oauth/revoke",
        json={
            "token": refresh_token,
            "client_id": settings.AUTH0_MGMT_CLIENT_ID,
            "client_secret": settings.AUTH0_MGMT_CLIENT_SECRET,
        },
        timeout=10,
    )
    if resp.status_code not in (200, 204):
        raise Auth0APIError(f"Auth0 revoke failed: {resp.text}", resp.status_code)
