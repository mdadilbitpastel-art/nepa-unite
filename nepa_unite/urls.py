from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
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
    path("api/v1/", include("commissions.urls")),

    # HTML UI (dev-mode auth, sessions)
    path("", include("users.urls_html")),
]

# Serve static + uploaded media in dev. In prod a CDN / nginx / WhiteNoise
# fronts these — gunicorn doesn't serve them on its own, and runserver's
# autoresolve only triggers under manage.py runserver.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
