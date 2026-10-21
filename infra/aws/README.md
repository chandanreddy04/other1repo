# AWS infrastructure

Terraform stacks for the AWS deploy path. Everything runs in the primary
region (`us-west-2`). Disaster recovery is **backup-only**: production
replicates its data (RDS automated backups, ECR images, Terraform state,
secrets) to `us-east-2`, and a region loss is recovered manually per
`docs/dr-runbook-aws.md`. There is no warm standby — an earlier
active-passive `failover/` stack (cross-region read replica + standby ECS)
was removed in favor of this posture; see git history if it's ever
revisited.

## Layout

```
infra/aws/
├── README.md                ← this file (naming convention + index)
├── state-bootstrap/         ← one-time S3 + DynamoDB for Terraform state (PR 6)
│                              + prod-only state-bucket CRR to us-east-2
├── primary/                 ← us-west-2: VPC + RDS + ECS + ALB + workers (PR 7-12)
│                              + prod-only backup/ECR replication to us-east-2
└── scripts/                 ← bootstrap, populate-secrets, init-db, teardown (PR 13)
```

## Bootstrap order (new account)

Run these once, in order, the first time you stand up an account. Steps
marked **account-level** are shared by both envs and run only once total;
the rest run per env (`staging`, then `production`).

1. **AWS identity** — do NOT use the account root user. Create an IAM
   admin (or SSO role) and use its access key:
   `aws iam create-user --user-name madeithome-terraform`,
   attach `AdministratorAccess`, configure the CLI with its key.
2. **state-bootstrap/** (per env) — S3 state bucket + DynamoDB lock table.
   Uses Terraform **workspaces** (`staging`/`production`) — select the
   right workspace before apply (see `state-bootstrap/README.md`).
3. **setup-sns-delivery-logging.sh** (**account-level**, per region) — must
   run BEFORE the first `bootstrap.sh`. It creates the SNS delivery-status
   CloudWatch log groups that the primary stack reads via a data source.
   Without it, `terraform plan` fails with an opaque "empty result" error.
4. **scripts/bootstrap.sh `<env>`** — the primary stack. Preflights for
   steps 2 and 3 and fails fast with a fix hint if either is missing. Set
   `BOOTSTRAP_AUTO_APPROVE=1` for non-interactive/CI runs.

### Staging-first caveat: SNS log-group ownership

The SNS SMS delivery-status log groups are **account-level** (one pair per
region+account), so only one stack can own them in Terraform.
`sns_delivery.tf` makes **production** own them (resource) and **staging**
read them (data source). Two supported paths:

- **Production first** (the design's default): production creates the log
  groups; staging reads them. Nothing extra to do.
- **Staging first**: `setup-sns-delivery-logging.sh` (step 3) pre-creates
  the log groups so staging's data source resolves. When production is
  later applied, it must **adopt** them instead of recreating:
  ```
  terraform import 'aws_cloudwatch_log_group.sns_sms_success[0]' \
    sns/<region>/<account>/DirectPublishToPhoneNumber
  terraform import 'aws_cloudwatch_log_group.sns_sms_failure[0]' \
    sns/<region>/<account>/DirectPublishToPhoneNumber/Failure
  ```
  The script creates them at 30-day retention to match production's
  `log_retention_days`, so the import shows zero drift.

### Fresh-account Lambda quota

New AWS accounts ship with a total Lambda concurrency limit of **10**. The
SNS bridge Lambda's reservation (`sns_bridge_reserved_concurrency`)
therefore defaults to `-1` (no reservation) — any positive value would drop
the unreserved pool below AWS's minimum of 10 and fail the apply. After
raising the account's "Concurrent executions" Service Quota, set a cap with
`-var sns_bridge_reserved_concurrency=10`.

## Naming convention

Every AWS resource follows **`madeithome-{resource}-{env}[-{account}]`**:

| Resource scope | Pattern | Example |
|---|---|---|
| In-account, per-region (most) | `madeithome-{resource}-{env}` | `madeithome-cluster-staging` |
| Globally-unique (S3 buckets) | `madeithome-{resource}-{env}-{account_id}` | `madeithome-photos-staging-123456789012` |
| Region-scoped, env in suffix | `madeithome-{resource}-{env}` | `madeithome-tfstate-lock-staging` |

**Env values**: always `staging` or `production` — no abbreviations, no
empty-string-means-prod. Each Terraform stack accepts `environment_name`
as a required `-var` with a validation block; passing anything else fails
fast before any resource is touched.

### Why explicit env in every name?

A prefix-based convention (prod unprefixed, staging prefixed) only works
when something else isolates environments. AWS has no such boundary here —
prod and staging resources can sit in the same account without
isolation. Explicit env names in every resource make operator mistakes
loud (no `madeithome-cluster` ambiguity about which env it belongs to).

## Per-environment AWS accounts

The current plan runs both envs in the **same AWS account** because the
naming convention disambiguates them. If/when the team moves to separate
accounts per env (recommended once production traffic justifies the
operational overhead), nothing in the naming changes — the per-account
suffix on S3 buckets already handles it.

## Manifest values

`AWS_S3_BUCKET` and similar static manifest entries in
`infra/secrets/manifest.json` use placeholder values shaped after this
convention. The real values get computed by Terraform and pushed to
Secrets Manager via `populate-secrets.sh` (PR 13), which reads Terraform
outputs. The manifest defaults serve as documentation of the expected
shape, not as the authoritative source.
