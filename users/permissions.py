from __future__ import annotations

from rest_framework.permissions import BasePermission

from users.models import CustomUser


class _RoleRequired(BasePermission):
    required_role: str = ""

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", None) == self.required_role
        )


class IsAdmin(_RoleRequired):
    required_role = CustomUser.Role.ADMIN


class IsBuyer(_RoleRequired):
    required_role = CustomUser.Role.BUYER


class IsSeller(_RoleRequired):
    required_role = CustomUser.Role.SELLER


class IsAuditor(_RoleRequired):
    required_role = CustomUser.Role.AUDITOR


class IsSelfOrAdmin(BasePermission):
    """Object-level: allow if request.user is the object, or is an admin."""

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if getattr(user, "role", None) == CustomUser.Role.ADMIN:
            return True
        return obj.pk == user.pk
