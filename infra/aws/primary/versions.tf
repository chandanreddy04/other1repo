# Terraform + provider versions and remote backend wiring.
#
# The backend `bucket` value is constructed AT INIT time using the same
# naming convention as state-bootstrap/main.tf:
#   madeithome-tfstate-{env}-{account_id}
# Because backend config blocks can't reference variables/data sources, the
# operator passes the bucket name in via `-backend-config` at init:
#
#   cd infra/aws/primary
#   ACCT=$(aws sts get-caller-identity --query Account --output text)
#   terraform init \
#     -backend-config="bucket=madeithome-tfstate-staging-$ACCT" \
#     -backend-config="dynamodb_table=madeithome-tfstate-lock-staging" \
#     -backend-config="key=primary/terraform.tfstate" \
#     -backend-config="region=us-west-2"
#
# `encrypt = true` below makes Terraform encrypt the state object using
# the bucket's default SSE — which is AES256 per state-bootstrap/main.tf.
# To upgrade to KMS later, change the bucket's encryption config AND set
# `kms_key_id` in the backend block here.
#
# The bootstrap script (PR 13) wraps the whole init invocation.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
  backend "s3" {
    # All fields supplied via -backend-config — see comment above.
    encrypt = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "made-it-home"
      Environment = var.environment_name
      ManagedBy   = "terraform"
      Stack       = "primary"
      # Track who/where the resource came from in console listings.
      Repository = "made-it-home"
    }
  }
}

# Aliased provider for the failover region (us-east-2). Used only by the
# production cross-region automated-backup replication in
# rds_backup_replication.tf. Declaring it is harmless for staging (no
# resources reference it there), so no us-east-2 API calls are made on a
# staging plan/apply.
provider "aws" {
  alias  = "failover"
  region = var.failover_region

  default_tags {
    tags = {
      Project     = "made-it-home"
      Environment = var.environment_name
      ManagedBy   = "terraform"
      Stack       = "primary-dr"
      Repository  = "made-it-home"
    }
  }
}

# Data sources used by multiple .tf files in this stack live in data.tf.
