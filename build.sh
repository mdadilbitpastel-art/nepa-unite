#!/usr/bin/env bash
# Render build script. Runs on every deploy before the service starts.
set -o errexit

pip install -r requirements.txt

# Gather static assets into STATIC_ROOT (served by WhiteNoise).
python manage.py collectstatic --no-input

# When sharing a Postgres instance via a dedicated schema, make sure it
# exists before migrate creates tables inside it.
if [ -n "$DB_SCHEMA" ]; then
  echo "Ensuring schema \"$DB_SCHEMA\" exists..."
  python manage.py shell -c "from django.db import connection; connection.cursor().execute('CREATE SCHEMA IF NOT EXISTS \"$DB_SCHEMA\"')"
fi

# Apply DB migrations against the Postgres instance.
python manage.py migrate --no-input

# Free tier has no Shell, so create the admin from env vars (idempotent —
# skips if it already exists, or if the env vars are not set).
python manage.py ensure_admin
