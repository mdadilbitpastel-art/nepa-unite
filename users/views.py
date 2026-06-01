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

from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from notifications.tasks import (
    send_approval_email,
    send_password_reset_email,
    send_seller_onboarding_email,
    send_suspension_email,
    send_welcome_email,
)
from users import auth0_client
from users.models import BuyerAddress, CustomUser, Tenant
from users.permissions import IsAdmin, IsBuyer, IsSelfOrAdmin
from users.serializers import (
    BuyerAddressSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    MemberSerializer,
    MemberUpdateSerializer,
    RefreshSerializer,
    RegisterResponseSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
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

        # Buyers self-onboard instantly; sellers wait for admin review
        # because they list products and receive payouts.
        is_buyer = data["role"] == CustomUser.Role.BUYER
        user_status = (
            CustomUser.Status.ACTIVE if is_buyer else CustomUser.Status.PENDING
        )
        tenant_status = (
            Tenant.Status.ACTIVE if is_buyer else Tenant.Status.PENDING
        )

        with transaction.atomic():
            tenant = Tenant.objects.create(
                name=data["business_name"],
                vertical_type=data["vertical_type"],
                status=tenant_status,
            )
            user = CustomUser.objects.create(
                email=data["email"],
                auth0_sub=auth0_user["user_id"],
                role=data["role"],
                tenant=tenant,
                status=user_status,
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
        except auth0_client.Auth0APIError:
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


@method_decorator(
    ratelimit(key="ip", rate=settings.AUTH_RATE_LIMIT, method="POST", block=True),
    name="post",
)
class ForgotPasswordView(APIView):
    """Email a reset link. Always returns 200 so this can't be used for
    user enumeration."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].lower()
        user = CustomUser.objects.filter(email__iexact=email).first()
        if user is not None:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_path = reverse("reset_password", args=[uidb64, token])
            full_url = request.build_absolute_uri(reset_path)
            send_password_reset_email.delay(user.email, full_url)
        return Response({"detail": "If an account exists, a reset email has been sent."})


class ResetPasswordView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]
        try:
            pk = urlsafe_base64_decode(uid).decode()
            user = CustomUser.objects.get(pk=pk)
        except (CustomUser.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"detail": "Invalid or expired reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Invalid or expired reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.save(update_fields=["password", "updated_at"])
        return Response({"detail": "Password updated."})


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
        # If this is the first member approved on a still-pending tenant,
        # activate the tenant too.
        if member.tenant_id and member.tenant.status == Tenant.Status.PENDING:
            member.tenant.status = Tenant.Status.ACTIVE
            member.tenant.save(update_fields=["status"])
        write_audit_log.delay(
            actor_id=str(request.user.pk),
            action="member.approve",
            entity_type="CustomUser",
            entity_id=str(member.pk),
            payload={"new_status": member.status},
        )
        send_approval_email.delay(member.email)
        # Sellers can't actually receive payouts until they finish Stripe
        # Connect onboarding — nudge them with a separate email. Suppressed
        # when the gate flag is off (Stripe not yet provisioned).
        if (
            settings.STRIPE_GATE_ENABLED
            and member.role == CustomUser.Role.SELLER
            and not member.stripe_account_id
        ):
            send_seller_onboarding_email.delay(member.email)
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


# ---------------------------------------------------------------------------
# /api/v1/addresses — buyer address book
# ---------------------------------------------------------------------------
class BuyerAddressViewSet(viewsets.ModelViewSet):
    """CRUD over the authenticated buyer's saved shipping addresses."""

    serializer_class = BuyerAddressSerializer
    permission_classes = [IsAuthenticated, IsBuyer]

    def get_queryset(self):
        return BuyerAddress.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        addr = serializer.save(user=self.request.user)
        if addr.is_default:
            BuyerAddress.objects.filter(user=self.request.user).exclude(pk=addr.pk).update(is_default=False)

    def perform_update(self, serializer):
        addr = serializer.save()
        if addr.is_default:
            BuyerAddress.objects.filter(user=self.request.user).exclude(pk=addr.pk).update(is_default=False)

    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        addr = get_object_or_404(BuyerAddress, pk=pk, user=request.user)
        BuyerAddress.objects.filter(user=request.user).update(is_default=False)
        addr.is_default = True
        addr.save(update_fields=["is_default", "updated_at"])
        return Response(BuyerAddressSerializer(addr).data)
