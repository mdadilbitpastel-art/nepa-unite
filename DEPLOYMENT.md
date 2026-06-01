# NEPA Unite — Deployment Guide

This document is the source of truth for moving NEPA Unite from a clean AWS
account to a live staging or production environment, and for routine
deploy / rollback / restore operations. All deploys go through GitHub
Actions; the manual steps below are only for the first-time bootstrap or
break-glass situations.

---

## 0. Quick deploy to Render (free tier)

The repo ships a `render.yaml` Blueprint that provisions a free Postgres
database and a Python web service in one shot. Same codebase as local —
production behaviour is selected purely by `DJANGO_SETTINGS_MODULE`
(`nepa_unite.settings.production` on Render, `...development` locally).

1. Push this repo to GitHub (already done if you're reading this on `main`).
2. In Render: **New +** → **Blueprint**, pick this repo. Render reads
   `render.yaml` and shows the DB + web service it will create.
3. Fill the secrets it prompts for (marked `sync: false`): `EMAIL_HOST_USER`,
   `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, and Stripe keys if used.
   `DJANGO_SECRET_KEY` is auto-generated; `DATABASE_URL` is auto-wired.
4. Click **Apply**. Render runs `./build.sh` (install → `collectstatic` →
   `migrate`) then starts `gunicorn nepa_unite.wsgi:application`.
5. First deploy done — create an admin user from the Render **Shell** tab:
   `python manage.py createsuperuser`.

Notes:
- **Redis is optional.** With no `REDIS_URL` the app uses an in-memory cache
  and runs Celery tasks eagerly — fine for a single web service. To enable
  background workers, add a Render Key Value instance and set `REDIS_URL`
  (uncomment the block in `render.yaml`), plus a separate worker service.
- **Media uploads are ephemeral** on Render's free disk (lost on redeploy).
  For persistent product images, enable Cloudinary (see the commented block
  in `settings/base.py` + `requirements.txt`) or attach a Render Disk.
- The `*.onrender.com` hostname is added to `ALLOWED_HOSTS` /
  `CSRF_TRUSTED_ORIGINS` automatically via `RENDER_EXTERNAL_HOSTNAME`.

---

## 1. First-time production setup

### 1.1 AWS infrastructure (one-time)

Provision the following in the target AWS account (Terraform recommended;
we keep modules in a separate `nepa-unite-infra` repo):

| Resource | Notes |
|---|---|
| VPC + private/public subnets in two AZs | required for ECS + RDS multi-AZ |
| RDS Postgres 16 (Multi-AZ) | primary; enable automated backups (7 day retention min) |
| RDS read replica | for the `replica` Django DB alias |
| ElastiCache Redis 7 | one cluster, single shard for now; cache + Celery broker |
| OpenSearch domain | one data node for staging; three for prod |
| S3 bucket `nepa-unite-invoices-prod` | versioning enabled, public access blocked |
| ECR repository `nepa-unite` | image tags pinned to `git sha` |
| ECS cluster `nepa-unite-prod` | Fargate |
| ECS services: `web`, `worker` | `web` runs gunicorn, `worker` runs celery |
| ALB | terminates TLS; forwards `:443` to `web` target group |
| ACM cert | for `api.nepaunite.com` |
| IAM OIDC + GitHub deploy role | trusted by `repo:nepa-unite/main` ref |
| CloudWatch log groups | one per ECS service |
| SSM Parameter Store | every secret listed in §3 |

### 1.2 GitHub repository configuration

Settings → Secrets and variables → Actions:

| Secret | Description |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | IAM role the GitHub OIDC provider may assume |
| `AWS_REGION` | e.g. `us-east-1` |
| `STAGING_ECR_REPOSITORY` | image repo name (without registry) |
| `STAGING_ECS_CLUSTER` | cluster name |
| `STAGING_ECS_SERVICE` | service name |
| `STAGING_ECS_TASK_DEFINITION` | path to `task-definition.json` in repo |

For production, mirror the same set with `PRODUCTION_*` names and add a
separate workflow (`deploy-production.yml`) gated on a manual approval.

### 1.3 Initial database setup

Once RDS is up but before the first ECS deploy:

```bash
# Connect via a bastion / SSM session.
psql "$DATABASE_URL" \
  -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
```

Migrations and the RLS policy install happen via the standard
`python manage.py migrate` in §2.

---

## 2. Running database migrations in production

Migrations are **not** part of the running ECS task; that would race when
multiple instances start. Instead, run a one-shot ECS task with the latest
image:

```bash
# From a workstation with AWS access.
aws ecs run-task \
  --cluster nepa-unite-prod \
  --task-definition nepa-unite-migrate \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-...],securityGroups=[sg-...],assignPublicIp=DISABLED}" \
  --overrides '{"containerOverrides":[{"name":"nepa-unite","command":["python","manage.py","migrate","--no-input"]}]}'
