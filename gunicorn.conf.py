"""Gunicorn configuration.

Auto-loaded by gunicorn from the working directory, so it applies even when
the platform start command is just `gunicorn nepa_unite.wsgi:application`
(no flags) — no dashboard / blueprint change needed.

Render's free tier has 512 MB RAM. Four workers each importing the full app
(stripe, elasticsearch, boto3) OOM-killed the instance. One preloaded worker
(shared memory) with threads for concurrency fits comfortably.
"""

import os

# Bind to the port Render injects (defaults to 10000 locally if unset).
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

workers = 1
threads = 4
worker_class = "gthread"
timeout = 120
preload_app = True

accesslog = "-"
errorlog = "-"
