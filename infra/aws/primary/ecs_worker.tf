# Worker — a long-lived ECS service running `python worker_loop.py`, which
# ticks on a warm ~60s cadence. This replaced the earlier EventBridge
# Scheduler → RunTask (one cold Fargate task per minute): a notification due
# at T waited on a ~20-60s cold start, so it went out well after T. The warm
# loop dispatches due work within seconds of the minute boundary.
#
# Overlap protection: run_tick_with_lock acquires a Postgres session-level
# advisory lock, so a rolling deploy's old+new task (or any stray tick) safely
# no-op each other — desired_count is 1, but correctness never depends on it.
# The tick still emits "tick complete"; the log-metric heartbeat alarm
# (alarms.tf) is unchanged. worker_tick.py stays for the migrate one-off,
# manual runs, and as the rollback entrypoint.

# --- Worker task SG ------------------------------------------------------
resource "aws_security_group" "worker_task" {
  name        = "${local.name_prefix}-worker-task-${local.env}"
  description = "Worker / migrate / db-init Fargate tasks - egress only"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-worker-task-${local.env}"
  }
}

resource "aws_vpc_security_group_egress_rule" "worker_task_all" {
  security_group_id = aws_security_group.worker_task.id
  description       = "All egress (RDS + AWS APIs + Twilio/Stripe)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# RDS ingress from the worker SG — same pattern as the web task SG rule.
resource "aws_vpc_security_group_ingress_rule" "rds_from_worker_task" {
  security_group_id            = aws_security_group.rds.id
  description                  = "Postgres from worker / migrate / db-init tasks"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.worker_task.id
}

# --- Worker task definition ----------------------------------------------
# Smaller than the web task — the tick is short and doesn't hold memory.
locals {
  worker_cpu    = 512
  worker_memory = 1024
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker-${local.env}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = local.worker_cpu
  memory                   = local.worker_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name        = "worker"
      image       = local.placeholder_image
      essential   = true
      command     = ["python", "worker_loop.py"]
      environment = local.web_env_vars # same env as web — same image, different entrypoint
      secrets = [
        for k, s in aws_secretsmanager_secret.app : {
          name      = k
          valueFrom = s.arn
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.task["worker"].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "worker"
        }
      }
    }
  ])

  # CD owns the deployed container_definitions (image + env + secrets from the
  # SSM spec) — see aws_ecs_task_definition.web for the rationale.
  lifecycle {
    ignore_changes = [container_definitions]
  }

  tags = {
    Name = "${local.name_prefix}-worker-${local.env}"
  }
}

# --- Worker service (always-on warm loop) --------------------------------

resource "aws_ecs_service" "worker" {
  name            = "${local.name_prefix}-worker-${local.env}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  launch_type     = "FARGATE"

  # Exactly one warm ticker. The advisory lock makes >1 safe, but a single
  # task is all the workload needs; a rolling deploy briefly runs 2 (old +
  # new), which the lock serializes.
  desired_count = 1

  # Rolling deploy: keep the old task ticking until the new one is up, then
  # drain the old. minimum_healthy 0 would let ECS stop the only task first
  # and leave a no-worker gap; 100% avoids that (peaks at 2 during the swap).
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # A crash-looping worker image (bad deploy) auto-reverts to the last-good
  # task def instead of leaving alert dispatch down until someone notices.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.worker_task.id]
    assign_public_ip = true # public subnets, no NAT — task egresses via IGW
  }

  lifecycle {
    # CD owns the running task_definition (register + update-service with the
    # real image); TF only seeds the service with the placeholder revision.
    # desired_count stays TF-owned at 1 (no autoscaling on the worker).
    ignore_changes = [task_definition]
  }

  tags = {
    Name = "${local.name_prefix}-worker-${local.env}"
  }
}