```

The migrate task uses the same image as `web` but a different task
definition that overrides the container command.

**Never** `python manage.py migrate` from a developer laptop against
production — it requires direct PG access and bypasses the audit trail.

After migrations, run the same task with
`python manage.py rebuild_search_index` if the Elasticsearch mapping
changed.

---

## 3. Required environment variables

Every value lives in SSM Parameter Store under `/nepa-unite/prod/...` and
is injected into the ECS task at runtime.

| Variable | Description |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `nepa_unite.settings.production` |
| `DJANGO_SECRET_KEY` | 64+ random chars |
| `DJANGO_ALLOWED_HOSTS` | comma list, includes the ALB hostname |
| `DATABASE_URL` | `postgres://user:pass@primary.host:5432/nepa_unite` |
| `DATABASE_REPLICA_URL` | `postgres://user:pass@replica.host:5432/nepa_unite` |
| `REDIS_URL` | ElastiCache primary endpoint |
| `CELERY_BROKER_URL` | usually `${REDIS_URL}` on a different DB number |
| `CELERY_RESULT_BACKEND` | same as broker |
| `OPENSEARCH_URL` | full https URL incl. domain |
| `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `AUTH0_ISSUER`, `AUTH0_ALGORITHMS` | matching the prod Auth0 tenant |
| `AUTH0_MGMT_CLIENT_ID`, `AUTH0_MGMT_CLIENT_SECRET`, `AUTH0_MGMT_AUDIENCE` | M2M app with `read:users`, `create:users` |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_CONNECT_CLIENT_ID` | live keys |
| `AWS_S3_INVOICES_BUCKET` | `nepa-unite-invoices-prod` |
| `EMAIL_BACKEND` | `django_ses.SESBackend` in prod |
| `DEFAULT_FROM_EMAIL` | verified SES sender |
| `STRIPE_PLATFORM_FEE_PERCENT` | platform's cut, e.g. `5.0` |
| `STRIPE_ONBOARDING_RETURN_URL`, `STRIPE_ONBOARDING_REFRESH_URL` | front-end deep links |
| `AUTH_RATE_LIMIT`, `API_RATE_LIMIT` | tighten in prod, e.g. `10/m` / `100/m` |

The container does **not** read a `.env` file in production —
`django-environ` falls back to `os.environ`, which ECS populates.

---

## 4. Deploying

Routine path:

1. Merge to `main` on GitHub.
2. `deploy-staging.yml` builds the Docker image, pushes to ECR with
   `IMAGE_TAG=$GITHUB_SHA`, renders a new task definition, and calls
   `aws ecs update-service` with `--wait-for-service-stability`.
3. Smoke-test against `https://staging.nepaunite.com`.
4. Promote to production by manually triggering `deploy-production.yml`
   with the same SHA. (Production workflow not in this repo yet — see
   §1.2.)

Bypassing the workflow is not allowed. If GitHub Actions is down, file an
INFRA ticket and wait — do not `docker push` from a laptop.

---

## 5. Rolling back a deployment

ECS keeps the previous task definition revision. To roll back to the
revision prior to a bad deploy:

```bash
# List recent revisions:
aws ecs list-task-definitions --family-prefix nepa-unite-web --sort DESC --max-results 10

# Roll back the service to a specific revision:
aws ecs update-service \
  --cluster nepa-unite-prod \
  --service nepa-unite-web \
  --task-definition nepa-unite-web:PREVIOUS_REVISION_NUMBER \
  --force-new-deployment
```

A rollback does **not** undo a database migration. If the new revision
applied a destructive migration, restore from a backup (§6) instead.

---

## 6. Restoring from RDS backup

RDS automated snapshots are taken every six hours and retained for seven
days. Manual snapshots are taken before every migration that drops or
renames a column.

```bash
# 1. Identify the snapshot to restore:
aws rds describe-db-snapshots \
  --db-instance-identifier nepa-unite-prod \
  --snapshot-type automated

# 2. Restore into a new instance (DO NOT overwrite the live one):
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier nepa-unite-prod-restore \
  --db-snapshot-identifier rds:nepa-unite-prod-YYYY-MM-DD-HH-MM \
  --db-instance-class db.r6g.large \
  --multi-az

# 3. Once the restored instance is `available`, update Parameter Store
#    DATABASE_URL to point at the new endpoint and redeploy the ECS service.
# 4. After validation, delete the old instance.
```

For PITR (point-in-time recovery within the retention window), use
`restore-db-instance-to-point-in-time` instead and pass
`--restore-time` in UTC.
