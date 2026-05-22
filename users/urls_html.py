"""URL routes for the HTML auth UI (separate from the JSON API routes)."""

from django.urls import path

from users import views_html

urlpatterns = [
    path("", views_html.home, name="home"),
    path("signup/", views_html.signup_view, name="signup"),
    path("login/", views_html.login_view, name="login"),
    path("logout/", views_html.logout_view, name="logout"),
    path("forgot-password/", views_html.forgot_password_view, name="forgot_password"),
    path(
        "reset-password/<uidb64>/<token>/",
        views_html.reset_password_view,
        name="reset_password",
    ),
    path("pending-approval/", views_html.pending_approval_view, name="pending_approval"),
    path("dashboard/", views_html.dashboard_view, name="dashboard"),
    path(
        "dashboard/members/<uuid:member_id>/approve/",
        views_html.admin_approve_member,
        name="admin_approve_member",
    ),
    path(
        "dashboard/members/<uuid:member_id>/suspend/",
        views_html.admin_suspend_member,
        name="admin_suspend_member",
    ),
]
