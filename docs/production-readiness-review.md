# Production-Readiness Review

A full-stack review (2026-06-26) of the safety pipeline, payments, data layer,
security, infra, and mobile. Findings were verified against the code; the
ship-blocking and high-value items were fixed (see "Fixed" below). The rest is
tracked here with file:line and a recommended approach.

## Verdict
Foundations are strong (auth/crypto, access-lapse safety, advisory-lock worker,
secrets, normalization). The critical gaps were in the **alert-dispatch path**
(an emergency contact could get nothing with no failure signal) — those are
fixed. Remaining items are listed by area; a few need a real environment
(mobile/infra) or careful payment-transaction work.

## Fixed this session (verified, CI-green)
- **C1** app-account contacts got no alert (async lazy-load `MissingGreenlet`) — `get_user_contacts` now eager-loads `contact_user`. (`crud/circle_of_trust.py`)
- **C2** SOS delayed ~2-3 min — `_create_sos_session` dispatches inline. (`api/v1/endpoints/sessions.py`)
- **C5** partial dispatch failure stuck MISSED forever — promote to ALERTED on any reach so `retry_failed_alerts` retries the failures. (`services/session_tasks.py`)
- **Worker rollback** — `_safe` rolls back the shared session on error. (`worker_tick.py`)
- **PII** — `phone_tag()` redaction in SMS error logs; dropped query string from Bugsnag metadata; removed a raw-phone debug log. Guard test added. (`services/sms.py`, `sms_sns.py`, `middleware/error_handler.py`, `web/routes_htmx_auth.py`)
- **OTP** — `resend-otp` got the per-IP rate limit + opt-out gate it was missing. (`api/v1/endpoints/auth.py`)
- **Data indexes** — partial `ix_sessions_active_overdue`, user-FK indexes, `ix_alerts_sms_message_id`; dropped redundant index; synced all (incl. pre-existing `ix_fpm_one_active_per_user`) into models. (migration `db6c675fb517`)
- **Referral H1** — `referrals.referral_code` made non-unique (was breaking every 2nd redemption); added one-per-referee partial unique. (migration `50cd0cd753f2`)
- **Webhook fail-closed + readiness** — Twilio delivery webhook 503s on unusable token in prod; `/health/ready` returns a generic error. (`api/v1/endpoints/delivery_webhooks.py`, `main.py`)
- **Docs** — corrected stale Sponsor-model rules + Expo SDK version.

## Fixed since the initial review (also shipped, CI-green)
- **C3** phone-only alert tracking — `Alert` now allows a `sent_to_phone_id` recipient (migration `8ce884503ae7`); SMS-only contacts' failures are tracked + retried. Regression test.
- **H2** Stripe webhook idempotency — marker is flushed before the handler and commits atomically with the effect; duplicates abort on the PK; ignored events don't burn a marker. Regression tests. (`webhooks.py`)
- **Mobile C4/H3/H5** — `sendSOS` retries + the home screen rolls back the false "Alerted"; offline check-in queue flushed on load; Expo push-token rotation listener; token log removed.
- **Infra C6 + deploy hardening** — CloudWatch alarms (worker heartbeat / ALB 5xx + unhealthy / RDS) + SNS topic (`infra/aws/primary/alarms.tf`, `terraform validate` clean); ECS `deployment_circuit_breaker`; CD `concurrency:` group.

## Fixed in the MEDIUM/LOW pass (also shipped, CI-green)
- Security: OTP HTMX-path rate-limit + opt-out; **revocable refresh tokens** via `users.token_version` (bumped on soft-delete); web token TTL matched to the cookie.
- Mobile: `completeSession` only optimistically marks safe on a network error; failed refresh clears tokens (force re-auth); `validateStripeUrl` test; removed dead `scheduleMissedCheckInAlert`; **SOS now retries in the background** (sosQueue) instead of asking the user to re-press.
- Data: **enum CHECK constraints** on the string-enum columns (migration `d4a42709f995`, declared in models); the overdue-scan + FK indexes from the first pass.
- Payments: **subscription reconciliation** for a lost `checkout.session.completed`; group-member cap race (`FOR UPDATE`) + rejoin-after-leave; sponsorship pending-pair partial-unique + idempotent endpoint; **out-of-order** checkout guard (live Stripe status).
- Infra: worker Dockerfile runs non-root + cron removed.

