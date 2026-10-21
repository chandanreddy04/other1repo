# Terraform remote state bootstrap

One-time stack that provisions the S3 bucket + DynamoDB lock table used as
the backend for every other Terraform stack under `infra/aws/`.

## Why this is separate

Terraform stores state. State has to live somewhere. The convention is an
S3 bucket + a DynamoDB table for locking, but **you can't use a remote
backend before it exists** — chicken and egg. So this stack uses **local
state on purpose** and only runs once per environment.

## When to run this

- First time setting up an environment (staging or production)
- Never again, unless you're tearing the whole environment down

The sibling `infra/aws/primary/` stack references this stack's outputs
as its backend config — it will fail to `terraform init` until this
stack has been applied.

## Procedure

The same Terraform working directory is used for both environments, with
**Terraform workspaces** isolating their state. Running staging and prod
without workspaces would reuse one local state file and corrupt the other.

```bash
cd infra/aws/state-bootstrap
terraform init

# --- Production (one-time) ---
terraform workspace new production    # first time only
terraform workspace select production
terraform apply -var environment_name=production
#  → confirms with `yes`; creates:
#    bucket: madeithome-tfstate-production-<accountId>
#    table : madeithome-tfstate-lock-production

# --- Staging (one-time) ---
terraform workspace new staging       # first time only
terraform workspace select staging
terraform apply -var environment_name=staging
#  → creates:
#    bucket: madeithome-tfstate-staging-<accountId>
#    table : madeithome-tfstate-lock-staging
```

There is no default for `environment_name`, and Terraform validates that
the value is exactly `staging` or `production` — `terraform apply` with a
typo or no `-var` will fail loudly before doing anything.

The resulting bucket + table names get wired into sibling stacks' backend
blocks. Both resources have `prevent_destroy = true` — `terraform destroy`
will fail loudly so state isn't lost by accident. To intentionally tear
down an environment, comment out the `prevent_destroy` blocks first, then
apply, then destroy.

## Local state file — back it up

After applying, `terraform.tfstate.d/<workspace>/terraform.tfstate` will
exist locally (one per workspace). **Do not commit it** — the root
`.gitignore` excludes `*.tfstate*`. But you MUST back it up:

- **Recommended**: store an encrypted copy in the team's password manager
  (1Password / Bitwarden, as a secure note attachment per environment)
- **Acceptable**: keep on the operator's machine + a separate encrypted
  external drive

Losing it means future runs of this stack can't manage the resources it
created. The resources keep working because of `prevent_destroy`, but any
future change has to be done via the AWS console + `terraform import`.

## CI considerations

This stack is intentionally **not** run from CI. It's a one-time human
operation with a fragile local state file. The CI workflow (`deploy-aws.yml`,
added in PR 16) assumes the state bucket already exists and references it
as the backend for sibling stacks.
