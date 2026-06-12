# NEPA Unite

Regional B2B marketplace backend for local businesses in **Northeastern
Pennsylvania**. Multi-tenant, vertical-aware (dental, architectural,
dry-cleaning, law office, etc.), with the platform handling member
onboarding, product catalog, orders, Stripe-Connect payments,
category-based seller commissions, and invoice generation.

This repository contains the Django REST API plus a small Django HTML
admin UI used in development. A separate Next.js frontend is planned for
production-facing buyer/seller experiences.

---

## Tech stack

| Layer | Choice |
|---|---|
| Web framework | Django 4.2 + Django REST Framework |
| Database | PostgreSQL 16 (primary + read replica via custom router) + **Row-Level Security** for tenant isolation |
| Cache / broker | Redis 7 (`django-redis` + Celery) |
| Background work | Celery 5.4 |
| Search | Elasticsearch / OpenSearch with PostgreSQL `ILIKE` fallback |
| Auth (API) | Self-issued JWT (djangorestframework-simplejwt, signed with `DJANGO_SECRET_KEY`) — DRF `JWTAuthentication` |
| Auth (HTML UI) | Session-based email/password login |
| Payments | Stripe Connect — Express accounts, PaymentIntents, transfers, refunds |
| Commissions | Category-based seller commission (Amazon/Flipkart "referral fee" model); per-category rate schedule, snapshotted ledger, 0% default |
| Invoices | reportlab PDF → AWS S3 with 24h pre-signed URLs |
| Infra | AWS ECS + RDS + ElastiCache + OpenSearch + S3 |
| CI/CD | GitHub Actions (flake8 + bandit + pytest + 80% coverage gate) |
| Container | `python:3.11-slim`, gunicorn × 4, non-root |
| Load testing | Locust |

---

## Quick start (Docker — recommended)

You only need Docker Desktop with WSL 2 integration enabled.

```bash
# 1. Clone
git clone https://github.com/mdadilbitpastel-art/nepa-unite.git
cd nepa-unite

# 2. Copy the env template and set DJANGO_SECRET_KEY
cp .env.example .env
# then edit .env — at minimum set DJANGO_SECRET_KEY to anything random.
# Auth0/Stripe/AWS values can stay blank for the dev UI to work.
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

# 3. Build + start everything (web + worker + postgres-16 + redis)
docker compose up --build

# 4. Open in your browser
#    http://localhost:8000/login/      (dev HTML UI)
#    http://localhost:8000/api/docs/   (Swagger)
#    http://localhost:8000/api/health/ (JSON health probe)
```

The `web` container automatically runs `python manage.py migrate` on
startup, so once it logs `Listening at: http://0.0.0.0:8000` the
application is ready.

### Seed an admin user for the dev HTML UI

```bash
docker compose exec -T web python manage.py shell <<'PY'
import uuid
from users.models import CustomUser, Tenant, WorkflowTemplate
tenant, _ = Tenant.objects.get_or_create(
    name="Platform Admin",
    defaults={"vertical_type": WorkflowTemplate.Vertical.OTHER,
              "status": Tenant.Status.ACTIVE},
)
admin = CustomUser.objects.filter(email="admin@nepaunite.local").first() or CustomUser(
    email="admin@nepaunite.local",
    auth0_sub=f"local|admin-{uuid.uuid4().hex}",
    role=CustomUser.Role.ADMIN, tenant=tenant, status=CustomUser.Status.ACTIVE,
)
admin.set_password("admin12345")
admin.save()
print("admin user ready: admin@nepaunite.local / admin12345")
PY
```

Sign in at `http://localhost:8000/login/` — the admin dashboard surfaces
pending members with Approve / Suspend buttons.

---

## Quick start (local Python — no Docker)

```bash
docker compose up -d postgres redis    # only the dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: DJANGO_SECRET_KEY required; the DB/Redis URLs already
# default to the docker-exposed ports.

python manage.py migrate
python manage.py runserver 0.0.0.0:8000

# separate terminal — start the Celery worker:
celery -A nepa_unite worker --loglevel=info
```

---

## Project layout

