# AWS Disaster Recovery Runbook — Region Loss

**Scope:** recovering the production backend after the loss of the primary
AWS region (`us-west-2`), using the **backup-only DR** posture we chose:
no warm standby, no automatic failover. Recovery is **manual and
runbook-driven**, trading a longer RTO for much lower cost and complexity.

This runbook covers the database (RDS) and the supporting app tier. It is
intentionally honest about what is and isn't pre-staged — read
[Dependencies & gaps](#dependencies--gaps) before you need it, not during
an incident.

> For everyday failures (a single instance/AZ dying), there is **nothing to
> do** — production RDS is **Multi-AZ**, so AWS fails over automatically in
> ~1–2 minutes with zero data loss. This runbook is **only** for losing the
> whole `us-west-2` region.

---

## Recovery objectives (honest estimates)

| Metric | Expectation | Why |
|---|---|---|
| **RPO** (data loss) | **~minutes** | Automated backups are replicated cross-region; the destination's latest-restorable-time lags the source by the replication lag (typically a few minutes). |
| **RTO — database** | **~15–30 min** | Restore the replicated backup to a new instance in `us-east-2`. |
| **RTO — full app** | **hours (first time)** | There is **no pre-built compute/network in `us-east-2`**. It must be stood up (see gaps). With the mitigations applied, this drops to ~30–60 min. |

If a multi-hour full-app RTO is unacceptable, the decision changes — revisit
the warm-standby `failover/` stack (removed; recover from git history) or
Aurora Global Database (see the Aurora research notes).

---

## What IS pre-staged (works today)

- **Database backups** — production automated backups (with PITR) are
  continuously replicated to `us-east-2` via
  `aws_db_instance_automated_backups_replication`
  (`infra/aws/primary/rds_backup_replication.tf`), encrypted with the
  `madeithome-backup-dr-production` KMS key there.
- **Application secrets** — all Secrets Manager secrets are replicated to
  `us-east-2` (`secrets.tf` `replica` block). Same names, different ARNs.

## Dependencies & gaps

These live in `us-west-2` today and are therefore **unavailable during a
region loss**. Closing them is what makes this runbook fast and reliable —
treat them as pre-incident work:

| Dependency | State | Notes |
|---|---|---|
| **ECR container images** | ✅ **Replicated (production)** | `primary/ecr.tf` (`aws_ecr_replication_configuration`) replicates the prod web/worker images to `us-east-2`. Active once production is applied; only images pushed after enablement replicate. |
| **Terraform state** | ✅ **Replicated (production)** | `state-bootstrap/replication.tf` continuously replicates the prod state bucket to `us-east-2` (CRR). Active once the production state-bootstrap is applied. |
| **Compute/network in us-east-2** | ⚠️ Not provisioned | Either pre-apply a minimal copy of `primary/` in `us-east-2`, or accept the bring-up time during recovery. This is the dominant remaining RTO cost. |
| **ACM cert in us-east-2** | ⚠️ Not provisioned | A new cert + Cloudflare DNS validation is needed for the failover ALB (minutes). |

> Two of the four dependencies (images, state) are now closed in code for
> **production** — so a region-loss recovery no longer stalls on "can't pull
> the image" or "can't read state." The remaining two (compute/network, ACM)
> are deliberately left to recovery time, matching the backup-only DR choice.
>
> ⚠️ **These live in two different stacks applied by two different commands.**
> ECR + RDS-backup replication ship with the `primary/` stack (`bootstrap.sh
> production`); **state** replication ships with `state-bootstrap/` and only
> activates when you apply its **production workspace** separately. Applying
> primary but forgetting the prod state-bootstrap leaves state un-replicated
> while everything else looks done. Also confirm both stacks use the **same**
> `failover_region` — state, backups, and images must land in one region.
> **Verify in the quarterly drill that the state bucket actually exists in
> the failover region**, not just that the code is present.

---

## Recovery procedure

> Prereqs: AWS creds for the account; `terraform`, `aws`, `jq` installed;
> Cloudflare access for the DNS cutover.

### 1. Declare the disaster
- Confirm `us-west-2` is genuinely down (AWS Health Dashboard, `/health/ready`
  failing region-wide, not just one AZ). **Do not invoke this for an AZ
  blip** — Multi-AZ already handles that.
- Announce the incident; designate one operator to avoid split-brain actions.

### 2. Restore the database in us-east-2
```bash
export AWS_REGION=us-east-2
# Find the replicated automated backup for the source instance:
aws rds describe-db-instance-automated-backups \
  --query "DBInstanceAutomatedBackups[?contains(DBInstanceArn,'madeithome-db-production')].{ARN:DBInstanceAutomatedBackupsArn,Latest:RestoreWindow.LatestTime}"

# Point-in-time restore to a NEW instance in us-east-2 (use the latest
# restorable time, or an earlier point if recent data is suspect):
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-automated-backups-arn "<ARN from above>" \
  --target-db-instance-identifier madeithome-db-production-dr \
  --restore-time "<LatestTime or chosen point>" \
  --db-subnet-group-name <us-east-2 subnet group> \
  --no-multi-az
```
Wait for status `available` (~15–30 min). Note the new endpoint.

### 3. Stand up compute in us-east-2
- Ensure the backend image is available in `us-east-2` ECR (replicated, or
  push it now).
- Apply the app stack in `us-east-2` (a copy of `primary/`), with
  `DATABASE_URL` pointing at the restored instance's endpoint. Secrets are
  already replicated.
- Provision/validate the ACM cert for the app domain (add the validation
  CNAME in Cloudflare).
- Run DB migrations if the restored version is behind the image
  (`migrate` task), and create/verify the app DB role (`init-db.sh`).

### 4. Cut traffic over (Cloudflare)
- Repoint the app-domain CNAME to the `us-east-2` ALB DNS name.
- Lower the record TTL first if time permits, to speed propagation.
- Verify: `curl https://app.madeithomeapp.com/health/ready` returns 200.

### 5. Verify
- OTP/SMS send works (Twilio/SNS reachable from the new region).
- A test check-in session creates, alerts dispatch, Stripe webhook reachable.

---

## Failback (when us-west-2 returns)

1. Stop writes to the DR instance (maintenance window / read-only).
2. Re-establish `us-west-2` as primary: restore/replicate the DR data back,
   bring the `primary/` stack healthy, run migrations.
3. Cut Cloudflare DNS back to the `us-west-2` ALB.
4. Tear down the temporary `us-east-2` app stack (keep backup replication).
5. Reconcile Terraform state for any resources created out-of-band during
   recovery (`terraform import` / `terraform refresh`).

---

## Testing this runbook

Backup-only DR is worthless if untested. Schedule a **drill at least
quarterly**, in a scratch context (never against live prod traffic):

1. Restore the replicated backup to a throwaway `*-dr-drill` instance in
   `us-east-2` and confirm the data is intact and recent (check RPO — how
   far behind is `LatestRestorableTime`?).
2. Stand up the app against it in `us-east-2` and hit `/health/ready`.
3. Time each phase; record actual RTO and compare to the table above.
4. Delete the drill resources.
5. File any gaps discovered (missing ECR image, stale runbook command,
   permission error) and fix them — that's the point of the drill.

> First drill after initial production setup is a required sign-off item.
