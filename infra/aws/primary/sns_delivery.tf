# SNS SMS delivery pipeline.
#
# Flow: SNS publishes SMS → SNS writes delivery status to a CloudWatch
# Logs group → this Lambda subscribes to the log group → forwards each
# record to the backend's /webhooks/delivery/sns endpoint (PR 5).
#
# NOTE — account-level setup required:
# AWS configures SMS delivery status logging at the account level via
# `aws sns set-sms-attributes` (DeliveryStatusIAMRole +
# DeliveryStatusSuccessSamplingRate). That call writes to ONE role per
# region per account, so it's done manually by the operator once per
# account (see infra/aws/scripts/setup-sns-delivery-logging.sh, added
# in PR 13). Until that's run, the Lambda exists but no events flow.

# --- Log groups SNS writes to (account-level, single owner) -------------
#
# Names are fixed by AWS as account-level resources:
#   sns/{region}/{account}/DirectPublishToPhoneNumber[/Failure]
# Both staging and production publishes write to the SAME pair of log
# groups per region per account.
#
# These are NOT TF-managed: they're created (and retention/tags set)
# once per account+region by infra/aws/scripts/setup-sns-delivery-logging.sh,
# which bootstrap.sh preflights for. TF used to own them on the
# "production" stack and data-source them on staging, but that:
#   - forced production to be the first stack applied
#   - duplicate-created on a second account or region rollout
#   - left a `prevent_destroy` foot-gun
# Always-data-source is simpler and lets envs come up in any order.
locals {
  sns_sms_success_log_group_name = "sns/${var.region}/${data.aws_caller_identity.current.account_id}/DirectPublishToPhoneNumber"
  sns_sms_failure_log_group_name = "sns/${var.region}/${data.aws_caller_identity.current.account_id}/DirectPublishToPhoneNumber/Failure"
  # Referenced from rds.tf, ecr.tf, rds_backup_replication.tf to gate
  # prod-only resources (multi-AZ RDS, cross-region replication, etc.).
  is_production = var.environment_name == "production"
}

data "aws_cloudwatch_log_group" "sns_sms_success" {
  name = local.sns_sms_success_log_group_name
}

data "aws_cloudwatch_log_group" "sns_sms_failure" {
  name = local.sns_sms_failure_log_group_name
}

locals {
  sns_sms_success_log_group_arn = data.aws_cloudwatch_log_group.sns_sms_success.arn
  sns_sms_failure_log_group_arn = data.aws_cloudwatch_log_group.sns_sms_failure.arn
}

# Subscription filter ceiling: CloudWatch Logs allows at most 2
# subscription filters per log group. Staging + production fills the
# quota in any single account+region. The failover region (PR 14) uses
# its own per-region log groups, so its filter doesn't count here.
# Adding a third env (e.g., a sandbox) would require collapsing one of
# the existing filters to a fan-out Lambda.

# --- Lambda code package -------------------------------------------------
locals {
  sns_bridge_src = "${path.module}/lambda/sns_delivery_bridge"
  # CONTENT hash (mtime-independent). The zip's own byte hash
  # (archive_file.output_base64sha256) embeds each file's mtime, so a fresh
  # git checkout on another machine / CI produces a different hash for
  # identical code — phantom "Lambda will be updated" drift on every plan.
  # Hashing file contents instead makes the change signal deterministic.
  sns_bridge_code_hash = base64sha256(join("", [
    for f in sort(tolist(fileset(local.sns_bridge_src, "**"))) :
    filesha256("${local.sns_bridge_src}/${f}")
  ]))
}

data "archive_file" "sns_bridge" {
  type        = "zip"
  source_dir  = local.sns_bridge_src
  output_path = "${path.module}/.terraform/lambda-sns-delivery-bridge.zip"
}

# --- Lambda IAM ----------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sns_bridge" {
  # Region in name: IAM is account-wide, so this avoids collision if the
  # stack is ever applied in a second region (e.g. a DR rebuild).
  name               = "${local.name_prefix}-sns-bridge-${var.region}-${local.env}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Name = "${local.name_prefix}-sns-bridge-${local.env}"
  }
}

