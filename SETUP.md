# Made It Home — Setup & Operations Guide

Authoritative non-code reference for Made It Home. Code conventions live in `CLAUDE.md` and `.claude/rules/`.

## Overview

Made It Home is a personal safety app: users set a check-in deadline, and the app alerts their trusted contacts if they don't check in on time. Phone-based OTP auth, Stripe subscriptions, Expo push notifications.

**Environments:** production (`app.madeithomeapp.com`), staging (auto-deploy on `master`), local dev.

## Required third-party accounts

| Provider | Purpose | Tier | Signup |
|----------|---------|------|--------|
| **AWS** | ECS Fargate (web + worker), RDS PostgreSQL (Multi-AZ in prod), SNS (SMS failover), S3 (photos), Secrets Manager (secrets), ECR (images), CloudWatch (logs) | Pay-as-you-go | aws.amazon.com |
| **Cloudflare** | DNS for both domains, Workers for failover health checks, KV namespace `FAILOVER_KV` | Free/Pro | cloudflare.com |
| **Twilio** | Primary SMS/OTP delivery, verified number in E164 | Pay-as-you-go | twilio.com |
| **Stripe** | All subscriptions and sponsorship checkout. 4 recurring products. Customer Portal for management | Standard | stripe.com |
| **Bugsnag** | Error tracking — backend project + mobile project | Free tier | bugsnag.com |
| **Expo / EAS** | Build service, push notifications. Project ID: `f6db40df-7218-47d2-a517-548cdb47f28e` | Free | expo.dev |
| **Apple Developer** | Team ID, App ID `com.madeithome.app`, APNs certificate | $99/yr | developer.apple.com |
| **Google Play Console** | Developer account, signing key, package `com.madeithome.app` | $25 one-time | play.google.com/console |

### Stripe products

Create 4 recurring products in the Stripe dashboard:

| Product | Price | Price ID env var |
|---------|-------|------------------|
| Individual Monthly | $5/mo | `STRIPE_PRICE_ID_MONTHLY` |
| Individual Annual | $48/yr ($4/mo) | `STRIPE_PRICE_ID_ANNUAL` |
| Group Monthly | $10/mo | `STRIPE_PRICE_ID_GROUP_MONTHLY` |
| Group Annual | $96/yr ($8/mo) | `STRIPE_PRICE_ID_GROUP_ANNUAL` |

