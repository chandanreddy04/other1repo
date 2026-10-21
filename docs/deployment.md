# Deployment

Made It Home runs on **AWS only**.

Both staging and production deploys are manual `workflow_dispatch` runs — `cd.yml`'s
`workflow_run` auto-deploy-to-staging-on-master trigger has been commented out since
2026-07-02 (staging infra was torn down; every push would otherwise produce a
guaranteed-failing deploy run).

This doc covers:
- AWS topology + decisions
- AWS deploy runbook + DR + naming
- Cloudflare health-check failover

## TL;DR / Deploy quick refs

| Action | Trigger | What happens |
|---|---|---|
| Deploy AWS staging | `cd.yml` → workflow_dispatch → `env=staging` | AWS staging deploys via `deploy-aws.yml` |
| Deploy AWS prod | `cd.yml` → workflow_dispatch → `env=production` | AWS prod deploys |

CI/CD flow files:
- `.github/workflows/cd.yml` — the dispatcher
- `.github/workflows/deploy-aws.yml` — reusable AWS deploy (build → ECR → migrate → ECS update → health check)

---

# AWS deploy

## Topology
Primary region: **`us-west-2`**. Failover region: **`us-east-2`** — holds replicated **data only** (RDS automated backups, ECR images, Terraform state, secrets), no standing compute. Provisioned by `infra/aws/primary/` (+ `infra/aws/state-bootstrap/` for state). Region-loss recovery is manual: `docs/dr-runbook-aws.md`.

| Resource | Name (production) | Notes |
|---|---|---|
| VPC | `madeithome-vpc-production` | 10.20.0.0/16 (10.30.0.0/16 reserved for a DR rebuild in us-east-2) |
| ECS cluster | `madeithome-cluster-production` | Fargate-only |
| ECR (web) | `madeithome-web-production` | Image-scan-on-push; IMMUTABLE tags |
| ECR (worker) | `madeithome-worker-production` | Same |
| RDS Postgres | `madeithome-db-production` | `db.t4g.medium`, **Multi-AZ** (staging single-AZ); master password managed by RDS; backups replicated to us-east-2 |
| S3 photos | `madeithome-photos-production-<account>` | Versioning + 30-day noncurrent expiration; CORS scoped to prod domain |
| Secrets Manager | `madeithome-<KEY>-production` | One container per backend secret; replicated to failover region |
| ALB | `madeithome-alb-production` | HTTPS listener (TLS 1.3) + HTTP→HTTPS redirect |
| ACM cert | DNS-validated | Operator adds CNAME to Cloudflare |
| Web ECS service | `madeithome-web-production` | Desired 2 (prod) / 1 (staging); CPU target-tracking autoscale up to 10 |
| Worker ECS service | `madeithome-worker-production` | Always-on `worker_loop.py`; warm ~60s tick, desired 1, advisory-lock serialized |
| Migrate task | `madeithome-migrate-production` | One-off; CD runs `alembic upgrade head` before web swap |
| DB-init task | `madeithome-db-init-production` | One-off; operator runs `infra/aws/scripts/init-db.sh` |
| SNS bridge Lambda | `madeithome-sns-bridge-production` | Forwards SNS SMS delivery events to `/webhooks/delivery/sns` |

Naming convention: `madeithome-{resource}-{env}` for in-account/per-region resources; `madeithome-{resource}-{env}-{account_id}` for globally-unique resources (S3 only). Convention details and rationale in `infra/aws/README.md`.

