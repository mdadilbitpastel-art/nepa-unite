from __future__ import annotations

from rest_framework import exceptions
from rest_framework_simplejwt.authentication import (
    JWTAuthentication as BaseJWTAuthentication,
)


class JWTAuthentication(BaseJWTAuthentication):
    """SimpleJWT auth with a single account-state enforcement point.

    Only ACTIVE accounts may use the API. Pending users can hold a valid
    token (issued at registration/login) but are rejected on EVERY request
    until an admin approves them; suspended users are rejected too. Centralising
    the check here means individual views/permissions don't have to re-check.
    (DRF's ``is_authenticated`` alone does NOT cover account state.)
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        # Imported lazily to avoid an app-registry import cycle at startup.
        from users.models import CustomUser

        if user.status != CustomUser.Status.ACTIVE:
            raise exceptions.AuthenticationFailed(
                f"Account is {user.status}; access requires an active account."
            )
        return user
