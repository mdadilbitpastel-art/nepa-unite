# NEPA Unite — System Functionality & Deployment Guide

**Regional B2B Marketplace Platform** &nbsp;|&nbsp; Prepared for Management Review
Document v1.0 · June 2026 · **Status: Live on Render**

---

## 1. Executive Summary

NEPA Unite is a **multi-tenant B2B marketplace** built for local businesses in
Northeastern Pennsylvania (dental, architectural, dry-cleaning, law offices, and
other verticals). The platform handles the complete commerce loop: member
onboarding and approval, product catalog management, cart and order processing,
order fulfilment tracking, Stripe-Connect payments, and PDF invoice generation.

The system is a **Django REST API** with an integrated **HTML dashboard** for
administrators, sellers, and buyers. It is currently deployed and live on **Render**.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Web framework | Django 4.2 + Django REST Framework |
| Database | PostgreSQL 16 (multi-tenant; dedicated schema per app) |
| Cache / broker | Redis 7 (optional) — in-memory fallback in single-service mode |
| Background jobs | Celery 5.4 (eager mode when no Redis) |
| Search | Elasticsearch / OpenSearch with PostgreSQL ILIKE fallback |
| Authentication | Session email/password login (HTML UI); Auth0 JWT for API |
| Payments | Stripe Connect (Express accounts, PaymentIntents, transfers, refunds) |
| Invoices | reportlab PDF generation |
| Static files | WhiteNoise (compressed, served by the app) |
| Web server | Gunicorn (4 workers) |
| Hosting | Render (Python web service) |
| CI/CD | GitHub Actions (flake8 + bandit + pytest + coverage gate) |

---

## 3. User Roles & Features

The platform supports four roles. Each role sees a tailored dashboard after login.

### 3.1 Administrator — full oversight of the marketplace
- **Member management** — all sellers and buyers in searchable, filterable, paginated tables.
- **Approval workflow** — approve pending sellers (sellers start as *Pending*) and reactivate accounts.
- **Suspend / reactivate** — suspend any member; suspended users cannot log in.
- **Seller & buyer detail pages** — profile, products, and order history.
- **Product oversight** — view and manage every seller's products.
- **Order oversight** — view all orders and drive status transitions.
- **Audit log** — chronological record of administrative and order actions.
- **System health** — live status page (database + cache connectivity).
- **API reference** — built-in documentation of all REST endpoints.

### 3.2 Seller — manage own catalog and fulfil orders
- **Product catalog (CRUD)** — create, edit, soft-delete products (name, SKU, price, description, inventory, image, minimum order quantity).
- **Inventory management** — track stock; low-stock indicator below threshold.
- **Activate / deactivate listings** — toggle product visibility.
- **Order fulfilment** — view incoming orders and advance them through the lifecycle.
- **Stripe Connect onboarding** — connect a Stripe account to receive payouts.
- **Storefront** — public seller storefront.

### 3.3 Buyer — browse and purchase (auto-activated on registration)
- **Browse & search products** across the marketplace.
- **Shopping cart** — add, update, and remove items.
- **Checkout & orders** — place orders and track status.
- **Wishlist** — save products for later.
- **Product reviews** — write reviews and ratings.
- **Address book** — save and manage multiple shipping addresses.
- **Order history** — view past and active orders with live status.

### 3.4 Auditor — read-only oversight for compliance
- View dashboards, members, orders, and the audit log without making changes.

---

## 4. Core Feature Modules

| Module | Capability |
|---|---|
| **Accounts & Auth** | Registration, login/logout, forgot & reset password (email link), pending-approval routing. |
| **Products** | Catalog CRUD, search, categories, wishlist, reviews, seller storefront. |
| **Cart** | Per-buyer cart with add / update / remove and quantity validation. |
| **Orders** | Order creation, line items, status transitions, per-item fulfilment, activity log. |
| **Payments** | Stripe Connect onboarding, payment intents, fund disbursement to sellers, refunds. |
| **Invoices** | PDF invoice generation (reportlab). |
| **Notifications** | Transactional email (password reset, onboarding, etc.). |
| **Audit log** | Records administrative and order-lifecycle events. |

