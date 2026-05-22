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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
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
            ],
        },
    },
]

# HTML auth flow
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

WSGI_APPLICATION = "nepa_unite.wsgi.application"
ASGI_APPLICATION = "nepa_unite.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db_url("DATABASE_URL"),
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

_replica_url = env("DATABASE_REPLICA_URL")
if _replica_url:
    DATABASES["replica"] = env.db_url_config(_replica_url)

DATABASE_ROUTERS: list[str] = []

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "users.CustomUser"

# ---------------------------------------------------------------------------
# Cache (django-redis) — also Celery uses the same Redis instance
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = False
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
    default="django.core.mail.backends.console.EmailBackend",
)
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

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]
