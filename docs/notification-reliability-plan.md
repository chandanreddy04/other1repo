# Notification Reliability — Implementation Plan (pre-prod, lean)

> Revised 2026-07-12 for **pre-prod** status: the production *environment* is
> deployed, but **no real users depend on the app yet**. That removes the "stop
> the bleeding this week" pressure and the live-traffic rollout ceremony, so we
> **build the outbox directly** instead of shipping throwaway bridge code first.
> File/line references verified against the working tree.
>
> **What this drops vs. the full staged plan** (and why it's safe pre-prod):
> - the Phase-0 "shippable-without-migration" bridges — the MISSED-retry patch,
>   in-process exhaustion tracking, the owner-reminder stopgap (the outbox
>   replaces all of them, so writing them first is pure throwaway);
> - the in-flight-session **backfill** (no live data to migrate);
> - the migrate-then-roll **zero-downtime** ceremony (downtime is free);
> - the **7-day dual-write** convergence before dropping `Alert` columns (do it
>   in one pass);
> - the **two-apply** warm-worker cutover with the schedule as a live fallback
>   (a single clean apply is fine with no traffic).
>
> **Kept from Phase 0** — the fixes that are real bugs regardless of launch and
> useful for beta testing today: the `delivered=True` truth fix (needed by the
> outbox anyway), the mobile push-token regression, and the mobile
> sosQueue/reminder fixes.

---

## 0. Mobile-contract decision — RESOLVED: go clean

TestFlight builds exist but **only with founders, who can be force-updated**
(confirmed 2026-07-12). And critically, the clean model is **transparent to the
mobile app anyway**: the columns we drop (`sms_message_id`, `sms_provider`,
`push_notification_id`, `retry_count`, `failed_at`) are backend delivery
internals — the mobile `Alert` type (`mobile/types/index.ts`) consumes **none**
of them (only `id, session_id, sent_to_user_id, alert_type, status, message,
sent_at, delivered_at, acknowledged_at, created_at`). `status` and the timestamps
mobile *does* read are preserved (now written by the outbox rollup).

**Decision:** build the **clean model** (B.5 default) — drop the channel columns
in the outbox migration, no dual-write, no derived-rollup baggage. Also remove
those fields from the `schemas/alert.py` response model (they're exposed at
`:43-45` but unused by mobile). Force-updating founders is an available safety
margin, but B.5 shouldn't require a coordinated mobile release. **I10 is fully
relaxed.**

---

## 1. Invariants (the finished system must hold these)

- **I1 — Terminal-state guarantee.** Every owed notification is a durable row a reconciler drives to exactly one terminal state: `delivered` / `exhausted` / `superseded` / `refused`. Nothing is attempted-once-and-forgotten.
- **I2 — Enqueue-with-the-business-change.** The row is written in the *same transaction* as the state change that owes it (SOS creation, MISSED promotion, completion, claim). A crash after commit loses nothing.
- **I3 — Receipt-driven truth.** "Delivered" = a provider receipt said so (Twilio/SNS webhook, Expo receipt). "Sent" = the provider accepted it (ticket/SID, no per-ticket error). Never "the HTTP call didn't throw."
- **I4 — Parallel channels.** Circle alerts dispatch push+SMS immediately in parallel; receipts inform retry/escalation, never delay the first send.
- **I5 — Escalate, never silently drop.** Exhausting a circle-member delivery auto-enqueues an owner "contact unreachable"; exhausted rows page Bugsnag (user.id only).
- **I6 — Session status is derived** from delivery-row state; no session can be stranded with nothing driving it forward.
- **I7 — Honest 4xx.** Genuine refusals (4xx except 401/403/408/429) are terminal both sides. 401/403 on mobile = auth, not refusal → SOS stays queued.
- **I8 — Idempotency.** Deterministic `dedupe_key` + UNIQUE + `ON CONFLICT DO NOTHING`; enqueue paths are re-runnable. The advisory lock stays the concurrency backstop, not the correctness mechanism.
- **I9 — Latency.** SOS: inline, sub-second. Missed check-in: circle reached ≤ 60s after grace (warm worker). Owner reminders: ≤ 60s after `fire_at`.
- **I10 — Contract (relaxed, see §0).** The clean `Alert` is transparent to the mobile app (it doesn't read the dropped columns); founders are force-updatable regardless. No contract preservation needed.

---

## Track A — Real bugs to fix now (building blocks + beta-relevant)

Independently commitable; each lands before or alongside the outbox.

### A.1 — `delivered=True` truth (needed by the outbox regardless)
**Files:** `app/services/expo_notifications.py`, `app/services/session_tasks.py`
- `send_notification`: extract `_map_tickets(sent_tokens, response)` → `(ok, dead, errored)`; return `ok_tokens: list[str]` + `ticket_ids: dict[str,str]` (token→Expo ticket id, used by outbox receipt polling). Error paths (`:124-129`) → `ok_tokens: []`.
- `session_tasks.py:157`: `delivered = token in push_result.get("ok_tokens", [])` (was unconditional `True`). Keep dead-token clearing.
**Tests (new `tests/test_push_ticket_truth.py`):** ok_tokens only for `status:"ok"`; HTTP 500 → empty; ticket-error+no phone → `mark_failed`; ticket-error+SMS ok → delivered; `ticket_ids` mapping.

### A.2 — Mobile push-token on grant (the regression I introduced)
**Files:** `mobile/services/notifications.ts`, `app/(auth)/onboarding.tsx:102`, `components/PermissionRequirements.tsx:71`, `mobile/store/useAuthStore.ts`
- Add `registerAndSaveToken()` = `registerForPushNotificationsAsync()` (check-only) then `saveTokenToBackend(token)`; `initialize()` uses it too.
- `onboarding.tsx:102`: bare register (token discarded) → `registerAndSaveToken()`.
- `PermissionRequirements.tsx:71`: after a `notifications` grant resolves sufficient, call `notificationService.registerAndSaveToken()` (keep `permissions.ts` pure).
- Foreground net: AppState 'active' listener in `setupNotificationListeners` → `registerAndSaveToken()` when no token stored.
**Tests (new `mobile/services/notifications.registration.test.ts`):** posts when granted; no-op when not; save-failure doesn't throw; foreground-missing-token registers, with-token doesn't.

### A.3 — Mobile sosQueue: 401/403 not terminal
**Files:** `mobile/services/sosQueue.ts:47-59`, `mobile/store/useAuthStore.ts`
- `isTerminalSOSError`: `if (status === 401 || status === 403) return false`. Keep the queue; post a one-time local nudge ("Sign in to finish sending your SOS"); track `authNudged` in the stored payload (`{queuedAt, authNudged}`, backward-compat parse). Login success → `flushSOSQueue()`.
**Tests (extend `mobile/services/sosQueue.test.ts`):** 401/403 not terminal + nudge once; post-login flush clears; 400/422 unchanged.

### A.4 — Mobile: deadline helper + future-guard + scoped cancel
**Files:** `mobile/store/useSessionStore.ts:177-184,344-352,310,331`, `mobile/services/notifications.ts:245-273`, `mobile/utils/sessionTiming.ts`
- Replace both hand-rolled deadline chains (they omit `expected_arrival_time`) with `getSessionDeadline(session)`; skip on `null`.
- Add pure `computeReminderTrigger(deadline, now?)` → `deadline-5min` or `null` if not strictly future; `scheduleCheckInReminder` skips on `null` (today schedules a past date).
- Scoped cancel: schedule id `checkin-reminder-${sessionId}`; add `cancelCheckInReminder(sessionId)`; replace the three `cancelAllScheduledNotifications()` sites.
**Tests (new `mobile/utils/sessionTiming.test.ts`):** trigger past→null/future→-5m/boundary; arrival-only session schedules; past deadline schedules nothing; scoped cancel only.

*(Dropped from the old Phase 0: 0.2 MISSED-retry bridge, 0.3 in-process exhaustion, 0.5 owner-reminder stopgap, 0.7 all-clear guard, 0.8 atomic reminder replace — all subsumed by Track B. SOS false-200 becomes moot once status is derived; A-track keeps only a Bugsnag-notify on inline-dispatch crash, folded into B.4.)*

---

## Track B — The outbox (the spine; build directly, no bridges)

### B.1 Model + migration (no backfill)
**New** `app/models/notification_delivery.py` (docstring; import in `conftest.py` + `app/models/__init__.py`).
Enums (StrEnum + PG enum, `values_callable` like `models/alert.py:102-118`):
- `NotificationKind`: circle_alert, circle_renudge, owner_reminder, owner_deadline, session_expired_owner, circle_alerted, all_clear, alert_claimed, contact_unreachable, contact_opted_out, circle_emptied, circle_emptied_mid_session, data_deleted
- `DeliveryChannel`: push, sms
- `DeliveryStatus`: pending, sent, delivered, failed, refused, exhausted, superseded

DDL (migration `alembic/versions/…_notification_deliveries.py`):
```sql
CREATE TABLE notification_deliveries (
  id UUID PRIMARY KEY,
  dedupe_key TEXT NOT NULL,
  kind notification_kind_enum NOT NULL,
  channel notification_channel_enum NOT NULL,
  recipient_user_id UUID NULL REFERENCES users(id),
  recipient_phone_id UUID NULL REFERENCES phone_numbers(id),
  session_id UUID NULL REFERENCES sessions(id),
  alert_id UUID NULL REFERENCES alerts(id),
  status notification_delivery_status_enum NOT NULL DEFAULT 'pending',
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL,
  expires_at TIMESTAMPTZ NULL,
  provider TEXT NULL,                 -- twilio | sns | expo
  provider_message_id TEXT NULL,      -- SMS SID / SNS id / Expo ticket id
  title TEXT NULL, body TEXT NOT NULL, data JSONB NULL,
  last_error TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ NULL, delivered_at TIMESTAMPTZ NULL, terminal_at TIMESTAMPTZ NULL,
  CONSTRAINT uq_nd_dedupe UNIQUE (dedupe_key),
  CONSTRAINT ck_nd_has_recipient CHECK (recipient_user_id IS NOT NULL OR recipient_phone_id IS NOT NULL),
  CONSTRAINT ck_nd_push_needs_user CHECK (channel != 'push' OR recipient_user_id IS NOT NULL)
);
CREATE INDEX ix_nd_due ON notification_deliveries (next_attempt_at) WHERE status IN ('pending','failed');
CREATE INDEX ix_nd_receipts ON notification_deliveries (sent_at) WHERE status = 'sent';
CREATE INDEX ix_nd_provider_msg ON notification_deliveries (provider_message_id);
CREATE INDEX ix_nd_session ON notification_deliveries (session_id);
CREATE INDEX ix_nd_alert ON notification_deliveries (alert_id);
```
Constraints in `__table_args__`. **Denormalization comment** on title/body/data (point-in-time snapshot; precedent `Alert.message`).
**No backfill step** (pre-prod: no in-flight sessions to migrate). Downgrade drops table + enums.

**Dedupe key** (`make_dedupe_key`, unit-tested): `{kind}:{scope_id}:{recipient}:{channel}[:{occurrence}]`; scope = session_id (session kinds) or owner user_id (cascade); recipient `u:{id}`|`p:{id}`; occurrence: owner_reminder → deadline ISO + minutes_before; circle_renudge → `r1`; else omitted.

### B.2 CRUD + policy
**New** `app/crud/notification_delivery.py`: `enqueue(rows, commit=False)` (bulk `ON CONFLICT DO NOTHING`, caller's tx); `get_due(now, limit)` (`status IN (pending,failed) AND next_attempt_at<=now AND (expires_at IS NULL OR expires_at>now)`, `FOR UPDATE SKIP LOCKED`); `mark_sent/mark_delivered/mark_failed_with_backoff/mark_terminal`; `expire_overdue(now)` (past-expiry → exhausted, incl. sent-but-no-receipt timeout); `supersede(session_id+kind | dedupe_prefix)`; `get_by_provider_message_id`; `count_reached_for_session(kind)`.
**New** `app/services/notification_policy.py`: frozen `DeliveryPolicy(channels, max_attempts, backoff_seconds, expires_after, track_expo_receipts, escalate_on_exhausted)` + `POLICIES` per kind. Ship values: circle_alert (push+sms, 6, (30,60,120,300,600,900)s, 24h, receipts✓, escalate✓); circle_renudge (push+sms, 3, (60,300,600), 2h, receipts✓); owner_reminder (push, 3, (30,60,120), expires=deadline+grace); owner_deadline (push+sms, 3, …, deadline+grace); broadcasts (push, 3, (60,300,900), 6h); all_clear/contact_unreachable (push+sms, 3, (60,300,900), 6h). (`ALERT_MAX_RETRIES`/backoff now live here, not `config.py` scattered.)
**Contract test (new `tests/test_notification_policy_contract.py`):** every kind has a policy; backoff non-empty / `max_attempts≥1`; push kinds map to a `data.type` in `mobile/constants/notificationTypes.json`; `escalate` only for circle-directed kinds.

### B.3 Reconciler + tick integration
**New** `app/services/notification_outbox.py` (db_session-testable):
- `send_due_deliveries(now, limit)`: push → resolve token (none → refused + escalation check), send, ticket ok → sent (+ticket id) [non-receipt kinds → delivered directly], ticket/HTTP error → backoff, DeviceNotRegistered → clear token + refused; sms → `gated_send_sms` (`sms_opt_out.py:379-407`), success → sent, opted_out → refused, else backoff. Commit per batch.
- `poll_expo_receipts(now)`: sent+expo+receipt-kind rows ≥30s old → new `ExpoPushNotificationService.get_receipts(ticket_ids)` (POST `.../getReceipts`); ok → delivered; DeviceNotRegistered → clear+refused; error → backoff; 24h silence → expiry.
- `expire_and_escalate(now)`: `expire_overdue`; newly exhausted/refused with `escalate_on_exhausted` → enqueue `contact_unreachable` (push+sms, dedupe once) + Bugsnag ids-only.
- `derive_session_promotions()`: MISSED sessions with `count_reached(circle_alert) ≥ 1` → ALERTED (`crud_session.mark_as_alerted`), enqueue `circle_alerted` owner row (I6).
`worker_tick.py`: add phases after overdue scan inside `_safe`: send_due → derive_promotions → poll_receipts → expire_and_escalate; add counters to summary (`:172-184`).

### B.4 Convert ALL kinds (one pass — no per-kind staging)
- **Circle alerts / SOS** (`session_tasks.py:243-325`, `sessions.py:185-227`): keep claim gate + `_build_alert_content`; create `Alert` business rows; **enqueue** push+sms rows per member/channel; single commit; inline `send_due_deliveries` for latency. **Delete** `_dispatch_to_member`, `retry_failed_alerts` (`:417-489`), `get_alerted_sessions_with_failed_alerts` (`crud/session.py:130-146`), and the old tick phases (`worker_tick.py:80-97`). SOS enqueues in the alert-creation tx → a total inline failure leaves committed pending rows the reconciler drives (fixes the panic-press loss). Keep a Bugsnag-notify on inline-dispatch crash (`sessions.py:224`).
- **Owner reminders** (`session_tasks.py:492-552`): keep `SessionReminder` as the *schedule*; `process_pending_reminders` enqueues `owner_reminder`/`owner_deadline` rows (`expires_at=deadline+grace`), marks the schedule row done, reconciler delivers. Extension calls `supersede({owner_reminder,owner_deadline})` inside a single-transaction `replace_for_session` (also fixes the non-atomic delete-then-recreate). Delete the direct-send path.
- **Broadcasts** — `all_clear` (`sessions.py:281-289`), `alert_claimed` (`alert_claim.py:83-126`), opt-out cascade (`notification_helpers.py:259-447`), `session_expired_owner`, `data_deleted`: convert each to enqueue(+inline attempt) in its business tx. The defect-5 "push-only + swallowed" class dies.
- **15-min circle re-nudge** (finally built): at promotion, enqueue `circle_renudge` per member/channel `next_attempt_at=now+ALERT_REMINDER_DELAY_MINUTES` (`config.py:167` gets its first consumer), `alert_id`=original alert (details link stays valid), new `ALERT_RENUDGE_BODY`. Superseded by claim/completion/ACKNOWLEDGED. Wire `data.type` stays `alert_triggered` (no new mobile type).
- **SMS webhooks** (`delivery_webhooks.py` Twilio `:38-86`, SNS `:118-163`): resolve the delivery row by `provider_message_id` (`mark_delivered`/`mark_failed_with_backoff`).

### B.5 The clean `Alert` model (RESOLVED: clean path — see §0)
In the same migration, **drop** `sms_message_id`, `sms_provider`, `push_notification_id`, `retry_count`, `failed_at` from `alerts` (`models/alert.py:128-142`); `Alert.status` is written *only* by the outbox rollup + claim/resolve; move `SMSProvider` to the delivery module; delete `crud_alert.mark_sms_sent/get_by_sms_message_id/get_failed_alerts_for_retry` and provider-hint plumbing. Update the SMS-webhook handlers to touch **only** delivery rows (no legacy mirror). Fix readers: **`schemas/alert.py`** — remove `push_notification_id`/`sms_message_id`/`failed_at` from the `Alert` response model (`:43-45`) and `failed_at` from `AlertUpdate` (`:30`); **`web/admin_registry.py`** — drop any column config referencing them. Mobile is unaffected (§0); `status`/timestamps it reads are preserved. Founders can force-update if a build ships alongside — not required for this change.

### B.6 Track-B tests (all new files, db_session, deterministic)
`test_outbox_model.py`, `test_outbox_enqueue_tx.py` (rides caller tx; SOS atomic), `test_outbox_reconciler.py` (due/backoff/expiry; push ok→sent; ticket-error→backoff; DNR→refused+cleared; sms opted_out→refused; exhaustion; non-receipt→delivered), `test_outbox_receipts.py` (ok→delivered; DNR→refused; error→requeue; 30s gate; 24h→exhausted), `test_outbox_escalation.py` (exhausted→contact_unreachable once; Bugsnag ids-only), `test_session_status_derivation.py` (total fail stays MISSED→retry→ALERTED; 1-of-3; total exhaustion escalates, never promotes), `test_owner_reminders_outbox.py` (enqueue on fire; extend supersedes atomically; tokenless→quiet expiry), `test_broadcast_kinds_outbox.py` (per kind enqueued in tx; push-failure retried), `test_circle_renudge.py` (enqueued +15m; claim-before-due→superseded; completion supersedes; dedupe), `test_delivery_webhooks_outbox.py`, `test_notification_policy_contract.py`. If §0=default, `test_alert_business_object.py` (rollup mapping; webhook path no longer touches alert columns; mobile schema fields). Keep `test_notification_types_contract.py` green — new `contact_unreachable` type registered (its `DISPATCH_MODULES` already scans `notification_helpers`/`session_tasks`/`alert_claim`, so **no edit to that test file**). Ratchet `.min-test-count`.

---

## Track C — Warm worker (single apply)

**Problem:** `aws_scheduler_schedule.worker` (`infra/aws/primary/ecs_worker.tf:152-200`) launches a fresh Fargate task per minute → 20-60s cold start on top of cadence.
**Change (one apply):**
1. **New** `backend/worker_loop.py`: `while not shutdown: run_tick_with_lock(); sleep(max(0, 60-elapsed))`; SIGTERM finishes the in-flight tick then exits (container `stopTimeout=120`); non-zero crash exit so ECS restarts. `worker_tick.py` stays for manual runs.
2. **Terraform:** add `aws_ecs_service "worker"` — `desired_count=1`, FARGATE, `command=["python","worker_loop.py"]`, `deployment_minimum_healthy_percent=0`/`maximum_percent=100`, same SG/subnets, no LB. **Retire** `aws_scheduler_schedule.worker` + its IAM role/policy **in the same apply** (no live traffic to protect).
3. **CD:** `deploy-aws.yml` must `update-service --force-new-deployment` for the worker service.
**Tradeoffs:** ~$13/mo continuous vs per-minute spend (≈wash); loses "fresh process per tick" — mitigated by the `_safe` wrapper, httpx timeouts, and the tick-absence alarm below.
**Observability:** CloudWatch metric filter on `"tick complete"` → alarm `<1 in 5min` (worker-dead pager); filter/alarm on `"exhausted" > 0`.
**Tests:** `tests/test_worker_loop.py` (shutdown after in-flight tick; non-negative sleep; tick exception doesn't kill loop). `make ci` (docker) required.

---

## Cross-cutting

- **Idempotency:** `make_dedupe_key` + UNIQUE + `ON CONFLICT DO NOTHING`; at-least-once (crash after send before mark re-sends — accepted, one-batch window).
- **Observability:** tick summary gains outbox counters; Bugsnag on exhausted circle rows + inline-SOS crash (ids only); repurpose the hourly stuck-MISSED check (`worker_tick.py:151-170`) into a "non-terminal delivery rows > 24h" invariant-I1 watchdog.
- **Migration ordering:** destructive migrations are fine (no live data); still `alembic upgrade head` before rolling tasks so the schema exists when new code runs. Model imported in `conftest.py`.
- **Convention compliance:** new tests in NEW files; `.min-test-count` ratcheted per batch; coverage ≥84% (the outbox is highly unit-testable — expect a rise); 3NF with one commented snapshot denorm; Bugsnag ids-only; REST untouched (webhooks reuse routes). No existing-test edits required (the one prior gate — `test_notification_types_contract.py::DISPATCH_MODULES` — already covers the dispatch modules).

---

## Sequenced checklist (pre-prod, lean)

| # | Item | Priority | Effort |
|---|---|---|---|
| 1 | A.1 push-ticket truth (`ok_tokens`, `delivered=`) | MUST | 0.5d |
| 2 | A.2 mobile token-on-grant (regression) | MUST | 0.5d |
| 3 | A.3 sosQueue 401/403 retryable | MUST | 0.5d |
| 4 | A.4 mobile deadline helper + future-guard + scoped cancel | MUST | 0.5d |
| 5 | C warm worker (single apply + alarms) | MUST | 1d |
| 6 | B.1–B.2 outbox model/migration(no backfill)/CRUD/policy | MUST | 1.25d |
| 7 | B.3 reconciler phases + Expo receipts | MUST | 1.5d |
| 8 | B.4 convert all kinds (circle+SOS, reminders, broadcasts, re-nudge, webhooks) | MUST | 1.5d |
| 9 | B.5 clean `Alert` model (drop channel columns + schema fields) | MUST | 0.5d |
| 10 | Repurpose stuck-session watchdog to delivery-row invariant | SHOULD | 0.25d |

**Total ≈ 6.5–7 days** (vs ~11 staged), landing at the same correct end state without throwaway bridges, backfill, or a two-apply cutover.

Run `make verify` per item, `make ci` for #5/#6, `/retro` at the A→B and B→done boundaries, ratchet `.min-test-count` with each test batch, push after each track.