Stripe dashboard settings:
- Payment methods: enable Apple Pay and Google Pay
- Billing → Customer portal: enable cancel, enable plan switching with proration, default return URL = `https://madeitho.me/subscription` (the app passes this per session anyway — `stripe_service.create_portal_session`)
- Customer emails: enable pre-renewal reminders
- Webhook endpoint: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`

## Domains

| Domain | Purpose | Notes |
|--------|---------|-------|
| `app.madeithomeapp.com` | Primary domain, API, web | Cloudflare DNS, TTL 60s for failover |
| `madeitho.me` | Short links (prod) | Cloudflare DNS |
| `s.madeitho.me` | Short links (staging) | Cloudflare DNS |

Universal/app links are claimed on the short-link host(s). The AASA file
at `madeitho.me/.well-known/apple-app-site-association` (and
`s.madeitho.me`) claims paths `/r/*`, `/g/*`, `/sub`, `/plans`,
`/subscription` — referral, group-plan join, the paywall (the frozen
lapse-SMS link redirects here too), and the app's own Stripe
checkout-return URLs (built on `SHORT_DOMAIN` for exactly this reason — the
app doesn't claim `app.madeithomeapp.com`). A Stripe return MAY hand back
to the app (the OS often won't for a script-driven redirect); the app's
confirming step and its foreground re-check are the reliable unlock path.
Without the app, `/plans` and `/subscription` redirect by User-Agent to the
App Store / Play Store, else the marketing site. Circle-of-trust invites (`/c/*`) are browser-only
(Circle members use mobile web only, no in-app accept screen). Sponsorship
checkout (`/s/*`, `/sponsorships`) is deliberately left unclaimed so Stripe
checkout stays in the browser and doesn't trip Apple/Google in-app-purchase
rules. Paths are generated from `_UNIVERSAL_LINK_PATHS` in
`backend/app/api/v1/endpoints/well_known.py`.

## Environment variables

The authoritative list of every env var (which side it belongs to, secret vs
static) is **`infra/secrets/manifest.json`**. Don't hand-set env vars on the
ECS tasks — fill `infra/secrets/<env>.secrets.env` and run
`infra/aws/scripts/populate-secrets.sh <env>`, which seeds Secrets Manager and
wires both tasks via secret references. See `infra/secrets/README.md`. The
tables below are a human-readable summary.

### Backend (ECS task)

| Variable | Source | Purpose |
|----------|--------|---------|
| `DATABASE_URL` | Secrets Manager | `postgresql+asyncpg://...` (RDS Postgres) |
| `SECRET_KEY` | Secrets Manager | JWT signing key |
| `ENVIRONMENT` | Static | `production` / `staging` / `development` |
| `DB_SSL_REQUIRE` | Static | `true` for cloud Postgres |
| `TWILIO_ACCOUNT_SID` | Secrets Manager | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Secrets Manager | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Secrets Manager | E164 format |
| `SMS_FAILOVER_PROVIDER` | Static | `sns` (AWS SNS — only supported value) |
| `AWS_SNS_REGION` | Static | Region for the SNS SMS failover |
| `AWS_SNS_SENDER_ID` | Static | Optional SNS sender ID (empty = default routing) |
| `AWS_SNS_DELIVERY_WEBHOOK_SECRET` | Secrets Manager | HMAC secret authenticating the SNS delivery webhook (`X-MIH-Signature`) |
| `STRIPE_SECRET_KEY` | Secrets Manager | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | Secrets Manager | Stripe webhook signing secret |
| `STRIPE_PRICE_ID_MONTHLY` | Secrets Manager | Stripe price ID |
| `STRIPE_PRICE_ID_ANNUAL` | Secrets Manager | Stripe price ID |
| `STRIPE_PRICE_ID_GROUP_MONTHLY` | Secrets Manager | Stripe price ID |
| `STRIPE_PRICE_ID_GROUP_ANNUAL` | Secrets Manager | Stripe price ID |
| `STORAGE_BACKEND` | Static | `s3` (AWS S3 — only supported value) |
| `AWS_S3_BUCKET` | Static | S3 bucket for photos |
| `AWS_S3_REGION` | Static | Region of the photo bucket |
| `BUGSNAG_API_KEY` | Secrets Manager | Backend error tracking |
| `GRACE_PERIOD_MINUTES` | Static | Minutes after deadline before overdue (default: 2) |
| `GROUP_PLAN_MAX_MEMBERS` | Static | Default 5 |
| `GROUP_PLAN_GRACE_DAYS` | Static | Default 7 |

### Mobile (`app.config.js` extra)

Config lives in `mobile/app.config.js` (formerly `app.json`). Secret-bearing
`extra` values are read from `process.env` so nothing secret is committed:
`populate-secrets.sh` writes `mobile/.env` for local dev and pushes EAS project
secrets for builds.

| Key | Source (process.env var) | Purpose |
|-----|--------------------------|---------|
| `extra.bugsnag.apiKey` | `MOBILE_BUGSNAG_API_KEY` | Mobile error tracking (separate Bugsnag project from backend); required for staging/production bundles — app.config.js throws without it |
| EAS project ID | static in `app.config.js` | `f6db40df-7218-47d2-a517-548cdb47f28e` |

### Cloudflare Worker

| Variable | Purpose |
|----------|---------|
| `TARGET_CLOUD` | `aws` (health-check + alerting only — the automated failover path is currently superseded; see `docs/deployment.md`) |
| `AWS_ACCESS_KEY_ID` | Dedicated failover IAM user (scoped to the failover actions) |
| `AWS_SECRET_ACCESS_KEY` | Dedicated failover IAM user |

## Webhook URLs

| Provider | URL | Events |
|----------|-----|--------|
| Stripe | `https://app.madeithomeapp.com/webhooks/payments/stripe` | checkout, subscription updated/deleted, invoice paid/failed |
| AWS SNS | `https://app.madeithomeapp.com/webhooks/delivery/sns` | SMS delivery reports (via SNS delivery-status logging → Lambda bridge) |
| Twilio (optional) | `https://app.madeithomeapp.com/webhooks/delivery/twilio` | SMS delivery status |

## GitHub Actions secrets

| Secret | Purpose |
|--------|---------|
| `AWS_ROLE_TO_ASSUME` | IAM role ARN assumed via OIDC for CD (see `infra/aws/scripts/setup-github-oidc.sh`) |

## Legal documents

| Path | URL |
|------|-----|
| `backend/app/web/templates/privacy.html` | `https://app.madeithomeapp.com/privacy` |
| `backend/app/web/templates/terms.html` | `https://app.madeithomeapp.com/terms` |

Compliance: GDPR, CCPA/CPRA, COPPA (13+ age gate). Contact: `hello@madeithomeapp.com`. Payment processor: Stripe (sole).

## Mobile app store metadata

| Field | Value |
|-------|-------|
| iOS Bundle ID | `com.madeithome.app` |
| Android Package | `com.madeithome.app` |
| Expo Project ID | `f6db40df-7218-47d2-a517-548cdb47f28e` |
| Apple Team ID | Set in `app.config.js` → `ios.appleTeamId` |
| ASC App ID | Set in EAS config |

## Deploy from scratch

1. Provision an AWS account and the GitHub Actions OIDC role (`infra/aws/scripts/setup-github-oidc.sh`).
2. Deploy infrastructure: `infra/aws/scripts/bootstrap.sh <env>` (Terraform in `infra/aws/primary/` — VPC + ECS Fargate + ALB + RDS + ECR + Secrets Manager), then `infra/aws/scripts/init-db.sh <env>`.
3. Provision Cloudflare account, add both domains, deploy Worker and KV namespace.
4. Create accounts: Stripe (4 products), Twilio (verified number), Bugsnag (2 projects), Expo/EAS, Apple Developer, Google Play Console.
5. Populate secrets: fill `infra/secrets/<env>.secrets.env` and run `infra/aws/scripts/populate-secrets.sh <env>` (seeds Secrets Manager, wires both ECS tasks, pushes EAS secrets).
6. Configure the GitHub Actions secret `AWS_ROLE_TO_ASSUME`.
7. Configure webhook endpoints in the Stripe dashboard and SNS delivery-status logging (`infra/aws/scripts/setup-sns-delivery-logging.sh`).
8. Configure DNS: root record pointing to the ALB, deploy AASA file.
9. Push to `master` to trigger first CD run (staging auto-deploy).
10. Build and submit mobile apps via `eas build` + `eas submit`.

## Local development

### Prerequisites

- Python 3.12+, Node.js 18+, PostgreSQL 15+
- iOS: macOS with Xcode 15+
- Android: Android Studio with SDK

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create database
createdb made_it_home

# Run migrations
alembic upgrade head

# Start dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In development, OTP codes print to console instead of sending SMS.

API docs: http://localhost:8000/docs

### Worker

The worker runs as a cron job (every 60s) via `worker_tick.py`. In dev, run it manually:

```bash
cd backend
source venv/bin/activate
python worker_tick.py
```

### Mobile

```bash
cd mobile
npm install
npx expo start
```

Update `mobile/constants/index.ts` with your machine's local IP for API connectivity.

### Running tests

```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -v --asyncio-mode=auto
ruff check .
mypy app/ --config-file pyproject.toml
```

`make verify` (repo root) runs the full gate set CI uses: audit, lint, type
check, tests + coverage, the test-count ratchet, the except-block reporting
check and the mobile swallowed-error lint. `make help` lists each gate.

### Git hooks (one-time)

`make hooks-installed` (run automatically by `make verify`) installs
`scripts/git-hooks/pre-commit`, which runs `make verify` before every commit.
`.pre-commit-config.yaml` is not used by the gate — don't run `pre-commit
install`, it would replace the hook.

Every commit then runs the full `make verify` gate set (audit, lint, type
check, tests + coverage, the test-count ratchet). Bypass a known-broken WIP
with `git commit --no-verify`, never to get an unreported `except` in.

## Production deployment

Backend runs on **AWS ECS Fargate** (web + worker services). Database is **RDS PostgreSQL** (Multi-AZ in production). Infrastructure managed via **Terraform** in `infra/aws/primary/`.

- **Staging**: automatic on every `master` push after CI passes.
- **Production**: manual via GitHub Actions → CD → Run workflow → `production`.

### Mobile deployment

One app/bundle ID; the target backend is chosen at build time by
`EXPO_PUBLIC_APP_ENV` (per EAS profile in `eas.json`): `staging` →
`staging-app.madeithomeapp.com`, `production` → `app.madeithomeapp.com`. A
`staging` build is for **internal** TestFlight only (never the App Store) and
shows a persistent "STAGING APP" banner in-app (`components/EnvBanner.tsx`).

Build/submit commands: see `RUNNING.md` → Mobile App → *Native / EAS builds*.

## Monitoring

- **Bugsnag**: error tracking (backend + mobile)
- **Cloudflare Worker**: health check monitoring with automated failover
- **AWS CloudWatch**: container logs and metrics

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Database connection failed | Check PostgreSQL is running, verify `DATABASE_URL` |
| Import errors in backend | Activate virtualenv: `source venv/bin/activate` |
| Expo Go crashes | Clear cache: `npx expo start -c` |
| Module not found (mobile) | `rm -rf node_modules && npm install` |
| API connection from mobile | Verify IP in `constants/index.ts`, ensure `--host 0.0.0.0` |
| Push notifications not working | Only work on physical devices, not simulators |
