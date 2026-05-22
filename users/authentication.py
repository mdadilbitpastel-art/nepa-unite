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
        return (user, claims)

    def authenticate_header(self, request):
        return self.keyword
