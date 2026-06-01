from __future__ import annotations

from rest_framework import serializers

from users.models import BuyerAddress, CustomUser, Tenant, WorkflowTemplate


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    role = serializers.ChoiceField(choices=CustomUser.Role.choices)
    business_name = serializers.CharField(max_length=255)
    vertical_type = serializers.ChoiceField(choices=WorkflowTemplate.Vertical.choices)

    def validate_email(self, value: str) -> str:
        if CustomUser.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_role(self, value: str) -> str:
        # Admins cannot self-register.
        if value == CustomUser.Role.ADMIN:
            raise serializers.ValidationError("Admin accounts cannot self-register.")
        return value


class RegisterResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ("id", "email", "role", "status")


# ---------------------------------------------------------------------------
# Login / refresh / logout
# ---------------------------------------------------------------------------
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class TokenResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField(required=False, allow_blank=True)
    expires_in = serializers.IntegerField()


class RefreshSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh_token = serializers.CharField()


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)


class BuyerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyerAddress
        fields = (
            "id", "label", "recipient_name", "phone",
            "line1", "line2", "city", "state", "zip_code", "country",
            "is_default", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


# ---------------------------------------------------------------------------
# Member profile
# ---------------------------------------------------------------------------
class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ("id", "name", "vertical_type", "status")
        read_only_fields = ("id", "status")


class MemberSerializer(serializers.ModelSerializer):
    tenant = TenantSerializer(read_only=True)

    class Meta:
        model = CustomUser
        fields = (
            "id", "email", "role", "status", "tenant",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "email", "role", "status",
            "tenant", "created_at", "updated_at",
        )


class MemberUpdateSerializer(serializers.ModelSerializer):
    """Members can update their own profile. Admins can update any.

    Only safe fields exposed here — role/status flow through admin endpoints.
    """

    class Meta:
        model = CustomUser
        fields = ("email",)

    def validate_email(self, value: str) -> str:
        normalized = value.lower()
        qs = CustomUser.objects.filter(email__iexact=normalized)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Email already in use.")
        return normalized