# Basic execution (CloudWatch Logs write for the Lambda's own logs).
resource "aws_iam_role_policy_attachment" "sns_bridge_basic" {
  role       = aws_iam_role.sns_bridge.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Read the HMAC shared secret from Secrets Manager. Scoped to the one
# secret the Lambda needs.
data "aws_iam_policy_document" "sns_bridge_secret" {
  statement {
    sid       = "ReadWebhookSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app["AWS_SNS_DELIVERY_WEBHOOK_SECRET"].arn]
  }
}

resource "aws_iam_role_policy" "sns_bridge_secret" {
  name   = "read-webhook-secret"
  role   = aws_iam_role.sns_bridge.id
  policy = data.aws_iam_policy_document.sns_bridge_secret.json
}

# --- Lambda function -----------------------------------------------------
resource "aws_cloudwatch_log_group" "sns_bridge" {
  name              = "/aws/lambda/${local.name_prefix}-sns-bridge-${local.env}"
  retention_in_days = local.log_retention_days
}

resource "aws_lambda_function" "sns_bridge" {
  function_name = "${local.name_prefix}-sns-bridge-${local.env}"
  role          = aws_iam_role.sns_bridge.arn
  runtime       = "python3.12"
  handler       = "handler.handler"

  filename         = data.archive_file.sns_bridge.output_path
  source_code_hash = local.sns_bridge_code_hash

  timeout     = 30
  memory_size = 256

  # Cap concurrent executions. SNS subscription filters can fire many
  # events per minute at scale; uncapped concurrency means runaway cost
  # under unexpected traffic.
  #
  # Defaults to -1 (no reservation) because a brand-new AWS account ships
  # with a total Lambda concurrency limit of 10, and AWS forbids any
  # reservation that drops the unreserved pool below 10 — so NO positive
  # value applies on a fresh account. Once the account's "Concurrent
  # executions" Service Quota is raised above 10, set a positive cap via
  # -var "sns_bridge_reserved_concurrency=10".
  reserved_concurrent_executions = var.sns_bridge_reserved_concurrency

  environment {
    variables = {
      # BACKEND_WEBHOOK_URL hits the PUBLIC ALB via the Cloudflare CNAME.
      # This means the SNS pipeline only activates after the operator has
      # validated the ACM cert AND pointed the CNAME at the ALB. Until
      # then, Lambda invocations error and CloudWatch Logs retries them.
      BACKEND_WEBHOOK_URL = "https://${local.app_domain}/webhooks/delivery/sns"
      WEBHOOK_SECRET_ARN  = aws_secretsmanager_secret.app["AWS_SNS_DELIVERY_WEBHOOK_SECRET"].arn
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.sns_bridge,
    aws_iam_role_policy_attachment.sns_bridge_basic,
  ]

  tags = {
    Name = "${local.name_prefix}-sns-bridge-${local.env}"
  }
}

# --- CW Logs subscription filters ---------------------------------------
# One per delivery-status log group (success + failure). CW Logs invokes
# Lambda with batched events.

resource "aws_lambda_permission" "allow_cw_logs_success" {
  statement_id  = "AllowCloudWatchLogsSuccess"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sns_bridge.function_name
  principal     = "logs.amazonaws.com"
  source_arn    = "${local.sns_sms_success_log_group_arn}:*"
}

resource "aws_lambda_permission" "allow_cw_logs_failure" {
  statement_id  = "AllowCloudWatchLogsFailure"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sns_bridge.function_name
  principal     = "logs.amazonaws.com"
  source_arn    = "${local.sns_sms_failure_log_group_arn}:*"
}

resource "aws_cloudwatch_log_subscription_filter" "sns_success" {
  name            = "${local.name_prefix}-sns-success-${local.env}"
  log_group_name  = local.sns_sms_success_log_group_name
  filter_pattern  = "" # all events
  destination_arn = aws_lambda_function.sns_bridge.arn
  depends_on      = [aws_lambda_permission.allow_cw_logs_success]
}

resource "aws_cloudwatch_log_subscription_filter" "sns_failure" {
  name            = "${local.name_prefix}-sns-failure-${local.env}"
  log_group_name  = local.sns_sms_failure_log_group_name
  filter_pattern  = ""
  destination_arn = aws_lambda_function.sns_bridge.arn
  depends_on      = [aws_lambda_permission.allow_cw_logs_failure]
}