```
nepa_unite/         project package (settings/, urls.py, celery.py, routers.py)
users/              CustomUser, Tenant, WorkflowTemplate; JWT auth (SimpleJWT);
                    HTML session auth (forms + views_html.py + templates)
products/           Product + ProductImage; search (ES + PG fallback);
                    bulk-upload Celery job; inventory service (Redis lock)
orders/             Order + OrderItem; state machine; services
payments/           Payment + Invoice; Stripe Connect service;
                    invoice PDF generator
commissions/        CommissionRate (per-category schedule) + Commission ledger;
                    accrue/earn/reverse lifecycle; admin rate management + bulk set
contracts/          Contract model (GPO pricing tiers)
notifications/      Notification model + service; SES-capable email task
webhooks/           Inbound Stripe handler + outgoing WebhookEndpoint /
                    WebhookDelivery with retry schedule
core/               AuditLog (append-only); /api/health/; Job tracker;
                    RLS migration; security headers middleware
templates/          base.html + auth/ + dashboard/ for the dev HTML UI
tests/              cross-cutting E2E flows
```

---

## Running tests

```bash
docker compose exec web pytest               # full suite + 80% coverage gate
docker compose exec web pytest -q products/  # one app
docker compose exec web flake8 .             # lint
docker compose exec web bandit -r . -lll -ii --exclude tests,migrations,staticfiles,.venv
```

CI on `main` runs the same commands on every push and pull request.

---

## API surface

All API routes live under `/api/v1/` and return JSON. Swagger UI at
`/api/docs/` enumerates every endpoint with request / response schemas.

Highlights:

| Endpoint | Notes |
|---|---|
| `POST /api/v1/auth/{register,login,refresh,logout}` | Self-issued JWT (SimpleJWT). The HTML pages use session auth instead. |
| `GET/PATCH /api/v1/members/{id}` | Self-or-admin scoped. |
| `POST /api/v1/admin/members/{id}/{approve,suspend}` | Admin-only; writes AuditLog. |
| `GET /api/v1/products/search/` | Public; Elasticsearch with Postgres fallback. |
| `POST /api/v1/products/`, `PUT /api/v1/products/{id}/` | Seller-only. |
| `POST /api/v1/products/bulk-upload/` | CSV → Job → poll `GET /api/v1/jobs/{id}/`. |
| `POST /api/v1/orders/` | Buyer-only; reserves inventory through Redis lock. |
| `PATCH /api/v1/orders/{id}/status/` | State-machine guarded; releases inventory on cancel. |
| `POST /api/v1/payments/intent` | Buyer-side Stripe PaymentIntent. |
| `POST /api/v1/payments/disburse` | Admin triggers Stripe Transfer to seller. |
| `POST /api/v1/sellers/onboard` | Stripe Express onboarding link. |
| `GET /api/v1/commissions/` | Admin; category-based commission ledger (+ `/summary/`). |
| `GET/POST /api/v1/commissions/rates/` | Admin; per-category commission rate schedule. |
| `POST /api/v1/webhooks/stripe` | Signature-verified Stripe receiver. |
| `GET /api/v1/orders/{id}/invoice` | Pre-signed S3 URL (auto-refreshed on expiry). |

---

## Operations

- **`DEPLOYMENT.md`** — first-time AWS bootstrap, required env vars,
  how to run migrations via a one-shot ECS task, rollback, RDS
  point-in-time restore.
- **`RUNBOOK.md`** — on-call playbook for: DB down, Redis down, Stripe
  webhooks failing, Elasticsearch down (graceful fallback), payment
  stuck in `pending`.

---

## Security notes

- All secrets come from environment variables; `.env` is `gitignore`d.
  `.env.example` lists every required key.
- Postgres Row-Level Security is enabled on every tenant-scoped table
  via `core/migrations/0002_enable_rls.py`. Application code sets
  `app.current_tenant` on each connection.
- `core.middleware.SecurityHeadersMiddleware` injects `nosniff`,
  `DENY` (X-Frame), HSTS, and a strict CSP on every response.
- `django-ratelimit` caps `/auth/register` + `/auth/login` to 10/min/IP.
  All other authenticated endpoints get 100/min/user via DRF's
  `UserRateThrottle`.
- Product text fields are sanitized with `bleach` before persistence.

---

## License

Proprietary — internal NEPA Unite project. Not licensed for redistribution.
