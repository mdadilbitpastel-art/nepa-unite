from .base import *  # noqa: F401,F403

DEBUG = False

# Staging mirrors prod behavior; replica routing is opt-in via env.
if "replica" in DATABASES:  # noqa: F405
    DATABASE_ROUTERS = ["nepa_unite.routers.PrimaryReplicaRouter"]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
