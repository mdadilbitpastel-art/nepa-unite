# NEPA Unite — Frontend API Reference

Complete REST API sheet for frontend developers. Every endpoint, with request &
response payloads, auth requirement, and allowed roles.

> **Live, always-in-sync docs (source of truth):**
> - Swagger UI (interactive): **`GET /api/docs/`**
> - OpenAPI spec (generate a typed TS client from this): **`GET /api/schema/`**
>
> This sheet is a human-friendly summary. If anything ever disagrees with the
> Swagger UI, trust Swagger — it is generated from the code.
>
> A spreadsheet version is also available: **`FRONTEND_API.xlsx`** / **`FRONTEND_API.csv`**.

---

## 0. Conventions (read first)

| Topic | Detail |
|---|---|
| **Base URL** | `https://<host>/api/v1` (JSON API). Health/docs live under `/api` (no `v1`). |
| **Auth** | `Authorization: Bearer <access_token>` (self-issued JWT). Get the token from `/auth/login`; refresh via `/auth/refresh`. |
| **Account state** | Only **active** accounts may use the API. Suspended/pending accounts get `401` on every request. |
| **Content-Type** | `application/json` for all bodies (except file uploads → `multipart/form-data`). |
| **Trailing slash** | Router endpoints (members, products, cart, orders, wishlist, reviews, addresses, jobs) **END WITH `/`**. Hand-written endpoints (`/auth/*`, `/payments/*`, `/sellers/onboard`, `/orders/{id}/invoice`) have **NO** trailing slash. Mind this exactly. |
| **List responses** | Plain JSON **array** (no pagination wrapper) — except `products/search` which paginates itself. |
| **Rate limit** | 100 requests/min per user (`429` on exceed). |
| **IDs** | All resource IDs are **UUID** strings. |
| **Money** | Decimal strings, e.g. `"50.00"`. |

### Common error shape
```json
{ "detail": "Human readable message" }
```
Validation errors are field-keyed:
```json
{ "email": ["A user with this email already exists."] }
```
Status codes: `400` validation · `401` missing/expired token or inactive account · `403` wrong role/not owner · `404` not found · `429` throttled.

### Enums (reference)
- **Role:** `buyer` · `seller` · `admin` · `auditor` (admin cannot self-register)
- **User/Tenant status:** `pending` · `active` · `suspended`
- **Order status:** `draft` · `confirmed` · `fulfillment` · `shipped` · `delivered` · `closed` · `cancelled`
- **Payment status:** `pending` · `completed` · `failed` · `refunded` · `disputed`
- **OrderItem fulfillment:** `pending` · `fulfilled` · `cancelled`
- **Vertical type:** `automotive, architectural, construction, dental, dry_cleaning, education, electronics, food_beverage, healthcare, hospitality, law_office, logistics, manufacturing, real_estate, retail, technology, textiles, wholesale, other`

---

## 1. Auth  `/api/v1/auth/*`  (no trailing slash, public)

### POST `/auth/register`
```json
// request
{
  "email": "buyer@example.com",
  "password": "min8chars",
  "role": "buyer",                 // buyer | seller  (NOT admin)
  "business_name": "Acme Corp",
  "vertical_type": "retail"
}
// response 201
{ "id": "uuid", "email": "buyer@example.com", "role": "buyer", "status": "pending" }
```
> Buyers become `active` immediately; sellers stay `pending` until an admin approves.

### POST `/auth/login`
```json
// request
{ "email": "buyer@example.com", "password": "min8chars" }
// response 200
{ "access_token": "jwt...", "refresh_token": "jwt...", "expires_in": 86400 }
```

### POST `/auth/refresh`
```json
{ "refresh_token": "jwt..." }            // → { "access_token": "jwt...", "expires_in": 86400 }
```

### POST `/auth/logout`  *(auth required)*
```json
{ "refresh_token": "jwt..." }            // → 204 / 200
```

### POST `/auth/forgot-password`
```json
{ "email": "buyer@example.com" }         // → 200 (always, to avoid email enumeration)
```

### POST `/auth/reset-password`
```json
{ "uid": "base64uid", "token": "reset-token", "new_password": "min8chars" }
```

---

## 2. Members / Profile  `/api/v1/members/`  (auth)

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/members/` | any | list members |
| GET | `/members/{id}/` | any | member detail |
| PATCH | `/members/{id}/` | self/admin | update own email |

```json
// GET /members/{id}/  →
{
  "id": "uuid", "email": "a@b.com", "role": "seller", "status": "active",
  "tenant": { "id": "uuid", "name": "Acme", "vertical_type": "retail", "status": "active" },
  "created_at": "2026-01-01T10:00:00Z", "updated_at": "2026-01-02T10:00:00Z"
}
// PATCH /members/{id}/   { "email": "new@b.com" }
```

### Admin member management  `/api/v1/admin/members/`  (admin only)
| Method | Path | Purpose |
|---|---|---|
| GET | `/admin/members/` | list all members |
| GET | `/admin/members/{id}/` | detail |
| POST | `/admin/members/{id}/approve/` | approve a pending seller/buyer |
| POST | `/admin/members/{id}/suspend/` | suspend a member |

---

## 3. Addresses  `/api/v1/addresses/`  (buyer, auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/addresses/` | list my addresses |
| POST | `/addresses/` | create |
| GET/PATCH/DELETE | `/addresses/{id}/` | manage one |
| POST | `/addresses/{id}/set-default/` | mark default |