## Key decisions
- **Public subnets + tight SGs for Fargate.** Saves ~$70/mo per env in NAT Gateway. Tasks have public IPs but their SG only allows inbound from the ALB SG. RDS is in private subnets.
- **`db.t4g.medium`; Multi-AZ in production, single-AZ in staging.** Roughly ~$50/mo single-AZ, ~2× for Multi-AZ. Production Multi-AZ buys automatic ~1–2 min in-region failover with zero data loss — the dominant availability win for a safety app. Staging tolerates downtime, so it stays cheap.
- **IMMUTABLE ECR tags.** Each deploy gets a SHA-tagged image; nothing overwrites. Avoids the staging-incident mystery of "the same tag points at different bytes than expected."
- **Always-on worker service over per-minute scheduling.** The worker runs `worker_loop.py` as a long-lived ECS service (desired 1) so a due notification goes out within seconds of becoming due — the previous EventBridge Scheduler → RunTask paid a ~20–60s Fargate cold start on every minute-ly tick. The Postgres advisory lock in `run_tick_with_lock` still serializes ticks, so a rolling deploy's old+new task can't double-process. `worker_tick.py` (one tick, then exit) stays as the migrate one-off + manual/rollback entrypoint.
- **RDS `manage_master_user_password = true`.** AWS generates + rotates the master password in Secrets Manager; no plaintext in TF state.
- **Secrets Manager cross-region replicas.** Each secret in the primary region is mirrored to the failover region so a DR rebuild can read them there.
- **Container Insights env-conditional.** Always-on in prod (incident data), off in staging (cost).
- **SNS delivery status logging is account-level.** Production stack owns the log groups; staging data-sources them. `infra/aws/scripts/setup-sns-delivery-logging.sh` sets the SNS attribute once per account.

## First-time AWS setup (per environment)
Order matters: production must be applied before staging in any given account because production owns the account-level SNS log groups + the source secret containers that staging's replicas mirror from.

1. **Configure AWS credentials** locally (`aws sts get-caller-identity` must succeed).
2. **Bootstrap Terraform state** (one-time per env):
   ```bash
   cd infra/aws/state-bootstrap
   terraform init
   terraform workspace new production && terraform workspace select production
   terraform apply -var environment_name=production
   # then for staging
   terraform workspace new staging && terraform workspace select staging
   terraform apply -var environment_name=staging
   ```
3. **One-time per account**: configure SNS SMS delivery status logging:
   ```bash
   infra/aws/scripts/setup-sns-delivery-logging.sh
   ```
4. **Bootstrap the env** (creates VPC, RDS, ECS, ALB, etc.):
   ```bash
   infra/aws/scripts/bootstrap.sh production
   # then staging
   infra/aws/scripts/bootstrap.sh staging
   ```
5. **Cloudflare side (manual)**:
   - Add the ACM validation CNAMEs (from `terraform output acm_validation_records`)
   - Add a CNAME for the app domain pointing at `terraform output alb_dns_name`
6. **Populate secrets** (per env):
   ```bash
   cp infra/secrets/example.secrets.env infra/secrets/production.secrets.env
   # fill in values
   infra/aws/scripts/populate-secrets.sh production
   ```
