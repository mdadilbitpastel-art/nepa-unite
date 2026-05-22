from .base import *  # noqa: F401,F403

DEBUG = True

# Replica router is intentionally inactive in development.
DATABASE_ROUTERS = []

# Allow eager Celery for local debugging if desired.
CELERY_TASK_ALWAYS_EAGER = False

# Permissive CORS for local Next.js dev.
CORS_ALLOW_ALL_ORIGINS = True