```json
// POST /addresses/  request (response adds id/created_at/updated_at)
{
  "label": "Home", "recipient_name": "Adil", "phone": "+9779800000000",
  "line1": "Street 1", "line2": "", "city": "Kathmandu",
  "state": "Bagmati", "zip_code": "44600", "country": "NP",
  "is_default": true
}
```

---

## 4. Products  `/api/v1/products/`

| Method | Path | Auth | Role | Purpose |
|---|---|---|---|---|
| GET | `/products/` | auth | any | list |
| POST | `/products/` | auth | seller | create |
| GET | `/products/{id}/` | auth | any | detail (incl. images) |
| PATCH/DELETE | `/products/{id}/` | auth | seller (owner) | update/delete |
| GET | `/products/search/` | **public** | — | full-text + filters (paginated) |
| GET | `/products/categories/` | **public** | — | category list |
| GET | `/products/by-seller/{seller_id}/` | auth | any | a seller's products |
| POST | `/products/bulk-upload/` | auth | seller | CSV upload (multipart) |
| GET/POST | `/products/{id}/reviews/` | auth | any/buyer | list / add review |

```json
// POST /products/  request
{
  "sku": "SKU-1", "name": "Widget", "description": "desc",
  "price": "19.99", "attributes": { "color": "red" },
  "inventory_count": 100, "min_order_qty": 1
}
// product object (response)
{
  "id": "uuid", "tenant": "uuid", "seller": "uuid",
  "sku": "SKU-1", "name": "Widget", "description": "desc",
  "price": "19.99", "attributes": {"color":"red"},
  "inventory_count": 100, "min_order_qty": 1, "status": "active",
  "primary_image_url": "https://.../img.jpg",
  "created_at": "...", "updated_at": "..."
}
```

### GET `/products/search/` — query params
`?q=&category=&region=&price_min=&price_max=&contract_status=&in_stock=&page=1&page_size=20`
```json
// response (this one IS paginated)
{ "count": 42, "page": 1, "page_size": 20, "results": [ /* product objects */ ] }
```

### POST `/products/bulk-upload/`  (multipart/form-data)
Field `file` = `.csv` (≤10 MB). Returns a **job** (track via `/jobs/`).

### Reviews `/api/v1/reviews/`  ·  Wishlist `/api/v1/wishlist/`  ·  Jobs `/api/v1/jobs/`
```json
// POST /reviews/  (or POST /products/{id}/reviews/)
{ "product": "uuid", "rating": 5, "title": "Great", "body": "Loved it" }   // rating 1–5

// POST /wishlist/
{ "product": "uuid" }

// GET /jobs/{id}/  → bulk-upload job status (queued/running/done/failed)
```

---

## 5. Cart  `/api/v1/cart/`  (buyer, auth)

| Method | Path | Purpose |
|---|---|---|
| GET | `/cart/` | get my cart (items + total) |
| POST | `/cart/items/` | add item |
| PATCH | `/cart/items/{item_id}/` | change quantity |
| DELETE | `/cart/items/{item_id}/` | remove item |
| POST | `/cart/clear/` | empty cart |
| POST | `/cart/checkout/` | **convert cart → Order (status `draft`)** |

```json
// GET /cart/  →
{
  "id": "uuid",
  "items": [{
    "id":"uuid","product":"uuid","product_name":"Widget","product_sku":"SKU-1",
    "product_image_url":"https://...","quantity":2,"unit_price":"19.99",
    "line_total":"39.98","updated_at":"..."
  }],
  "total": "39.98", "item_count": 2, "updated_at": "..."
}

// POST /cart/items/   { "product_id": "uuid", "quantity": 2 }
// PATCH /cart/items/{item_id}/   { "quantity": 3 }

// POST /cart/checkout/  — use a saved address OR inline shipping
{ "address_id": "uuid" }
// ...or:
{
  "shipping_name":"Adil","shipping_phone":"+977...",
  "shipping_address_line1":"Street 1","shipping_address_line2":"",
  "shipping_city":"Kathmandu","shipping_state":"Bagmati","shipping_zip":"44600",
  "buyer_notes":"leave at door"
}
// → returns the created Order object (status "draft")
```

---

