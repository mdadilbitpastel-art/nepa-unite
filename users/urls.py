from django.urls import path
from rest_framework.routers import DefaultRouter

from users.views import (
    AdminMemberViewSet,
    LoginView,
    LogoutView,
    MemberViewSet,
    RefreshView,
    RegisterView,
)

router = DefaultRouter()
router.register(r"members", MemberViewSet, basename="members")
router.register(r"admin/members", AdminMemberViewSet, basename="admin-members")

urlpatterns = [
    path("auth/register", RegisterView.as_view(), name="auth-register"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/refresh", RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    *router.urls,
]
