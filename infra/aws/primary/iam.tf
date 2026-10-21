# IAM roles for ECS tasks.
#
# Two roles per task definition:
#   - Task execution role: used by the ECS agent to set the task up
#     (pull image from ECR, fetch secrets, ship logs to CloudWatch).
#     Same role works for every task in the cluster.
#   - Task role: assumed by the application code itself (the running
#     container's AWS SDK calls). Scopes what the app can do at runtime
#     (S3 read/write on photos, SNS publish).

# --- Task execution role (cluster-wide) ----------------------------------
data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  # IAM role names are account-wide. Region is included so the failover
  # stack (PR 14) doesn't collide on apply when both stacks live in the
  # same account.
  name               = "${local.name_prefix}-task-exec-${var.region}-${local.env}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = {
    Name = "${local.name_prefix}-task-exec-${local.env}"
  }
}

# AWS-managed policy covers ECR pull + CloudWatch Logs write — the
# standard baseline.
resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Read every backend secret from Secrets Manager. Scoped to just the
# secrets we provisioned — no wildcards.
#
# Design note: this grant is on the EXECUTION role (used at task launch
# by the ECS agent), not the runtime task role. ECS task definitions
# inject secrets as env vars via the `secrets` block — the agent reads
# them, then starts the container with the values already in os.environ.
# That means the application never needs Secrets Manager access at
# runtime; everything it needs is pre-injected. The db-init task (PR 11)
# uses the same pattern to receive the RDS master password.
data "aws_iam_policy_document" "task_execution_secrets" {
  statement {
    sid     = "ReadAppSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [for s in aws_secretsmanager_secret.app : s.arn],
      # The RDS-managed master secret — db-init task definition (PR 11)
      # injects it as an ADMIN_DSN env var via the `secrets` block.
      [aws_db_instance.main.master_user_secret[0].secret_arn],
    )
  }
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name   = "secrets-read"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution_secrets.json
}

# --- Task role (application runtime) -------------------------------------
resource "aws_iam_role" "task" {
  # Region in name: IAM is account-wide, so this avoids collision if the
  # stack is ever applied in a second region (e.g. a DR rebuild).
  name               = "${local.name_prefix}-task-${var.region}-${local.env}"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = {
    Name = "${local.name_prefix}-task-${local.env}"
  }
}

# Photos bucket — read/write/delete on objects within the bucket.
data "aws_iam_policy_document" "task_s3" {
  statement {
    sid       = "PhotosObjectAccess"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.photos.arn}/*"]
  }
  # ListBucket on the bucket itself — used by presigned URL generation
  # for HEAD-style existence checks. Scoped to bucket, not contents.
  statement {
    sid       = "PhotosListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.photos.arn]
  }
}

resource "aws_iam_role_policy" "task_s3" {
  name   = "s3-photos"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_s3.json
}

# SNS publish — used by sms_sns._SNSBackend.send_sms. Direct phone
# publishes can't be scoped to specific phone-number ARNs (they don't
# exist as resources), so the resource scope is "*" but the action is
# narrow.
#
# Known gap: a tighter aws:SourceVpce condition would prevent stolen task
# creds from publishing outside our VPC, but that requires a VPC endpoint
# for SNS (~$7/mo per AZ). Not worth it at current scale; revisit if a
# credential-leak threat model emerges.
data "aws_iam_policy_document" "task_sns" {
  statement {
    sid       = "PublishSMS"
    actions   = ["sns:Publish"]
    resources = ["*"]
    # Defense-in-depth: SNS supports a condition on the publish target.
    # Lock down to the regions we use so a compromised task can't fan
    # out to unexpected regions.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [var.region]
    }
  }
}

resource "aws_iam_role_policy" "task_sns" {
  name   = "sns-publish"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_sns.json
}
