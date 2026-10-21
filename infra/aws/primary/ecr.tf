# ECR repositories for the backend web + worker images.
#
# Two repos — same Python image content today (worker is just a different
# entrypoint), but kept separate so they can diverge (e.g., a slimmer
# worker image without web deps) without touching the deploy plumbing.
#
# Two repos: madeithome (web) and madeithome-worker.

locals {
  ecr_repos = ["web", "worker"]

  # Shared lifecycle policy applied to BOTH the primary repos and their
  # us-east-2 DR replicas, so the two can never drift. Rule-order note
  # lives on the source resource below.
  ecr_lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 7 days (leftover build layers)"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the 30 most recent tagged images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 30
        }
        action = { type = "expire" }
      },
    ]
  })
}

resource "aws_ecr_repository" "app" {
  for_each = toset(local.ecr_repos)

  name = "${local.name_prefix}-${each.key}-${local.env}"

  # Image scanning on push — free for the first 100 scans/region/month,
  # then cheap. Worth always-on for security regressions.
  image_scanning_configuration {
    scan_on_push = true
  }

  # Encrypt with default AWS-managed KMS — no extra key to manage.
  encryption_configuration {
    encryption_type = "AES256"
  }

  # IMMUTABLE in both envs: a tag identifies an exact set of bytes,
  # always. Rapid iteration uses different tags (commit-sha-based), not
  # overwriting an existing one. Avoids the kind of staging-incident
  # mystery where the "same" tag points at different bytes than expected.
  image_tag_mutability = "IMMUTABLE"

  tags = {
    Name = "${local.name_prefix}-${each.key}-${local.env}"
  }
}

# Lifecycle policy: keep the last N images, expire older ones to control
# storage cost. 30 images covers ~1 month of daily deploys + buffer.
#
# Rule order matters: ECR evaluates rules by rulePriority (ascending) and
# applies the FIRST matching rule. Rule 1 cleans untagged images first;
# rule 2's `imageCountMoreThan: 30` then counts ONLY the surviving tagged
# images. Do not reorder.
resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name
  policy     = local.ecr_lifecycle_policy
}

# Cross-region replication of PRODUCTION images to the failover region,
# supporting backup-only DR (docs/dr-runbook-aws.md): a region-loss
# recovery in us-east-2 needs the backend image available there.
#
# OWNERSHIP: the registry replication configuration is an account+region
# SINGLETON (one per registry). Staging and production share the us-west-2
# registry, so — exactly like the SNS delivery log groups in
# sns_delivery.tf — the PRODUCTION stack owns it; staging does not manage
# it. The repository_filter scopes replication to the production repos
# only, so staging images are never replicated even though the
# configuration itself is registry-wide.
#
# CAVEAT: replication copies only images pushed AFTER it's enabled —
# existing images are not backfilled. Created before the first production
# CD push, so all prod images replicate from day one.
resource "aws_ecr_replication_configuration" "prod_dr" {
  count = local.is_production ? 1 : 0

  replication_configuration {
    rule {
      destination {
        region      = var.failover_region
        registry_id = data.aws_caller_identity.current.account_id
      }

      # One filter per repo in local.ecr_repos, so adding a repo there
      # automatically extends replication — no hand-maintained list to
      # forget (a missed repo would be invisible until a DR recovery).
      dynamic "repository_filter" {
        for_each = local.ecr_repos
        content {
          filter      = "${local.name_prefix}-${repository_filter.value}-${local.env}"
          filter_type = "PREFIX_MATCH"
        }
      }
    }
  }
}

# Pre-create the DR repositories in the failover region so replicated
# images land in repos with the SAME posture as the source — IMMUTABLE
# tags, scan-on-push, and the shared lifecycle policy. Without this, ECR
# replication auto-creates the destination repos with DEFAULTS (mutable,
# no scan, unbounded retention), silently diverging the DR copy. Creating
# the repos up front is safe: replication pushes into the existing repos.
resource "aws_ecr_repository" "dr" {
  for_each = local.is_production ? toset(local.ecr_repos) : toset([])
  provider = aws.failover

  name                 = "${local.name_prefix}-${each.key}-${local.env}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${local.name_prefix}-${each.key}-${local.env}-dr"
  }
}

resource "aws_ecr_lifecycle_policy" "dr" {
  for_each   = aws_ecr_repository.dr
  provider   = aws.failover
  repository = each.value.name
  policy     = local.ecr_lifecycle_policy
}
