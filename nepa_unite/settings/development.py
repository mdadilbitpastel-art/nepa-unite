from .base import *  # noqa: F401,F403

DEBUG = True

# Replica router is intentionally inactive in development.
DATABASE_ROUTERS = []

# Run Celery tasks synchronously — no Redis/worker needed in dev.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Disable template and Redis caching in dev.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

# Permissive CORS for local Next.js dev.
CORS_ALLOW_ALL_ORIGINS = True