### Order Lifecycle

> **Draft → Confirmed → Fulfilment → Shipped → Delivered → Closed**
> (an order may also be **Cancelled**)
> Per-item fulfilment status: Pending / Fulfilled / Cancelled

---

## 5. Site Access & Login Credentials

| Item | Value |
|---|---|
| **Live URL** | https://nepa-unite.onrender.com |
| **Login page** | https://nepa-unite.onrender.com/login/ |
| **Admin dashboard** | https://nepa-unite.onrender.com/dashboard/ |
| **Health check** | https://nepa-unite.onrender.com/api/health/ |
| **API docs (Swagger)** | https://nepa-unite.onrender.com/api/docs/ |

**Administrator login** (configured via deployment environment variables):

| Field | Value |
|---|---|
| Email | admin@nepaunite.com |
| Password | Admin@12345 |
| Role | Administrator |

> ⚠️ **Security note:** This is the initial bootstrap credential. Please change the
> password after first login. Sellers and buyers self-register from the sign-up page.

---

## 6. Deployment Details

| Item | Detail |
|---|---|
| **Hosting platform** | Render (cloud PaaS) |
| **Service type** | Python web service (Gunicorn), free tier |
| **Service name** | nepa-unite |
| **Deploy method** | Render Blueprint (`render.yaml`) — auto-deploys on push to `main` |
| **Build steps** | install deps → collect static → run migrations → bootstrap admin |
| **Settings module** | `nepa_unite.settings.production` (local uses `.development`) |
| **Static files** | served by WhiteNoise (compressed) |
| **HTTPS** | enforced by Render at the edge; hostname auto-trusted |

> Note: The free tier sleeps after inactivity; the first request after idle may take
> ~30 seconds to wake. Uploaded media is ephemeral on the free tier (persistent
> storage recommended for production media).

---

## 7. Database Details

| Item | Detail |
|---|---|
| **Engine** | PostgreSQL (hosted on Render) |
| **Dedicated schema** | `nepa_unite` — all tables live in their own schema |
| **Isolation** | Database instance shared with another service; NEPA Unite tables fully isolated in their own schema (no collisions). |
| **Connection** | via the `DATABASE_URL` environment variable |
| **Migrations** | applied automatically on each deploy |

> Database credentials are managed securely in the Render dashboard and are never
> stored in source code.

---

## 8. Source Code & Version Control

| Item | Detail |
|---|---|
| **Repository** | https://github.com/mdadilbitpastel-art/nepa-unite |
| **Main branch** | `main` (production deploys from here) |
| **CI/CD** | GitHub Actions — linting, security scan, tests, coverage |
| **Deploy trigger** | Pushing to `main` automatically redeploys on Render |

---

## 9. Environment & Configuration

The same codebase runs locally and in production; behaviour is selected by the
`DJANGO_SETTINGS_MODULE` variable. Key values are supplied as environment variables
(secrets are never committed):

- `DJANGO_SECRET_KEY` — auto-generated on Render
- `DATABASE_URL` — Postgres connection string
- `DB_SCHEMA` — `nepa_unite` (schema isolation)
- `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` — initial admin bootstrap
- `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` — transactional email (Gmail SMTP)
- `STRIPE_*` — payment keys (optional, off by default)

---

## 10. Local Development

Developers can run the full stack with Docker, or with a local Python environment
and PostgreSQL. Development settings enable a permissive single-machine
configuration (in-memory cache, eager tasks, relaxed CORS) — no external Redis or
worker required.

---

## 11. Roadmap & Notes

- A dedicated **Next.js frontend** is planned for the production buyer/seller
  experience (the current HTML dashboard serves operations and administration).
- **Persistent media storage** (Cloudinary or Render Disk) recommended before
  storing production product images.
- **Redis + Celery worker** can be enabled for true background processing at scale.
- **Stripe Connect** is integrated and can be switched on once live payment
  accounts are configured.

---

*NEPA Unite — Confidential. Prepared for internal management review.*
