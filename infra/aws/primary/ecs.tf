# ECS cluster (Fargate) — hosts the web service (PR 10), worker
# scheduled task (PR 11), and one-off migrate / db-init tasks (PR 11).
#
# Single cluster per env. Fargate-only (no EC2 capacity providers) for
# cost simplicity.

resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster-${local.env}"

  # Container Insights ingests CPU/mem/network metrics into CloudWatch
  # at ~$0.50/GB-month. Always-on for production so we have data when an
  # incident happens; disabled in staging to save cost since no one
  # actively watches the dashboards there.
  setting {
    name  = "containerInsights"
    value = var.environment_name == "production" ? "enabled" : "disabled"
  }

  tags = {
    Name = "${local.name_prefix}-cluster-${local.env}"
  }
}

# Default capacity providers — Fargate (always-on) and Fargate Spot
# (cheaper but interruptible). The web service uses 100% on-demand
# Fargate for guaranteed availability; the worker scheduled task
# (PR 11) can override to Fargate Spot if interruptions are tolerable.
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}
