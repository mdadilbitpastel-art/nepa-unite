from django.urls import path
from rest_framework.routers import DefaultRouter

from users.views import (
    AdminMemberViewSet,
    BuyerAddressViewSet,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MemberViewSet,
    RefreshView,
    RegisterView,
    ResetPasswordView,
)

router = DefaultRouter()
router.register(r"members", MemberViewSet, basename="members")
router.register(r"admin/members", AdminMemberViewSet, basename="admin-members")
router.register(r"addresses", BuyerAddressViewSet, basename="addresses")

urlpatterns = [
    path("auth/register", RegisterView.as_view(), name="auth-register"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/refresh", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("auth/forgot-password", ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("auth/reset-password", ResetPasswordView.as_view(), name="auth-reset-password"),
    *router.urls,
]
