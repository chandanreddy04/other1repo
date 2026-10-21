# Cross-region replication of the Terraform STATE bucket — PRODUCTION only.
#
# WHY: the state bucket lives in us-west-2. In a region-loss disaster
# (docs/dr-runbook-aws.md) you need Terraform state readable from the
# failover region to rebuild infrastructure there. This replicates the
# production state bucket to us-east-2 continuously.
#
# Production-gated (like the rest of the DR posture): staging keeps a
# single regional state bucket — its loss is recoverable from operator
# backups and it isn't part of the production recovery path.
#
# Source encryption is SSE-S3 (AES256), not KMS, so replication needs no
# KMS grant/criteria — the destination simply re-encrypts with its own
# SSE-S3. State objects are tiny (KB), so storage + transfer cost is
# negligible.

variable "failover_region" {
  type        = string
  description = "Destination region for state-bucket replication. MUST match the primary stack's var.failover_region — Terraform state, RDS backups, and ECR images all replicate to the SAME region, and a region-loss recovery assumes they are co-located there. The two stacks hold separate state so this can't be one shared variable; keep them in sync (same name is the reminder)."
  default     = "us-east-2"
}

locals {
  replicate = var.environment_name == "production"
}

# Destination-region provider. Declared unconditionally (harmless — no
# resources reference it unless replicate is true), so a staging apply
# makes no us-east-2 calls. default_tags so the DR state bucket + role
# carry the same Project/Environment/ManagedBy tags as everything else.
provider "aws" {
  alias  = "dr"
  region = var.failover_region

  default_tags {
    tags = {
      Project     = "made-it-home"
      Environment = var.environment_name
      ManagedBy   = "terraform"
      Stack       = "state-bootstrap-dr"
      Repository  = "made-it-home"
    }
  }
}

# --- Destination bucket (us-east-2) --------------------------------------
resource "aws_s3_bucket" "tfstate_dr" {
  count    = local.replicate ? 1 : 0
  provider = aws.dr
  bucket   = "${local.bucket_name}-dr"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate_dr" {
  count    = local.replicate ? 1 : 0
  provider = aws.dr
  bucket   = aws_s3_bucket.tfstate_dr[0].id
  versioning_configuration {
    status = "Enabled" # CRR requires versioning on BOTH source and destination
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate_dr" {
  count    = local.replicate ? 1 : 0
  provider = aws.dr
  bucket   = aws_s3_bucket.tfstate_dr[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate_dr" {
  count                   = local.replicate ? 1 : 0
  provider                = aws.dr
  bucket                  = aws_s3_bucket.tfstate_dr[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- Replication IAM role (S3 assumes this to copy objects) --------------
data "aws_iam_policy_document" "replication_assume" {
  count = local.replicate ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "replication" {
  count              = local.replicate ? 1 : 0
  name               = "madeithome-tfstate-replication-${var.environment_name}"
  assume_role_policy = data.aws_iam_policy_document.replication_assume[0].json
}

data "aws_iam_policy_document" "replication" {
  count = local.replicate ? 1 : 0

  statement {
    sid       = "SourceBucketRead"
    actions   = ["s3:GetReplicationConfiguration", "s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn]
  }
  statement {
    sid = "SourceObjectsRead"
    actions = [
      "s3:GetObjectVersionForReplication",
      "s3:GetObjectVersionAcl",
      "s3:GetObjectVersionTagging",
    ]
    resources = ["${aws_s3_bucket.tfstate.arn}/*"]
  }
  statement {
    sid = "DestinationReplicate"
    actions = [
      "s3:ReplicateObject",
      "s3:ReplicateDelete",
      "s3:ReplicateTags",
    ]
    resources = ["${aws_s3_bucket.tfstate_dr[0].arn}/*"]
  }
}

resource "aws_iam_role_policy" "replication" {
  count  = local.replicate ? 1 : 0
  name   = "replication"
  role   = aws_iam_role.replication[0].id
  policy = data.aws_iam_policy_document.replication[0].json
}

# --- Replication configuration on the SOURCE bucket ----------------------
resource "aws_s3_bucket_replication_configuration" "tfstate" {
  count  = local.replicate ? 1 : 0
  role   = aws_iam_role.replication[0].arn
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "tfstate-to-dr"
    status = "Enabled"

    filter {} # replicate all objects

    delete_marker_replication {
      status = "Enabled"
    }

    destination {
      bucket        = aws_s3_bucket.tfstate_dr[0].arn
      storage_class = "STANDARD"
    }
  }

  # Replication config requires versioning to already exist on both buckets.
  depends_on = [
    aws_s3_bucket_versioning.tfstate,
    aws_s3_bucket_versioning.tfstate_dr,
  ]
}
