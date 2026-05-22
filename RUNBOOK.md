# NEPA Unite — Incident Runbook

On-call playbook for the five most common production incidents. Each
section gives detection signals, the immediate mitigation, and the
follow-up actions.

If an incident is not in this book, page the platform lead and write a
section for it afterward.

---

## A. Database is down

**Signals**
- `/api/health/` returns `503` with `"db": {"ok": false}`.
- CloudWatch alarm: `RDSDatabaseConnections == 0` for 2 min.
- Spike in HTTP 5xx from ECS `web`.

**Mitigation**
1. Confirm in the RDS console that the primary is unhealthy. If it's
   mid-failover, wait 2-3 minutes; Multi-AZ usually recovers itself.
2. If the primary is permanently down, force a failover:
   ```bash
   aws rds reboot-db-instance \
     --db-instance-identifier nepa-unite-prod \
     --force-failover
   ```
3. If the failover target is also down (rare), restore from the latest
   snapshot per `DEPLOYMENT.md` §6 and update `DATABASE_URL`.
4. While Postgres is down, the app returns 503s — do **not** disable the
   health check; ECS will deregister broken tasks for you.

**Follow-up**
- Post-mortem within 48h.
- Verify replica lag returned to <1s after recovery
  (CloudWatch `ReplicaLag`).

---

## B. Redis is down

**Signals**
- `/api/health/` returns `503` with `"redis": {"ok": false}`.
- Celery worker logs flood with `ConnectionError`.
- Login + register endpoints start returning 5xx (rate limiter is unhappy).

**Mitigation**
1. ElastiCache: check the primary node status. For single-shard, replace
   the node:
   ```bash
   aws elasticache reboot-cache-cluster \
     --cache-cluster-id nepa-unite-prod \
     --cache-node-ids-to-reboot 0001
   ```
2. While Redis is unavailable:
   - Cache misses degrade gracefully — search still works via PG fallback.
   - Celery cannot enqueue tasks: **emails and webhooks will be dropped**.
     Once Redis is back, manually replay critical events (see §E).
3. Rate-limit failures from Redis are non-fatal — `django-ratelimit` is
   configured to fail open on backend errors.

**Follow-up**
- Confirm Celery worker resumed consuming. If the worker queue backed up,
  scale up the `worker` ECS service temporarily.

---

## C. Stripe webhooks failing

**Signals**
- Stripe dashboard → Developers → Webhooks: increase in failed deliveries.
- Orders stuck in `draft` after payment success.
- CloudWatch metric filter: log line `Invalid Stripe webhook signature`.

**Mitigation**
1. Verify the signing secret matches Stripe's current value:
   ```bash
   aws ssm get-parameter --name /nepa-unite/prod/STRIPE_WEBHOOK_SECRET \
     --with-decryption
   ```
   If it's stale, rotate it in Stripe (Developers → Webhooks → Reveal),
   then update SSM and redeploy.
2. If webhooks are failing because the endpoint is 500ing, check ECS
   `web` logs for the failing event type and use Stripe's "Replay" to
   re-send after the fix.
3. For events already lost: backfill from Stripe via the API:
   ```bash
   stripe events list --type=payment_intent.succeeded --created.gte=$EPOCH
   ```
   Then for each event, call the relevant handler manually via
   `python manage.py shell`.

**Follow-up**
- Add a Stripe metric alarm if not already present.
- Confirm the Order / Payment statuses match Stripe's state.

---

## D. Elasticsearch / OpenSearch is down

**Signals**
- `/api/v1/products/search` returns `used_fallback: true` for >5 min.
- CloudWatch alarm: `ClusterStatus.red > 0`.

**Mitigation**
1. **The site stays up** — the search service automatically falls back to
   Postgres `ILIKE`. This is by design. No emergency action required.
2. Communicate via status page: search results are less relevant (no
   fuzzy / faceted filters) until ES recovers.
3. AWS OpenSearch: try a blue/green domain config update if the cluster
   is stuck red. If data is corrupt, restore from the latest manual
   snapshot.
4. Once OpenSearch is healthy, rebuild the index from Postgres:
   ```bash
   python manage.py rebuild_search_index
   ```
   (Run via the migrate-style one-shot ECS task, not from a laptop.)

**Follow-up**
- Verify a sample of search results matches what PG returned during the
  fallback window — large drifts mean reindex is needed.

---

## E. Payment is stuck in `pending`

**Signals**
- Customer reports order paid but app still shows `draft`.
- Stripe dashboard shows the PaymentIntent as `succeeded`.

**Mitigation**
1. Pull the order:
   ```bash
   python manage.py shell -c \
     "from orders.models import Order; o = Order.objects.get(pk='...'); print(o.status, o.stripe_payment_intent_id)"
   ```
2. Confirm Stripe's view:
   ```bash
   stripe payment_intents retrieve <pi_id>
   ```
3. If Stripe says `succeeded` but our DB says `pending`, replay the webhook:
   ```bash
   stripe events resend <event_id>
   ```
   This re-fires `payment_intent.succeeded`; the handler is idempotent.
4. If the replay still doesn't update, run the handler manually:
   ```bash
   python manage.py shell -c \
     "from webhooks.handlers import handle_payment_succeeded; \
      handle_payment_succeeded({'type':'payment_intent.succeeded','data':{'object':{'id':'<pi_id>'}}})"
   ```
5. Write an `AuditLog` entry noting the manual intervention.

**Follow-up**
- If multiple orders are stuck, follow §C — it's almost always a webhook
  failure upstream.
- If Stripe shows `requires_action`, the buyer needs to complete 3DS;
  email them via the support flow rather than mutating state server-side.
