# Terraform remote state bootstrap for the AWS deploy path.
#
# This is a small, standalone stack that provisions the S3 bucket and
# DynamoDB lock table used as the backend for every OTHER Terraform stack
# under infra/aws/. It uses LOCAL state (chicken-and-egg: you can't store
# the state bucket's own state inside the state bucket).
#
# Run ONCE per account, then never touch again. See README.md for the
# one-time bootstrap procedure.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
  # NOTE: no `backend` block — this stack uses local state on purpose.
}

provider "aws" {
  region = var.region
}

# Account ID is appended to the bucket name to guarantee global uniqueness
# (S3 bucket names are unique across all AWS accounts) without requiring
# the operator to invent a suffix.
data "aws_caller_identity" "current" {}

variable "region" {
  type        = string
  description = "AWS region for the state bucket and lock table."
  default     = "us-west-2"
}

variable "environment_name" {
  type        = string
  description = "Deploy environment — must be 'staging' or 'production'. Embedded in every resource name so prod and staging can coexist in one account without ambiguity. No default — apply must pass -var explicitly so a hurried run can't silently target the wrong env."
  validation {
    condition     = contains(["staging", "production"], var.environment_name)
    error_message = "environment_name must be 'staging' or 'production'."
  }
}

locals {
  # Explicit env in every name so prod and staging are unambiguous even
  # when both live in the same account. Account ID suffix on the bucket
  # name guards against S3's global namespace; the DynamoDB table is
  # per-region per-account so it doesn't need it.
  bucket_name = "madeithome-tfstate-${var.environment_name}-${data.aws_caller_identity.current.account_id}"
  table_name  = "madeithome-tfstate-lock-${var.environment_name}"
}

# --- State bucket ---------------------------------------------------------
resource "aws_s3_bucket" "tfstate" {
  bucket = local.bucket_name

  # Loud failure if someone tries to destroy this stack — losing state is
  # catastrophic. To intentionally tear down an environment, comment out
  # this block, apply, then destroy.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 (AES256) over SSE-KMS is an accepted trade-off: state files contain
# every secret Terraform ever sees, but they also live in a private bucket
# with no public access and IAM-gated reads. KMS adds an additional
# rotation/audit layer at the cost of a per-call charge and a key to manage.
# Upgrade to `aws:kms` with a customer-managed key if/when an auditor or
# compliance regime requires it.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- State lock table -----------------------------------------------------
# Pay-per-request — locks are short-lived and infrequent; provisioned
# capacity would waste money.
resource "aws_dynamodb_table" "tfstate_lock" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  # PITR: cheap insurance (~$0.20/GB-month; the table is tiny). Lets us
  # restore the lock table if it's accidentally truncated or corrupted.
  point_in_time_recovery {
    enabled = true
  }

  # Explicit even though DynamoDB encrypts by default with an AWS-owned key —
  # makes intent visible to auditors who don't know the default.
  server_side_encryption {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

# --- Outputs (used as the backend config in sibling stacks) ---------------
output "state_bucket" {
  value       = aws_s3_bucket.tfstate.id
  description = "Name of the S3 bucket holding Terraform state."
}

output "lock_table" {
  value       = aws_dynamodb_table.tfstate_lock.name
  description = "Name of the DynamoDB table used for state locking."
}

output "region" {
  value       = var.region
  description = "Region of the state bucket and lock table."
}
