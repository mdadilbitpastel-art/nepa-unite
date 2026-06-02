from __future__ import annotations

from rest_framework import authentication, exceptions

from users.backends import (
    Auth0Error,
    InvalidClaimsError,
    InvalidSignatureError,
    MissingTokenError,
    TokenExpiredError,
    resolve_user,
    validate_token,
)


class Auth0JWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header:
            return None  # Lets AllowAny views through.

        parts = header.split()
        if parts[0].lower() != self.keyword.lower() or len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed Authorization header")

        token = parts[1]
        try:
            claims = validate_token(token)
        except TokenExpiredError:
            raise exceptions.AuthenticationFailed("Token expired")
        except InvalidSignatureError:
            raise exceptions.AuthenticationFailed("Invalid token signature")
        except InvalidClaimsError as exc:
            raise exceptions.AuthenticationFailed(f"Invalid token claims: {exc}")
        except MissingTokenError:
            raise exceptions.AuthenticationFailed("Missing token")
        except Auth0Error as exc:
            raise exceptions.AuthenticationFailed(str(exc))

        user = resolve_user(claims)

        # Single enforcement point for account state: only ACTIVE accounts may
        # use the API. Suspended/pending users are rejected on EVERY request,
        # for every role and every CRUD operation, so individual views don't
        # have to re-check. (is_authenticated alone does NOT cover this.)
        from users.models import CustomUser

        if user.status != CustomUser.Status.ACTIVE:
            raise exceptions.AuthenticationFailed(
                f"Account is {user.status}; access requires an active account."
            )

        return (user, claims)

    def authenticate_header(self, request):
        return self.keyword
