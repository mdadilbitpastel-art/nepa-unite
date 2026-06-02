"""Shared settings — everything env-driven via django-environ."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_CORS_ALLOWED_ORIGINS=(list, []),
    DATABASE_REPLICA_URL=(str, ""),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "django_elasticsearch_dsl",
    # Local
    "core",
    "users",
    "products",
    "orders",
    "payments",
    "notifications",
    "webhooks",
    "contracts",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serve static files in production (no nginx/CDN needed on Render).
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.InactivityLogoutMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "nepa_unite.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.session_settings",
            ],
        },
    },
]

# HTML auth flow
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

# Auto sign-out session (dashboard) users after this many seconds of inactivity.
# Sliding window — each request resets it. Enforced by
# core.middleware.InactivityLogoutMiddleware. Default: 5 minutes.
SESSION_INACTIVITY_TIMEOUT = env.int("SESSION_INACTIVITY_TIMEOUT", default=300)

WSGI_APPLICATION = "nepa_unite.wsgi.application"
ASGI_APPLICATION = "nepa_unite.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db_url("DATABASE_URL"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

# Optional: confine this app's tables to a dedicated Postgres schema so a
# single database instance can be shared with another app without table
# collisions. When DB_SCHEMA is set, every connection runs with
# `search_path=<schema>` ONLY (no `public` fallback) — otherwise Django's
# django_migrations lookup would resolve to the *other* app's table living in
# public and raise InconsistentMigrationHistory. The schema is created in
# build.sh before `migrate`. Unset (local dev) → normal `public`, no change.
DB_SCHEMA = env("DB_SCHEMA", default="")
if DB_SCHEMA:
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["options"] = f"-c search_path={DB_SCHEMA}"

# Row-Level Security is FORCEd on tenant tables but no per-request tenant
# context is wired up, so the app's DB role bypasses RLS on every connection
# (see core.apps._bypass_rls). Set DB_BYPASS_RLS=False to enforce policies
# once an `app.current_tenant` mechanism exists.
DB_BYPASS_RLS = env.bool("DB_BYPASS_RLS", default=True)

_replica_url = env("DATABASE_REPLICA_URL")
if _replica_url:
    DATABASES["replica"] = env.db_url_config(_replica_url)

DATABASE_ROUTERS: list[str] = []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.CustomUser"

# ---------------------------------------------------------------------------
# Cache (django-redis) — also Celery uses the same Redis instance.
# Redis is OPTIONAL: if REDIS_URL is unset (e.g. a single-service Render
# deploy) we fall back to local-memory cache and run Celery tasks eagerly,
# so the app boots and serves without an external Redis/worker.
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="")

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }
    CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
    CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
    CELERY_TASK_ALWAYS_EAGER = False
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
    CELERY_TASK_ALWAYS_EAGER = True

CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "users.authentication.Auth0JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": env("API_RATE_LIMIT", default="100/min"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "NEPA Unite API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env("DJANGO_CORS_ALLOWED_ORIGINS")

# ---------------------------------------------------------------------------
# Auth0
# ---------------------------------------------------------------------------
AUTH0_DOMAIN = env("AUTH0_DOMAIN", default="")
AUTH0_AUDIENCE = env("AUTH0_AUDIENCE", default="")
AUTH0_ISSUER = env("AUTH0_ISSUER", default="")
AUTH0_ALGORITHMS = env("AUTH0_ALGORITHMS", default="RS256").split(",")
AUTH0_MGMT_CLIENT_ID = env("AUTH0_MGMT_CLIENT_ID", default="")
AUTH0_MGMT_CLIENT_SECRET = env("AUTH0_MGMT_CLIENT_SECRET", default="")
AUTH0_MGMT_AUDIENCE = env("AUTH0_MGMT_AUDIENCE", default="")
AUTH0_ROLE_CLAIM = "https://nepaunite.com/role"
AUTH0_TENANT_CLAIM = "https://nepaunite.com/tenant_id"

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
STRIPE_CONNECT_CLIENT_ID = env("STRIPE_CONNECT_CLIENT_ID", default="")
STRIPE_PLATFORM_FEE_PERCENT = env.float("STRIPE_PLATFORM_FEE_PERCENT", default=5.0)
STRIPE_ONBOARDING_RETURN_URL = env(
    "STRIPE_ONBOARDING_RETURN_URL", default="https://nepaunite.local/onboarding/return"
)
STRIPE_ONBOARDING_REFRESH_URL = env(
    "STRIPE_ONBOARDING_REFRESH_URL", default="https://nepaunite.local/onboarding/refresh"
)

# Feature flag: when False, seller listings are NOT gated on Stripe Connect
# onboarding (no API 403, no banner, no locked button, no onboarding email).
# Flip to True once a real Stripe Connect account is wired up in the env.
STRIPE_GATE_ENABLED = env.bool("STRIPE_GATE_ENABLED", default=False)

# ---------------------------------------------------------------------------
# AWS / S3
# ---------------------------------------------------------------------------
AWS_REGION = env("AWS_REGION", default="us-east-1")
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_S3_INVOICES_BUCKET = env("AWS_S3_INVOICES_BUCKET", default="")

# ---------------------------------------------------------------------------
# Elasticsearch / OpenSearch
# ---------------------------------------------------------------------------
ELASTICSEARCH_URL = env("OPENSEARCH_URL", default="") or "http://localhost:9200"
ELASTICSEARCH_DSL = {
    "default": {"hosts": ELASTICSEARCH_URL},
}
PRODUCT_SEARCH_INDEX = "products"
# Don't reach ES on every model save — we reindex explicitly via Celery.
ELASTICSEARCH_DSL_AUTOSYNC = False

# ---------------------------------------------------------------------------
# Inventory / low-stock
# ---------------------------------------------------------------------------
LOW_STOCK_THRESHOLD = env.int("LOW_STOCK_THRESHOLD", default=5)
INVENTORY_LOCK_TTL = env.int("INVENTORY_LOCK_TTL", default=10)

# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------
AUTH_RATE_LIMIT = env("AUTH_RATE_LIMIT", default="10/m")
API_RATE_LIMIT = env("API_RATE_LIMIT", default="100/m")

# ---------------------------------------------------------------------------
# Outgoing webhook retry schedule (seconds): 1m, 5m, 30m, 2h, 24h
# ---------------------------------------------------------------------------
OUTGOING_WEBHOOK_RETRY_DELAYS = [60, 300, 1800, 7200, 86400]
OUTGOING_WEBHOOK_TIMEOUT = 10

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL", default="no-reply@nepaunite.local"
)

# ---------------------------------------------------------------------------
# i18n / static
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise: compress static assets and serve them straight from the app.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

# User uploads (product images, etc.). Local filesystem by default; switch to
# Cloudinary automatically when CLOUDINARY_URL is set (e.g. on Render, where
# the local disk is ephemeral). Code that reads `instance.primary_image.url`
# keeps working unchanged either way.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

CLOUDINARY_URL = env("CLOUDINARY_URL", default="")
if CLOUDINARY_URL:
    # The `cloudinary` library auto-configures itself from the CLOUDINARY_URL
    # environment variable, so no extra credentials settings are needed.
    INSTALLED_APPS += ["cloudinary_storage", "cloudinary"]
    STORAGES["default"]["BACKEND"] = (
        "cloudinary_storage.storage.MediaCloudinaryStorage"
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]
