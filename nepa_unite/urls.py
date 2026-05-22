from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    # OpenAPI / Swagger
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),

    # Health
    path("api/", include("core.urls")),

    # v1 JSON API
    path("api/v1/", include("users.urls")),
    path("api/v1/", include("products.urls")),
    path("api/v1/", include("orders.urls")),
    path("api/v1/", include("payments.urls")),
    path("api/v1/", include("webhooks.urls")),

    # HTML UI (dev-mode auth, sessions)
    path("", include("users.urls_html")),
]
