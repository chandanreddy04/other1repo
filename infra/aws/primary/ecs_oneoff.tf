# Manual one-off task definitions.
#
# Two transient workloads, each a separate task definition family so
# `aws ecs run-task` calls reference them by name:
#
#   - migrate: runs `alembic upgrade head` against the app DB. CD
#     (deploy-aws.yml in PR 16) starts a migrate task BEFORE swapping
#     the web service image so new code never serves against an
#     un-migrated schema.
#
#   - db-init: runs scripts/init_db.py to create the least-priv app
#     role + database on the RDS instance, using the RDS-managed
#     master credentials. One-time per environment, invoked manually
#     by infra/aws/scripts/init-db.sh (PR 13).
#
# Both share the worker_task SG (egress + RDS ingress).

# --- migrate -------------------------------------------------------------
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name_prefix}-migrate-${local.env}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = local.placeholder_image
      essential = true
      # alembic upgrade head — env vars + DB connection come from the
      # same secrets as the web service (DATABASE_URL etc.).
      command     = ["alembic", "upgrade", "head"]
      environment = local.web_env_vars
      secrets = [
        for k, s in aws_secretsmanager_secret.app : {
          name      = k
          valueFrom = s.arn
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.task["migrate"].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "migrate"
        }
      }
    }
  ])

  # CD owns the deployed container_definitions (image + env + secrets from the
  # SSM spec) — see aws_ecs_task_definition.web for the rationale. The migrate
  # step in deploy-aws.yml injects the same spec before running the task.
  lifecycle {
    ignore_changes = [container_definitions]
  }

  tags = {
    Name = "${local.name_prefix}-migrate-${local.env}"
  }
}

# --- db-init -------------------------------------------------------------
# Runs scripts/init_db.py to create the least-priv app role + database.
#
# Runtime contract: ADMIN_DSN, APP_ROLE, APP_PASSWORD, APP_DB MUST be
# provided at run time. They are NOT in the task definition because
# (a) ADMIN_DSN is constructed from the RDS-managed master secret
# (which TF doesn't synthesize into a DSN string), and (b) the app
# role credentials live in the operator's hands at first init.
#
# infra/aws/scripts/init-db.sh (PR 13) supplies them via
# `aws ecs run-task --overrides '{"containerOverrides":[{"environment":[...]}]}'`.
# Running this task without that wrapper fails fast with a missing-env
# error — that's the intended fail-loud behavior.
resource "aws_ecs_task_definition" "db_init" {
  family                   = "${local.name_prefix}-db-init-${local.env}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "db-init"
      image     = local.placeholder_image
      essential = true
      command   = ["python", "scripts/init_db.py"]
      # Minimal static env. ADMIN_DSN, APP_ROLE, APP_PASSWORD, APP_DB
      # are injected at run time by init-db.sh — see file header.
      environment = [
        { name = "ENVIRONMENT", value = var.environment_name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.task["db-init"].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "db-init"
        }
      }
    }
  ])

  tags = {
    Name = "${local.name_prefix}-db-init-${local.env}"
  }
}
