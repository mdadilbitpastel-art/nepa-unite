import os

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, DATABASES  # noqa: F401

DEBUG = False

# ---------------------------------------------------------------------------
# Render: the platform injects RENDER_EXTERNAL_HOSTNAME at runtime. Add it to
# ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS automatically so we never have to hard-
# code the *.onrender.com URL. Extra hosts (custom domains) can still be set
# via DJANGO_ALLOWED_HOSTS in the environment.
# ---------------------------------------------------------------------------
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# HTTPS form posts (login, etc.) need the origin to be trusted.
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}"
    for host in ALLOWED_HOSTS
    if host not in ("localhost", "127.0.0.1")
]

# Replica router is only safe when a replica DB is actually configured.
DATABASE_ROUTERS = (
    ["nepa_unite.routers.PrimaryReplicaRouter"] if "replica" in DATABASES else []
)

# ---------------------------------------------------------------------------
# Security hardening (behind Render's TLS-terminating proxy)
# ---------------------------------------------------------------------------
# Render terminates TLS and already redirects HTTP→HTTPS at the edge, so an
# app-level redirect is off by default (it can trip internal health checks).
# Flip on with DJANGO_SECURE_SSL_REDIRECT=True if serving a custom domain.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "False") == "True"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
