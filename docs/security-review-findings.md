# Security Review — Findings & Tracking

Date: 2026-05-24. Method: four parallel audits (auth/authz, web/injection,
payments/webhooks, data/PII/infra) against the code and `.claude/rules/security.md`.

Status legend: ✅ Fixed · ⬜ Open (triage)

---

## Fixed

| ID | Sev | Finding | Location | Fix |
|----|-----|---------|----------|-----|
| C1 | 🔴 Critical | SMS delivery webhook was unauthenticated — anyone could forge delivery/failure events to suppress real safety-alert retries | `app/api/v1/endpoints/delivery_webhooks.py` | ✅ Shared-secret HMAC (`AWS_SNS_DELIVERY_WEBHOOK_SECRET`) required via the `X-MIH-Signature` header, constant-time compare, fail-closed (returns 403 for all requests until the secret is set). Test: `tests/test_sns_delivery_webhook.py`. **Deploy note:** set `AWS_SNS_DELIVERY_WEBHOOK_SECRET` and have the SNS→Lambda bridge sign requests to `…/webhooks/delivery/sns`. |
| H1 | 🟠 High | Refresh tokens (7-day) accepted as access tokens — `decode_access_token` didn't check `type` | `app/core/security.py`, `app/api/v1/deps/auth.py` | ✅ `create_access_token` stamps `type=access`; access-path deps reject non-access tokens; `/refresh` unchanged. Test: `tests/test_security_jwt_type.py`. |
| H2 | 🟠 High | Stored cross-user XSS via unescaped `alert.message` in an HTMX polling fragment | `app/web/routes_htmx.py` (deleted) | ✅ The route was **dead code** (unmounted router, 0% coverage; live alert rendering in `routes_htmx_profile.py` already uses the autoescaped template). Deleted the orphaned file entirely. |

---

## Open — to triage

### Medium
- ⬜ **Auth rate limiting is dead config.** `RATE_LIMIT_AUTH="10/minute"` (`config.py`) is defined but applied nowhere; OTP endpoints rely only on the global 60/min-per-IP → SMS-pump/toll-fraud on `/request-otp` + `/resend-otp`. (Per-code 3-attempt cap does mitigate guessing.) Fix: decorate OTP/refresh handlers, ideally keyed on phone for sends. Also add a per-phone daily send cap; consider shortening OTP validity (currently 15 min).
- ⬜ **Stripe webhook idempotency is non-atomic.** Subscription committed inside `create_subscription`; `ProcessedStripeEvent` row committed separately afterward (`webhooks.py:56-89`). A crash/replay between them double-creates subscriptions (no unique constraint on `stripe_checkout_session_id`). Fix: insert processed-event row in the same transaction; commit once.
- ⬜ **Twilio signature breaks behind TLS proxy.** uvicorn runs without `--proxy-headers`, so `request.url` is `http://internal:8000`, mismatching the signed `https://` URL → legit callbacks 403 (`delivery_webhooks.py:43`, `Dockerfile`). Fix: `--proxy-headers --forwarded-allow-ips`, or build the URL from a configured public base.
- ⬜ **Referral cap race.** `referral.py:47-71` read-then-write with no row lock / unique constraint → concurrent redemptions can exceed `max_referral_redemptions` and stack credit. Fix: `SELECT … FOR UPDATE` + unique index on `referee_user_id`.
- ⬜ **No security headers.** Missing `X-Frame-Options`/CSP/`X-Content-Type-Options` (`app/main.py`) — clickjacking; a CSP would also be defense-in-depth for template XSS. Fix: small response-headers middleware (note: templates use inline scripts, so a strict CSP needs refactoring first).

### Low
- ⬜ Full phone numbers (PII) logged at ERROR in prod SMS paths — `sms.py:68,127,132`. Mask them.
- ⬜ `/docs`, `/redoc`, `/openapi.json` exposed in prod — `main.py:46-51`. Disable outside development.
- ⬜ Authenticated HTMX mutations rely on `SameSite=Lax` only (no CSRF token like the admin panel). Document or extend the double-submit token.
- ⬜ Web auth cookie `max_age` 7 days ≫ 30-min access-token lifetime — `web/utils.py`. Align, or issue a deliberate longer-lived web token + cookie refresh.
- ⬜ Alembic/sync DB uses `sslmode=require` (encrypt, no cert verify) and `DB_SSL_REQUIRE` defaults False — `db/session.py`, `config.py:71`. Use `verify-full` + ensure on in prod.
- ⬜ `upload_file`/`delete_file` return unsigned `…s3.amazonaws.com/...` URLs that only work if the bucket is public — `storage_s3.py`. Confirm the photos bucket is private and only presigned URLs are handed out.
- ⬜ Gift checkout trusts unverified `recipient_phone` from the public form (`routes_web.py:258`). Self-limiting (attacker pays); optionally re-derive `gifter_phone` from the verified session.

### Infra / hardening
- ⬜ Confirm secrets are injected via Secrets Manager `secrets` references on the ECS task def (task execution role), not plaintext env vars — `infra/aws/primary/secrets.tf`, `ecs_web.tf`.
- ⬜ The Cloudflare failover IAM user's credentials should stay least-privilege (only `rds:PromoteReadReplica` + `ecs:UpdateService` on specific ARNs) — see the policy in `infra/cloudflare/worker.js`.
- ⬜ Secrets Manager secrets should use a recovery window (not force-delete) so an accidental delete is recoverable.
- ⬜ `SECRET_KEY` dev-default is accepted if `ENVIRONMENT` is unset (defaults to `development`) — `config.py:100-107`. Consider failing closed.

---

## Verified correct (no action)
JWT algorithm pinned (HS256) on decode; OTP uses `secrets.choice` + `compare_digest` with a 3-attempt cap and dev-only logging; IDOR/ownership checks via `get_owned_or_404`; no mass-assignment on `PUT /users/me`; admin routes uniformly gated by `get_current_admin` + CSRF double-submit; Stripe + Twilio webhook signatures validated; no raw-SQL injection (the only `text()` calls are parameterized); no SSRF (external URLs are server-constructed); Bugsnag receives only `user.id`; CORS is an explicit allow-list (not `*`); Jinja2 autoescaping intact and live JS interpolation uses `json.dumps`; S3 bucket blocks public access, TLS + HTTPS-only; Secrets Manager access via IAM.
