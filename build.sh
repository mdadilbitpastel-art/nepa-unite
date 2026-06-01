#!/usr/bin/env bash
# Render build script. Runs on every deploy before the service starts.
set -o errexit

pip install -r requirements.txt

# Gather static assets into STATIC_ROOT (served by WhiteNoise).
python manage.py collectstatic --no-input

# Apply DB migrations against the Render Postgres instance.
python manage.py migrate --no-input
