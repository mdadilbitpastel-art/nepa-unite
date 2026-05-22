"""Auth0 JWT validation: valid, expired, bad signature, missing, wrong audience."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from jose import jwt

from users import backends
from users.authentication import Auth0JWTAuthentication


# ---------------------------------------------------------------------------
# Test helpers — build an HS256 token and a matching "JWKS" key.
#
# We patch out the real RS256 JWKS fetch so tests don't hit the network. The
# Auth0JWTAuthentication code-path is identical; only the signing algo
# differs.
# ---------------------------------------------------------------------------
HS_SECRET = "test-secret"


def _make_token(**overrides):
    now = int(time.time())
    claims = {
        "iss": "https://test.auth0.com/",
        "aud": "https://api.nepaunite.test",
        "sub": "auth0|user-abc",
        "iat": now,
        "exp": now + 600,
        "https://nepaunite.com/role": "buyer",
        "https://nepaunite.com/tenant_id": None,
        "email": "test@example.com",
    }
    claims.update(overrides)
    return jwt.encode(claims, HS_SECRET, algorithm="HS256", headers={"kid": "test-kid"})


@pytest.fixture(autouse=True)
def patch_auth0(settings):
    settings.AUTH0_DOMAIN = "test.auth0.com"
    settings.AUTH0_AUDIENCE = "https://api.nepaunite.test"
    settings.AUTH0_ISSUER = "https://test.auth0.com/"
    settings.AUTH0_ALGORITHMS = ["HS256"]
    with patch.object(backends, "_signing_key", return_value=HS_SECRET):
        yield


def test_validate_token_success(db):
    token = _make_token()
    claims = backends.validate_token(token)
    assert claims["sub"] == "auth0|user-abc"


def test_validate_token_expired():
    token = _make_token(exp=int(time.time()) - 60, iat=int(time.time()) - 300)
    with pytest.raises(backends.TokenExpiredError):
        backends.validate_token(token)


def test_validate_token_wrong_audience():
    token = _make_token(aud="https://wrong-audience")
    with pytest.raises(backends.InvalidClaimsError):
        backends.validate_token(token)


def test_validate_token_invalid_signature():
    token = jwt.encode(
        {"iss": "https://test.auth0.com/", "aud": "https://api.nepaunite.test",
         "sub": "auth0|user-abc", "exp": int(time.time()) + 600},
        "the-wrong-secret",
        algorithm="HS256",
        headers={"kid": "test-kid"},
    )
    with pytest.raises(backends.InvalidSignatureError):
        backends.validate_token(token)


def test_validate_token_missing():
    with pytest.raises(backends.MissingTokenError):
        backends.validate_token("")


# ---------------------------------------------------------------------------
# Authentication class wiring — confirms DRF surfaces the right HTTP errors.
# ---------------------------------------------------------------------------
class _FakeRequest:
    def __init__(self, header_value: str = ""):
        self.META = {"HTTP_AUTHORIZATION": header_value} if header_value else {}


def test_authentication_returns_none_when_no_header():
    auth = Auth0JWTAuthentication()
    assert auth.authenticate(_FakeRequest()) is None


def test_authentication_rejects_malformed_header():
    from rest_framework import exceptions
    auth = Auth0JWTAuthentication()
    with pytest.raises(exceptions.AuthenticationFailed):
        auth.authenticate(_FakeRequest("Token abc.def.ghi"))


def test_authentication_success_creates_user(db):
    token = _make_token()
    auth = Auth0JWTAuthentication()
    user, claims = auth.authenticate(_FakeRequest(f"Bearer {token}"))
    assert user is not None
    assert user.auth0_sub == "auth0|user-abc"
    assert claims["sub"] == "auth0|user-abc"


def test_authentication_expired_token_returns_401(db):
    from rest_framework import exceptions
    token = _make_token(exp=int(time.time()) - 60, iat=int(time.time()) - 300)
    auth = Auth0JWTAuthentication()
    with pytest.raises(exceptions.AuthenticationFailed):
        auth.authenticate(_FakeRequest(f"Bearer {token}"))
