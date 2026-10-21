# Inputs for the primary-region stack. All env-scoping flows through
# `environment_name` — see infra/aws/README.md for the convention.

variable "environment_name" {
  type        = string
  description = "Deploy environment — 'staging' or 'production'. Embedded in every resource name. No default — apply must pass -var explicitly."
  validation {
    condition     = contains(["staging", "production"], var.environment_name)
    error_message = "environment_name must be 'staging' or 'production'."
  }
}

variable "region" {
  type        = string
  description = "AWS region for this stack."
  default     = "us-west-2"
}

variable "failover_region" {
  type        = string
  description = "Destination region for cross-region DR data replication: Secrets Manager replicas, RDS automated-backup replication, and ECR image replication (backup-only DR, docs/dr-runbook-aws.md). MUST match state-bootstrap's var.failover_region — all replicated data must land in one region."
  default     = "us-east-2"
}

variable "sns_bridge_reserved_concurrency" {
  type        = number
  description = "Reserved concurrent executions for the SNS delivery-bridge Lambda. -1 = no reservation (required on fresh accounts whose total Lambda concurrency quota is the default 10, since AWS forbids dropping the unreserved pool below 10). Set a positive cap only after raising the account's Concurrent-executions Service Quota."
  default     = -1
  validation {
    condition     = var.sns_bridge_reserved_concurrency == -1 || var.sns_bridge_reserved_concurrency >= 1
    error_message = "sns_bridge_reserved_concurrency must be -1 (unreserved) or a positive integer."
  }
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC."
  # Convention: primary region uses 10.20.0.0/16; 10.30.0.0/16 stays
  # reserved for a DR rebuild in the failover region (docs/dr-runbook-aws.md)
  # so primary↔failover VPC peering stays possible during failback.
  default = "10.20.0.0/16"
}

# Per-AZ subnet sizing. We take the first two AZs returned by
# data.aws_availability_zones (sorted by name, stable per-region) so the
# subnet→AZ binding is deterministic across applies.
variable "public_subnet_cidrs" {
  type        = list(string)
  description = "Public subnet CIDRs, one per AZ. Hosts ALB + Fargate tasks (with assign_public_ip + tight SGs)."
  default     = ["10.20.0.0/24", "10.20.1.0/24"]
  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Must provide exactly 2 public subnet CIDRs (2 AZs)."
  }
}

variable "private_subnet_cidrs" {
  type        = list(string)
  description = "Private subnet CIDRs, one per AZ. Hosts RDS (and any future internal-only resource)."
  default     = ["10.20.10.0/24", "10.20.11.0/24"]
  validation {
    condition     = length(var.private_subnet_cidrs) == 2
    error_message = "Must provide exactly 2 private subnet CIDRs (2 AZs)."
  }
}

variable "alert_email" {
  description = "Email subscribed to the CloudWatch alerts SNS topic (alarms.tf). Empty disables the email subscription; the topic is still created so other subscribers can be attached."
  type        = string
  default     = ""
}

locals {
  name_prefix = "madeithome"
  # Resources follow `{name_prefix}-{resource}-{env}` per the convention.
  env = var.environment_name
  # data.aws_availability_zones is declared in data.tf.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}