7. **Wire GitHub Actions → AWS** via OIDC (one-time per env):
   ```bash
   infra/aws/scripts/setup-github-oidc.sh production
   # then staging
   infra/aws/scripts/setup-github-oidc.sh staging
   ```
   The script prints a `gh secret set ...` command for the role ARN; run it (or paste the ARN into the GitHub Environment's `AWS_ROLE_TO_ASSUME` secret in the UI). Without this, a `workflow_dispatch` run of CD fails to assume any role and the run shows `startup_failure` with no logs.
8. **First image build**: run `cd.yml` via `workflow_dispatch` for the env (builds and pushes to ECR; the first migrate run will fail until step 9 — that's expected). CD is manual-only (its `workflow_run` auto-deploy-on-master trigger is commented out, see the top of this doc) — a plain push to master does **not** build or deploy anything.
9. **Create the app role + DB** on RDS:
   ```bash
   infra/aws/scripts/init-db.sh production
   ```
10. **Re-run `workflow_dispatch`** (or manually run a migrate task) and verify health: `curl https://{env-domain}/health/ready` should return 200 with `database: ok`.
11. **Twilio Advanced Opt-Out + inbound webhook URL** (per env's Messaging Service): see `docs/sms-stop-flow-setup.md`. Without this, STOP texts fall back to Twilio's generic reply and the cascade webhook never fires.

## Ongoing AWS deploys
`cd.yml` calls `deploy-aws.yml` for each env. Per deploy it:
1. Builds + pushes web + worker images (tagged with the deploy SHA)
2. Registers a new migrate task def revision and runs it
3. Waits for migrate exit code 0
4. Registers a new web task def revision and updates the web service; waits for steady state
5. Registers a new worker task def revision and updates the worker service; waits for steady state (long-lived service — same rolling-deploy pattern as web)
6. Verifies `/health/ready` on the public domain

### Verifying error reporting (Bugsnag)

Bugsnag was silent for months because nothing ever proved delivery. Now:

- **Before a deploy, from your machine**: `BUGSNAG_API_KEY=<backend key> make error-reporting-smoke [STAGE=staging]` sends two events (an explicit notify and a `logger.error`) with synchronous delivery and fails on any SDK delivery error (401 for a bad key, egress, ...). Mobile: `MOBILE_BUGSNAG_API_KEY=<mobile key> npm run error-reporting:smoke` (in `mobile/`) posts one event to the notify API and checks the 200.
- **After a deploy**: open the admin dashboard → *Error reporting (Bugsnag)* → **Send error-reporting test event**. The panel shows the release stage and the deployed `GIT_SHA`; the event should appear in Bugsnag within a minute under that stage/version. `GET /health` returns `version` (the SHA) and `GET /health/ready` reports `error_reporting: configured|unconfigured` (informational).
- **Boot guard**: in staging/production the web and worker refuse to start with a blank `BUGSNAG_API_KEY` (`app/core/startup_checks.py`), so a bad secret shows up as a failed deploy, not as silence. The value comes from Secrets Manager via the Terraform-rendered task spec (`/madeithome/<env>/task-container-spec`) — a manifest change needs `terraform apply` before CD can pick it up.
- **Version stamping**: `deploy-aws.yml` passes `--build-arg GIT_SHA=<commit>` to both image builds; `app/core/version.py` exposes it and `app/core/error_reporting.py` uses it as `app_version`.

### AWS migrations
Expand/contract rules apply — see the [Migrations](#migrations) section below. Migrations run inside the VPC against the private RDS via a one-off ECS RunTask before the web service is rolled.

### Runbook: changing the worker's execution model (cutover gotcha)
The worker task def command is shared between the always-on service and any
one-off/manual RunTask. **If you ever reintroduce a scheduled RunTask (or cut
back over), change the ordering deliberately:** a scheduled RunTask resolves
`<family>:LATEST`, so if you change the task-def `command` while a scheduler is
still firing, in-flight RunTasks inherit the new command. When the warm service
was introduced (2026-07-16), flipping the command to `worker_loop.py` *before*
deleting the schedule left 7 scheduled RunTasks running the infinite loop instead
of one-shotting — harmless (the advisory lock serialized them) but they never
exit and had to be `aws ecs stop-task`'d by hand. **Order: remove the schedule
first, then change the command.** For a from-scratch `bootstrap` there is no
schedule, so this only matters on a live cutover.

If strays do get created, stop the standalone tasks (`startedBy` = `chronos-schedule/…`)
and leave the service task (`startedBy` = `ecs-svc/…`):
```bash
ENV=production   # or staging
for t in $(aws ecs list-tasks --cluster madeithome-cluster-$ENV --family madeithome-worker-$ENV --query 'taskArns' --output text); do
  sb=$(aws ecs describe-tasks --cluster madeithome-cluster-$ENV --tasks "$t" --query 'tasks[0].startedBy' --output text)
  case "$sb" in chronos-schedule*) aws ecs stop-task --cluster madeithome-cluster-$ENV --task "$t" --reason "stray scheduled RunTask post-cutover" >/dev/null ;; esac
done
```

### Runbook: RDS Postgres version upgrades
`rds.tf` pins only the **major** version as a create-time floor (`engine_version
= "16"`) and `ignore_changes = [engine_version]`, because `auto_minor_version_
upgrade` (RDS default) advances the live minor version and Postgres can't
downgrade — a static full pin makes every later `terraform apply` error on an
impossible downgrade (this bit the 2026-07-16 worker apply). So:
- **Minor upgrades** (16.13 → 16.x): automatic, no action; TF ignores them.
- **Major upgrades** (16 → 17): deliberate. Temporarily remove `engine_version`
  from the `ignore_changes` list, set `engine_version = "17"` and
  `allow_major_version_upgrade = true`, `terraform apply` (in a maintenance
  window — a major upgrade reboots), verify, then restore the `ignore_changes`
  entry. Bump the `postgres16` parameter-group `family` to match.

## DR (backup-only, runbook-driven)

There is **no warm standby and no automatic cross-region failover**. The
posture, chosen deliberately for cost/complexity:

- **In-region HA**: production RDS is **Multi-AZ** — instance/AZ failures
  fail over automatically in ~1–2 min with zero data loss. Nothing to do.
- **Region loss**: recovered **manually** per `docs/dr-runbook-aws.md`
  (restore replicated backup in us-east-2, stand up compute, cut DNS over).
  Pre-staged in us-east-2, all production-gated in Terraform: RDS automated
  backups (`primary/rds_backup_replication.tf`), ECR images + DR repos
  (`primary/ecr.tf`), Terraform state (`state-bootstrap/replication.tf` —
  applied separately via the production workspace), and Secrets Manager
  replicas. Data only — no compute, no standby DB.
- The runbook must be **drilled quarterly** (procedure in the runbook).

An earlier warm-standby stack (`infra/aws/failover/`: cross-region read
replica + ECS at desired=0 + Cloudflare-worker-triggered promotion) was
removed without ever being applied — recover it from git history only if
the RTO requirement tightens enough to justify ~2× the DB cost.

## Teardown (AWS)
`infra/aws/scripts/teardown.sh <env>`. Several resources have `prevent_destroy = true` (state bucket + lock table, RDS, photos S3 bucket) — the script's comment block explains how to override. The photos bucket must be emptied manually before destroy will succeed.

## Migrations
**Migrations must be backward-compatible (expand/contract).** The web is rolling-deployed so the old revision serves during the migration + the swap.

- **Safe (one release):** additive changes — new nullable columns/tables, new indexes, new enum values.
- **Two releases for destructive changes** (drop/rename a column, tighten NOT NULL):
  - *Expand*: add the new shape + deploy code that writes both old + new.
  - *Contract*: once no running revision uses the old shape, drop it.
  - Never drop or rename in the same release that stops using it.
- **Recorded exception (owner decision 2026-09-05):** `d75a707d6ba9` dropped `session_photos` + `sessions.photo_sharing_enabled` in the same release that stopped using them (as `b7d3e1a2c4f5` did for the battery toggle). During the swap window the outgoing tasks error on session reads (web 500s; worker ticks log and skip). Deploy it in a quiet window; it is not precedent for relaxing the rule. Orphaned `session-photos/` S3 objects age out via the bucket lifecycle rule in `infra/aws/primary/s3.tf` — apply that Terraform change with the deploy.

## Account deletion ops runbook

The account-deletion pipeline (see `docs/account-deletion-plan.md` for design) runs largely on its own — the hourly hard-purge step inside `worker_tick.py` does the heavy lifting. The notes below are for the rare incidents where you need to peek under the hood, force progress, or unstick a row.

### Tick log fields to watch

`worker_tick.tick` emits a structured summary log each minute. Account-deletion-relevant fields:

- `purges_done` — non-zero only on the top of the hour (`now.minute == 0`); how many rows the hard-purge step anonymized this tick. Stuck/0 across many hours with a backlog of grace-expired rows ⇒ inspect manually with the query below.
- `lapse_reminders_sent` — T-7d / T-1d subscription-lapse SMS dispatched. Independent of purges.
- `errors` — JSON list of `<step>: <exception>` for any `_safe(...)` block that swallowed an exception (including `process_pending_purges`, `process_pending_lapse_reminders`, the Stripe webhook fan-out). Search Bugsnag for the matching `hard_purge_user_failed` / `lapse_reminder_*_failed` / `sub_lapse_notify_dispatch_failed` events.

### Inspect pending purges

```sql
-- Users in grace (deleted_at set, not yet eligible for purge)
SELECT id, phone_number_id, deleted_at,
       deleted_at + INTERVAL '30 days' AS scheduled_purge_at
FROM users
WHERE deleted_at IS NOT NULL
  AND deleted_at >= NOW() - INTERVAL '30 days'
ORDER BY deleted_at;

-- Grace-expired users the worker hasn't anonymized yet (the worker
-- only runs at minute 0 — anything older than the last top-of-hour
-- ought to have been processed)
SELECT u.id, u.deleted_at, u.full_name IS NULL AS appears_purged
FROM users u
WHERE u.deleted_at IS NOT NULL
  AND u.deleted_at < NOW() - INTERVAL '30 days'
  AND NOT EXISTS (
      SELECT 1 FROM sessions s
      WHERE s.user_id = u.id
        AND s.status IN ('active', 'missed', 'alerted')
  )
ORDER BY u.deleted_at;
```

If the second query returns rows from earlier than the last hourly tick:

1. Check `errors` in the most recent `tick complete` log line for that user_id under `hard_purge_user_failed`.
2. Check Bugsnag for the matching exception.
3. The function is idempotent (re-runs on a row with `stripe_customer_id` already `purged:*` are no-ops) so it is safe to manually re-run from a Python shell:
   ```python
   from app.db.session import AsyncSessionLocal
   from app.services.account_deletion import hard_purge_user
   from app.crud import crud_user
   async with AsyncSessionLocal() as db:
       user = await crud_user.get(db, id="<user_id>")
       await hard_purge_user(db, user)
   ```

### Manual restore inside grace

If a user reports they can't recover via the in-app Welcome Back screen (e.g., the deletion was performed by ops on their behalf and they want to undo it), call the orchestrator from a Python shell:

```python
from app.db.session import AsyncSessionLocal
from app.services.account_deletion import restore_user_account
from app.crud import crud_user
async with AsyncSessionLocal() as db:
    user = await crud_user.get(db, id="<user_id>")
    await restore_user_account(db, user)
```

`restore_user_account` will raise `GraceExpiredError` if `deleted_at < now - 30 days` — that's the same gate the HTTP endpoint enforces, and is what produces the 410 Gone the mobile app sees. If you genuinely need to restore a past-grace row (e.g., the deletion was an ops mistake AND the worker hasn't anonymized yet), call the lower-level primitive `restore_user(db, user)` directly. Check `SELECT full_name FROM users WHERE id = '<user_id>';` first — a NULL full_name means hard-purge already ran and no restore can recover the PII.

### Stripe outages mid-deletion

The `delete_user_account` orchestrator swallows Stripe errors so the user's soft-delete still completes. If Stripe was unreachable when a user clicked Delete, their subs were NOT actually cancelled and will continue billing. Watch Bugsnag for `stripe_cancel_failed_during_deletion` warnings; reconciling manually:

```python
# For each subscription that should have been cancelled:
import stripe
stripe.Subscription.modify("sub_xxx", cancel_at_period_end=True)
```

The plan was for a worker-tick reconciler to chase these. That is intentionally deferred — the volume should be near zero (Stripe is rarely down for the seconds it takes to process a deletion), and Bugsnag's alerting is the catch.

### Notification fan-out troubleshooting

`process_pending_lapse_reminders` runs every minute. If a user reports they didn't get a T-7d / T-1d SMS:

1. Check the subscription row: `SELECT lapse_reminder_7d_sent_at, lapse_reminder_1d_sent_at, current_period_end, auto_renew, status FROM subscriptions WHERE id = '<sub_id>';`
2. If `auto_renew` is true, no reminder is expected — the sub is still set to renew.
3. If a stamp is set but the SMS never arrived, the dispatch succeeded from our side; check Twilio / AWS SNS delivery logs for that phone.
4. To force re-fire: `UPDATE subscriptions SET lapse_reminder_7d_sent_at = NULL WHERE id = '<sub_id>';` and wait one tick.

### Re-signup linking

Phase 9 attaches an existing Stripe Customer (matched by `phone`) when a user signs back up after their grace expired. To verify a returning user landed correctly:

```sql
SELECT id, stripe_customer_id, had_prior_billing_history
FROM users WHERE id = '<user_id>';
```

A successful re-attach has `stripe_customer_id` matching the original `cus_*` (not `pending:*`) and `had_prior_billing_history` set to `true`. If the user complains about getting a free-trial session they shouldn't have earned, the flag is the gate; set it manually if needed:

```sql
UPDATE users SET had_prior_billing_history = true WHERE id = '<user_id>';
```

---

# Cloudflare health-check failover

`infra/cloudflare/` runs a Worker on Cloudflare's network every minute. Pings the primary's `/health/ready`; after 3 consecutive failures, executes the failover sequence against the configured `TARGET_CLOUD`:
- **aws**: ⚠️ **superseded — do not enable.** This mode targeted the removed warm-standby stack (RDS PromoteReadReplica + standby ECS); those resources no longer exist. AWS region loss is handled manually per `docs/dr-runbook-aws.md`.

Inline SigV4 via Cloudflare's Web Crypto (no external libs). See `worker.js` header for the minimum-priv IAM policy required for the worker's AWS credentials.
