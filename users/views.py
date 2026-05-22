from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.tasks import (
    send_approval_email,
    send_suspension_email,
    send_welcome_email,
)
from users import auth0_client
from users.models import CustomUser, Tenant
from users.permissions import IsAdmin, IsSelfOrAdmin
from users.serializers import (
    LoginSerializer,
    LogoutSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    RefreshSerializer,
    RegisterResponseSerializer,
    RegisterSerializer,
    TokenResponseSerializer,
)
from core.tasks import write_audit_log

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /api/v1/auth/*
# ---------------------------------------------------------------------------
@method_decorator(
    ratelimit(key="ip", rate=settings.AUTH_RATE_LIMIT, method="POST", block=True),
    name="post",
)
class RegisterView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            auth0_user = auth0_client.create_user(
                email=data["email"], password=data["password"]
            )
        except auth0_client.Auth0APIError as exc:
            return Response(
                {"detail": "Auth0 registration failed", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        with transaction.atomic():
            tenant = Tenant.objects.create(
                name=data["business_name"],
                vertical_type=data["vertical_type"],
                status=Tenant.Status.PENDING,
            )
            user = CustomUser.objects.create(
                email=data["email"],
                auth0_sub=auth0_user["user_id"],
                role=data["role"],
                tenant=tenant,
                status=CustomUser.Status.PENDING,
            )

        send_welcome_email.delay(user.email)
        return Response(
            RegisterResponseSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


@method_decorator(
    ratelimit(key="ip", rate=settings.AUTH_RATE_LIMIT, method="POST", block=True),
    name="post",
)
class LoginView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tokens = auth0_client.login(
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except auth0_client.Auth0APIError as exc:
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(TokenResponseSerializer(tokens).data)


class RefreshView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tokens = auth0_client.refresh(serializer.validated_data["refresh_token"])
        except auth0_client.Auth0APIError:
            return Response(
                {"detail": "Invalid refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(TokenResponseSerializer(tokens).data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            auth0_client.revoke_refresh_token(
                serializer.validated_data["refresh_token"]
            )
        except auth0_client.Auth0APIError as exc:
            logger.warning("Auth0 revoke failed: %s", exc)
            return Response(
                {"detail": "Logout failed"}, status=status.HTTP_502_BAD_GATEWAY
            )
        return Response(status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# /api/v1/members/{id}
# ---------------------------------------------------------------------------
class MemberViewSet(viewsets.ViewSet):
    """Retrieve/update a member.

    Buyers and sellers can only see/update themselves; admins see anyone.
    """

    permission_classes = [IsAuthenticated, IsSelfOrAdmin]

    def retrieve(self, request, pk=None):
        member = get_object_or_404(CustomUser, pk=pk)
        self.check_object_permissions(request, member)
        return Response(MemberSerializer(member).data)

    def partial_update(self, request, pk=None):
        member = get_object_or_404(CustomUser, pk=pk)
        self.check_object_permissions(request, member)
        serializer = MemberUpdateSerializer(member, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MemberSerializer(member).data)


# ---------------------------------------------------------------------------
# /api/v1/admin/members/{id}/{approve,suspend}
# ---------------------------------------------------------------------------
class AdminMemberViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsAdmin]

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        member = get_object_or_404(CustomUser, pk=pk)
        if member.status == CustomUser.Status.ACTIVE:
            return Response(
                {"detail": "Member already active"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        member.status = CustomUser.Status.ACTIVE
        member.save(update_fields=["status", "updated_at"])
        write_audit_log.delay(
            actor_id=str(request.user.pk),
            action="member.approve",
            entity_type="CustomUser",
            entity_id=str(member.pk),
            payload={"new_status": member.status},
        )
        send_approval_email.delay(member.email)
        return Response(MemberSerializer(member).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        member = get_object_or_404(CustomUser, pk=pk)
        if member.status == CustomUser.Status.SUSPENDED:
            return Response(
                {"detail": "Member already suspended"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        member.status = CustomUser.Status.SUSPENDED
        member.save(update_fields=["status", "updated_at"])
        write_audit_log.delay(
            actor_id=str(request.user.pk),
            action="member.suspend",
            entity_type="CustomUser",
            entity_id=str(member.pk),
            payload={"new_status": member.status},
        )
        send_suspension_email.delay(member.email)
        return Response(MemberSerializer(member).data)