## 6. Orders  `/api/v1/orders/`  (auth)

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/orders/` | any | my orders (buyer: own · seller: containing my items · admin: all) |
| GET | `/orders/{id}/` | any (scoped) | order detail |
| POST | `/orders/` | buyer | create order directly (without cart) |
| PATCH | `/orders/{id}/status/` | scoped | move order status |

```json
// POST /orders/  request
{
  "items": [ { "product_id": "uuid", "quantity": 2 } ],
  "shipping_name":"Adil","shipping_phone":"+977...",
  "shipping_address_line1":"Street 1","shipping_address_line2":"",
  "shipping_city":"Kathmandu","shipping_state":"Bagmati","shipping_zip":"44600",
  "buyer_notes":""
}
// Order object (response)
{
  "id":"uuid","buyer":"uuid","tenant":"uuid","status":"draft","total_amount":"39.98",
  "shipping_name":"Adil","shipping_phone":"+977...",
  "shipping_address_line1":"Street 1","shipping_address_line2":"",
  "shipping_city":"Kathmandu","shipping_state":"Bagmati","shipping_zip":"44600",
  "buyer_notes":"","stripe_payment_intent_id":"",
  "items":[{"id":"uuid","product":"uuid","seller":"uuid","quantity":2,"unit_price":"19.99","fulfillment_status":"pending"}],
  "created_at":"...","updated_at":"..."
}

// PATCH /orders/{id}/status/   { "status": "cancelled" }
```
**Allowed transitions:** `draft→confirmed→fulfillment→shipped→delivered→closed`; any non-terminal state → `cancelled`. (Payment moves `draft→confirmed` automatically — see §7.)

---

## 7. Payments — Stripe  `/api/v1/payments/*`  (no trailing slash)

| Method | Path | Auth | Role | Purpose |
|---|---|---|---|---|
| GET | `/payments/config` | **public** | — | publishable key + currency for Stripe.js init |
| POST | `/payments/intent` | auth | buyer (owner) | create a PaymentIntent for an order |
| GET | `/payments/{order_id}` | auth | scoped | list payments + statuses for an order |
| POST | `/payments/disburse` | auth | admin | payout an order item's share to its seller |
| POST | `/sellers/onboard` | auth | seller | start Stripe Connect onboarding |

```json
// GET /payments/config   (call once on app load)
{ "publishable_key": "pk_test_...", "currency": "usd", "platform_fee_percent": 5.0, "configured": true }

// POST /payments/intent   { "order_id": "uuid" }
// response 201
{ "client_secret": "pi_..._secret_...", "payment_intent_id": "pi_..." }

// GET /payments/{order_id}  →  [ payment objects ]
{
  "id":"uuid","order":"uuid","stripe_payment_intent_id":"pi_...",
  "amount":"39.98","platform_fee":"2.00","status":"completed",
  "disbursed_at":null,"created_at":"..."
}

// POST /sellers/onboard   {}  →  { "onboarding_url": "https://connect.stripe.com/..." }

// POST /payments/disburse  (admin)   { "order_item_id": "uuid" }  →  202
```

### 🔑 Frontend Stripe checkout flow (step by step)
1. **App load:** `GET /payments/config` → `publishable_key`. Init `Stripe(publishable_key)`.
   *(Alternatively put the publishable key in your own env, e.g. `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`.)*
2. **Start checkout:** `POST /payments/intent {order_id}` → `client_secret`.
3. **Collect card:** mount Stripe **Payment Element** with the `client_secret`, then call
   `stripe.confirmPayment({ elements, confirmParams: { return_url } })`.
4. **After payment:** Stripe fires the `payment_intent.succeeded` **webhook** → backend marks
   the `Payment` `completed` and the order `draft → confirmed`.
5. **Reflect status:** poll `GET /payments/{order_id}` (or re-fetch the order) until
   `status: "completed"` / order `confirmed`.

> **Test card:** `4242 4242 4242 4242`, any future expiry, any CVC/ZIP.
> **Production note:** Step 4 needs `STRIPE_WEBHOOK_SECRET` configured on the backend and a
> Stripe webhook pointed at `POST /api/v1/webhooks/stripe`. Without it the order won't flip to
> `confirmed` on its own.

---

## 8. Invoices  `/api/v1/orders/{order_id}/invoice`  (auth, scoped; no trailing slash)
```json
// GET  →  fresh pre-signed PDF URL (auto-regenerated if expired)
{
  "id":"uuid","order":"uuid","invoice_number":"INV-XXXX",
  "s3_key":"invoices/2026/.../order.pdf",
  "pre_signed_url":"https://s3...","pre_signed_url_expires_at":"...","created_at":"..."
}
```

---

## 9. Webhooks (server-to-server — NOT called by the frontend)
- `POST /api/v1/webhooks/stripe` — Stripe → backend. Verified via `Stripe-Signature`. Listed here only so you know the order auto-confirms through it.

---

## 10. Utility
| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health/` | public | `{ "status":"ok", "db":{...}, "redis":{...} }` (LB liveness) |
| GET | `/api/docs/` | public | Swagger UI |
| GET | `/api/schema/` | public | OpenAPI spec (YAML) |

---

### Quick role cheat-sheet
- **Buyer:** browse/search products, wishlist, reviews, cart, checkout, **pay**, view own orders & invoices, manage addresses.
- **Seller:** manage own products (incl. bulk upload), Stripe Connect onboarding, view orders containing their items, advance fulfillment.
- **Admin:** approve/suspend members, view everything, disburse payouts.
- **Auditor:** read-only oversight.
