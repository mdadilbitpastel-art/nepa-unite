FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=nepa_unite.settings.production

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app
RUN chown -R app:app /app

USER app

EXPOSE 8000

# Collect static at image build time (no runtime DB needed).
RUN python manage.py collectstatic --noinput || true

CMD ["gunicorn", "nepa_unite.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
