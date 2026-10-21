# Secrets Manager containers for every secret value the app reads.
#
# Provisions ONLY the secret resources — values are populated by
# populate-secrets.sh (PR 13), which reads infra/secrets/manifest.json +
# the operator's secrets.env file and pushes versions to each container.
#
# The list of secrets is derived from manifest.json at plan time (single
# source of truth — no drift possible between this file and the manifest).
# The DB admin password is managed separately by RDS itself
# (manage_master_user_password = true in rds.tf) and doesn't appear here.

locals {
  # Read the manifest sitting at the repo root. file() is relative to
  # the module dir (infra/aws/primary/), so go up two levels.
  _manifest = jsondecode(file("${path.module}/../../secrets/manifest.json"))

  # Backend secret env vars from the manifest. Mobile entries (EAS) and
  # static (non-secret) entries are filtered out — this matches what
  # populate-secrets.sh pushes to Secrets Manager.
  #
  # `optional: true` entries are also filtered out. They exist in the
  # manifest for completeness but aren't always set, and AWS shouldn't
  # create empty SM secrets for them — empty SecretString values are
  # rejected by the SM API
  # (min length 1), and an unreferenced SM secret + ECS task def
  # `secrets` entry → ResourceNotFoundException at task start.
  backend_secret_names = [
    for entry in local._manifest.secrets :
    entry.backend_env
    if try(entry.side, "") == "backend"
    && try(entry.secret, false) == true
    && try(entry.optional, false) == false
  ]

  # Production gets the standard 30-day recovery window (AWS recommendation
  # for prod secrets); staging uses 7 days to keep teardown nimble.
  secret_recovery_days = var.environment_name == "production" ? 30 : 7
}

resource "aws_secretsmanager_secret" "app" {
  for_each = toset(local.backend_secret_names)

  name                    = "${local.name_prefix}-${each.key}-${local.env}"
  description             = "${each.key} for ${local.env}. Value populated by populate-secrets.sh (PR 13)."
  recovery_window_in_days = local.secret_recovery_days

  # Cross-region replication: each secret is automatically mirrored to
  # the failover region so a DR rebuild (docs/dr-runbook-aws.md) can read
  # it there by the same name — replicas share the source's name but have
  # a different ARN in the replica region. Replication propagates value
  # updates within seconds.
  #
  # FOOTGUN: Secrets Manager doesn't support changing replica regions
  # in-place. Updating var.failover_region requires destroying and
  # re-creating every secret. Don't change this casually.
  replica {
    region = var.failover_region
  }

  tags = {
    Name   = "${local.name_prefix}-${each.key}-${local.env}"
    Secret = each.key
  }
}
