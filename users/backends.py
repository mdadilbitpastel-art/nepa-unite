"""Auth0 authentication backend.

Validates Auth0-issued JWTs using the tenant's JWKS endpoint, then looks up
(or creates) the corresponding CustomUser record.

The JWKS document is cached in Redis to avoid hitting Auth0 on every request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from jose import jwt
from jose.exceptions import (
    ExpiredSignatureError,
    JWTClaimsError,
    JWTError,
)

logger = logging.getLogger(__name__)

JWKS_CACHE_KEY = "auth0:jwks"
JWKS_CACHE_TTL = 60 * 60  # 1 hour


class Auth0Error(Exception):
    """Base error for Auth0 token failures."""


class TokenExpiredError(Auth0Error):
    pass


class InvalidSignatureError(Auth0Error):
    pass


class InvalidClaimsError(Auth0Error):
    pass


class MissingTokenError(Auth0Error):
    pass


def _jwks_url() -> str:
    return f"https://{settings.AUTH0_DOMAIN}/.well-known/jwks.json"


def fetch_jwks(force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = cache.get(JWKS_CACHE_KEY)
        if cached:
            return json.loads(cached)
    response = requests.get(_jwks_url(), timeout=5)
    response.raise_for_status()
    jwks = response.json()
    cache.set(JWKS_CACHE_KEY, json.dumps(jwks), JWKS_CACHE_TTL)
    return jwks


def _signing_key(token: str) -> dict[str, Any] | None:
    unverified = jwt.get_unverified_header(token)
    kid = unverified.get("kid")
    if not kid:
        return None
    for key in fetch_jwks().get("keys", []):
        if key.get("kid") == kid:
            return key
    # Possibly rotated — refresh once.
    for key in fetch_jwks(force_refresh=True).get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


def validate_token(token: str) -> dict[str, Any]:
    """Validate an Auth0 JWT and return its claims.

    Raises Auth0Error subclasses; callers translate these into 401s.
    """
    if not token:
        raise MissingTokenError("Missing bearer token")

    try:
        key = _signing_key(token)
    except JWTError as exc:
        raise InvalidSignatureError(str(exc)) from exc

    if key is None:
        raise InvalidSignatureError("Signing key not found in JWKS")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=settings.AUTH0_ALGORITHMS,
            audience=settings.AUTH0_AUDIENCE,
            issuer=settings.AUTH0_ISSUER,
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError(str(exc)) from exc
    except JWTClaimsError as exc:
        raise InvalidClaimsError(str(exc)) from exc
    except JWTError as exc:
        raise InvalidSignatureError(str(exc)) from exc

    return claims


def resolve_user(claims: dict[str, Any]):
    """Find or create the CustomUser corresponding to a verified JWT.

    Role and tenant_id come from Auth0 custom claims. We trust them only
    because the JWT signature has already been verified.
    """
    from users.models import CustomUser

    sub = claims.get("sub")
    if not sub:
        raise InvalidClaimsError("Token has no sub claim")

    email = claims.get("email") or f"{sub}@placeholder.local"
    role = claims.get(settings.AUTH0_ROLE_CLAIM) or CustomUser.Role.BUYER
    tenant_id = claims.get(settings.AUTH0_TENANT_CLAIM)

    user, created = CustomUser.objects.get_or_create(
        auth0_sub=sub,
        defaults={"email": email, "role": role, "tenant_id": tenant_id},
    )
    # Keep mutable claims in sync.
    dirty = False
    if user.role != role:
        user.role = role
        dirty = True
    if tenant_id and str(user.tenant_id) != str(tenant_id):
        user.tenant_id = tenant_id
        dirty = True
    if dirty:
        user.save(update_fields=["role", "tenant", "updated_at"])
    return user
