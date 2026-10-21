# CloudWatch Log groups for ECS tasks.
#
# One log group per task family. ECS task definitions in PR 10/11 use
# awslogs driver pointed at these groups; container stdout/stderr →
# CloudWatch Logs.

locals {
  log_groups = [
    "web",     # the FastAPI web service (PR 10)
    "worker",  # the every-minute worker tick (PR 11)
    "migrate", # alembic upgrade one-off (PR 11)
    "db-init", # least-priv app role provisioning (PR 11)
  ]

  # Production keeps 30 days for incident forensics; staging is cheaper.
  log_retention_days = var.environment_name == "production" ? 30 : 14
}

resource "aws_cloudwatch_log_group" "task" {
  for_each = toset(local.log_groups)

  name              = "/${local.name_prefix}/${local.env}/${each.key}"
  retention_in_days = local.log_retention_days

  tags = {
    Name = "${local.name_prefix}-${each.key}-logs-${local.env}"
  }
}