## Genuinely remaining (deliberate / low-risk)
- **Account-deletion FK semantics — NOT a bug.** The design is documented anonymize-in-place ("No row deletion", `docs/account-deletion-plan.md`), so the NO-ACTION FKs are correct; nothing to change unless a hard-purge is ever added.
- **Broader `alembic check` drift** — some pre-existing indexes/NOT-NULLs on `otps`/`users`/`session_updates`/`circle_of_trust_members` live only in migrations, not the models. Harmless today; a future `--autogenerate` could try to drop them. Hygiene only — declare them in the model `__table_args__` (run `alembic check` to enumerate). New indexes/constraints added in this review are already declared.
- **Base-image digest pinning** — deliberately left as a team decision: pinning a digest trades reproducibility for losing automatic security patches, and checksumming the AWS RDS CA bundle breaks builds when AWS rotates it. Current state (pinned minor tag + official truststore fetch) is defensible.
- **Refresh-token *rotation* + reuse-detection** — beyond the revocation now in place, full per-token rotation with a stored `jti` family is a larger feature for its own PR.
- **Alarm thresholds** need a `terraform plan` review + a one-time SNS email-subscription confirmation before they page.

## Pre-deploy checklist (one-time setup before the next production deploy)
- [x] **Stripe day pass** — DONE 2026-07-02: $0.99 one-off price created in
      test + live modes; all five `STRIPE_PRICE_ID_*` values in both
      `.secrets.env` files verified against the Stripe API (amount, type,
      active). Values reach AWS via `populate-secrets.sh` at revival
      (see the revival-order item below).
- [x] **Migrations** — DONE 2026-07-03: production deployed via CD run
      28644266136; `alembic upgrade head` applied the full chain against the
      fresh RDS instance.
- [ ] **Twilio toll-free verification** for +18774146630: submit with the login
      consent-form screenshot (see `docs/twilio-a2p-consent.md`); alert SMS and
      the welcome/consent texts won't deliver reliably until verified.
- [ ] **Push notification credentials** (blocks all remote pushes; SMS
      channels work without it): (1) Android — create a Firebase project,
      add app `com.madeithome.app`, put `google-services.json` in
      `mobile/`, wire `android.googleServicesFile` in app.config.js, and
      upload the FCM V1 service-account key via `eas credentials`;
      (2) iOS — Apple Developer membership, then `eas credentials` sets up
      the APNs key. Remote push CANNOT be tested in Expo Go (SDK 53+) —
      needs a dev build (`eas build --profile development`).
- [ ] **Apple Critical Alerts entitlement** (non-blocking, recommended): apply via
      Apple's request form so circle alerts can bypass mute/DND (Life360 precedent
      — see docs/flow-review.md §2.5).
- [x] **Secrets at revival** — DONE 2026-07-03 for production: stale names
      force-deleted, `bootstrap.sh production` applied (105 resources, plan
      reviewed), `populate-secrets.sh production` pushed all 15 values, OIDC
      role + GH environment re-wired, DNS flipped to the new ALB, first
      deploy green, /health + /health/ready both 200, live Stripe webhook
      endpoint verified. STAGING remains torn down (cd.yml auto-deploy
      trigger disabled) — same order applies when reviving it:
      force-delete stale secrets → `bootstrap.sh staging` →
      `populate-secrets.sh staging`.
- [x] **Cloud consolidation follow-through** — DONE 2026-07-02: owner confirmed
      no non-AWS provider keys or legacy storage/SMS values remain in the
      `.secrets.env` files (stale values would fail loudly at boot). The
      deployment is AWS-only.

## How to verify
All gates run via `make verify` (backend + mobile) / `make ci` (adds docker build);
migrations verified by `alembic upgrade head` on a throwaway DB, and `alembic check`
for model/migration drift.
