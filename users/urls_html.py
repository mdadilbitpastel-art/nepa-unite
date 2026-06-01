"""URL routes for the HTML auth UI (separate from the JSON API routes)."""

from django.urls import path
from django.views.generic import RedirectView

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
    path("dashboard/profile/", views_html.profile_view, name="profile"),
    path("dashboard/change-password/", views_html.change_password_confirm, name="change_password_confirm"),
    path("dashboard/", views_html.dashboard_view, name="dashboard"),
    path("dashboard/sellers/", views_html.admin_sellers_view, name="admin_sellers"),
    path("dashboard/buyers/", views_html.admin_buyers_view, name="admin_buyers"),
    path("dashboard/members/", RedirectView.as_view(pattern_name="admin_sellers", permanent=False)),
    path("dashboard/products/", views_html.seller_products_view, name="seller_products"),
    path("dashboard/products/<uuid:product_id>/", views_html.admin_product_detail, name="admin_product_detail"),
    path("dashboard/products/new/", views_html.seller_product_create, name="seller_product_create"),
    path("dashboard/products/<uuid:product_id>/edit/", views_html.seller_product_edit, name="seller_product_edit"),
    path("dashboard/products/<uuid:product_id>/toggle-status/", views_html.seller_product_toggle_status, name="seller_product_toggle_status"),
    path("dashboard/products/<uuid:product_id>/delete/", views_html.seller_product_delete, name="seller_product_delete"),
    path("dashboard/seller/connect/", views_html.seller_connect_stripe, name="seller_connect_stripe"),
    path("dashboard/orders/", views_html.orders_view, name="orders"),
    path("dashboard/orders/<uuid:order_id>/", views_html.order_detail_view, name="order_detail"),
    path("dashboard/orders/<uuid:order_id>/transition/", views_html.order_transition_view, name="order_transition"),
    path("dashboard/audit-log/", views_html.audit_log_view, name="audit_log"),
    path("dashboard/api/", views_html.api_reference_view, name="api_reference"),
    path("dashboard/health/", views_html.system_health_view, name="system_health"),
    path(
        "dashboard/sellers/<uuid:seller_id>/",
        views_html.admin_seller_detail,
        name="admin_seller_detail",
    ),
    path(
        "dashboard/buyers/<uuid:buyer_id>/",
        views_html.admin_buyer_detail,
        name="admin_buyer_detail",
    ),
    path(
        "dashboard/users/<uuid:user_id>/approve/",
        views_html.admin_approve_user,
        name="admin_approve_user",
    ),
    path(
        "dashboard/users/<uuid:user_id>/suspend/",
        views_html.admin_suspend_user,
        name="admin_suspend_user",
    ),
]
