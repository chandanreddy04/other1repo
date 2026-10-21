# ECS web service — the FastAPI app running on Fargate behind the ALB.
#
# Image lifecycle:
# Terraform creates the FIRST task definition revision with a placeholder
# image, just so the service has something to launch. Subsequent deploys
# (deploy-aws.yml, PR 16) call `aws ecs register-task-definition` and
# `aws ecs update-service` to roll new revisions with real images.
# `lifecycle.ignore_changes = [task_definition]` on the service keeps
# Terraform from rolling the revision backwards on every apply.

locals {
  # AWS public hello-world image — same role as the placeholder in
  # bootstrap.sh. Replaced on first CD deploy. Public ECR has anonymous
  # pull rate limits; if multiple envs apply concurrently and pull this
  # image, expect occasional throttling. Doesn't matter once the first
  # CD push replaces it.
  placeholder_image = "public.ecr.aws/nginx/nginx:stable-alpine"

  # Sizing: 1 vCPU + 2 GB RAM.
  web_cpu    = 1024
  web_memory = 2048

  # AWS-specific env vars not covered by the manifest (cloud-target
  # decisions baked into the deploy). Combined with the manifest-driven
  # static vars below.
  web_aws_env_vars = [
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "SMS_FAILOVER_PROVIDER", value = "sns" },
    { name = "AWS_S3_BUCKET", value = aws_s3_bucket.photos.id },
    { name = "AWS_S3_REGION", value = var.region },
    { name = "AWS_SNS_REGION", value = var.region },
  ]
  # NOTE: DB_SSL_REQUIRE is set by the manifest's static block
  # (staging/production → "true"). RDS enforces TLS server-side via
  # rds.force_ssl=1 (rds.tf), and the app reads DB_SSL_REQUIRE to
  # set up its connect_args (ssl ctx for asyncpg, sslmode for
  # psycopg2 in app/db/session.py).

  # Manifest-driven static env vars — single source of truth for static
  # config. resolve_static() logic from infra/secrets/manifest.py:
  # the env-specific value (e.g., "staging") wins; otherwise "all".
  # Mirrors populate-secrets.sh's static handling.
  web_manifest_env_vars = [
    for entry in local._manifest.secrets :
    {
      name = entry.backend_env
      value = try(
        entry.static[var.environment_name],
        entry.static["all"],
      )
    }
    if try(entry.side, "") == "backend" &&
    try(entry.secret, false) == false &&
    try(entry.static, null) != null
  ]

  # Order matters: ECS Agent uses last-wins on duplicate env-var
  # entries, so the AWS-specific values (the cloud-tier source of
  # truth) come AFTER the manifest defaults and override them. Without
  # this, STORAGE_BACKEND, SMS_FAILOVER_PROVIDER, etc. could silently
  # revert to the manifest defaults instead of the AWS-tier values.
  web_env_vars = concat(local.web_manifest_env_vars, local.web_aws_env_vars)
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.name_prefix}-web-${local.env}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = local.web_cpu
  memory                   = local.web_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "web"
      image     = local.placeholder_image
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      environment = local.web_env_vars
      # Use the for_each key directly (= the secret name) rather than
      # looking up a tag — Terraform's default_tags merge can shadow
      # local tags, making s.tags["Secret"] fragile.
      secrets = [
        for k, s in aws_secretsmanager_secret.app : {
          name      = k
          valueFrom = s.arn
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.task["web"].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "web"
        }
      }
      # No container-level healthCheck. The ALB target group probes /health
      # already, which is the actual signal for "healthy enough to serve."
      # A container-level curl-based check would require curl in the image
      # (alpine doesn't ship it); the ALB check is sufficient.
    }
  ])

  # CD owns the deployed container_definitions: it registers a new revision
  # each deploy, injecting image + environment + secrets from the SSM spec
  # (aws_ssm_parameter.task_container_spec — TF is the single source, CD reads
  # it). Ignoring container_definitions here keeps TF's seed revision from
  # showing as a perpetual "must be replaced" diff against CD's real-image
  # revisions (that noise once hid a real RDS change), and lets env/secret
  # edits flow through a deploy instead of being stranded behind a full apply.
  # TF still owns the task-def shell (cpu/memory/roles/family/network_mode).
  lifecycle {
    ignore_changes = [container_definitions]
  }

  tags = {
    Name = "${local.name_prefix}-web-${local.env}"
  }
}

# Single source of truth for the container environment + secrets that CD
# injects into the web / worker / migrate task defs at deploy time (all three
# share the same env + secret set). Rendered by TF, read by CD via
# `aws ssm get-parameter` — no Terraform in the deploy pipeline. An env or
# secret change here becomes a clean, meaningful plan diff on THIS parameter
# and ships on the next deploy; the task defs themselves stay quiet.
locals {
  task_container_secrets = [
    for k, s in aws_secretsmanager_secret.app : { name = k, valueFrom = s.arn }
  ]
}

resource "aws_ssm_parameter" "task_container_spec" {
  name = "/madeithome/${local.env}/task-container-spec"
  type = "String"
  # Advanced tier: the full secrets list exceeds the 4 KB Standard limit.
  tier = "Advanced"
  value = jsonencode({
    environment = local.web_env_vars
    secrets     = local.task_container_secrets
  })

  tags = {
    Name = "${local.name_prefix}-task-container-spec-${local.env}"
  }
}

resource "aws_ecs_service" "web" {
  name            = "${local.name_prefix}-web-${local.env}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  launch_type     = "FARGATE"

  # Production runs at least 2 tasks across AZs for availability; staging
  # at 1 for cost. Autoscaling (defined below) ramps up under load.
  desired_count = var.environment_name == "production" ? 2 : 1

  # Rolling deploys: never below 100% capacity, allow 200% during the
  # swap. Capacity impact: prod runs 2 tasks, so a deploy peaks at 4 tasks
  # × 1 vCPU each. Well under the default account vCPU limit.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Auto-revert to the last-good task definition if a deploy's tasks fail to
  # stabilize, instead of hanging until the deploy step times out with a bad
  # image live (the migrate step has already run by then).
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.web_task.id]
    assign_public_ip = true # public subnets, no NAT — task egresses via IGW
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8000
  }

  # Give containers time to come up + register healthy before ECS
  # decides they're stuck.
  health_check_grace_period_seconds = 60

  lifecycle {
    # CD updates the service's task_definition via update-service.
    # TF managing this would race the deploy script. desired_count is
    # owned by autoscaling — to change the minimum task count, edit
    # aws_appautoscaling_target.web.min_capacity, NOT this attribute.
    ignore_changes = [task_definition, desired_count]
  }

  depends_on = [aws_lb_listener.https]

  tags = {
    Name = "${local.name_prefix}-web-${local.env}"
  }
}

# --- Autoscaling ---------------------------------------------------------
# Target tracking on CPU. Min/max bounded so a runaway scale-out can't
# explode the bill.

resource "aws_appautoscaling_target" "web" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.web.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.environment_name == "production" ? 2 : 1
  max_capacity       = 10
}

resource "aws_appautoscaling_policy" "web_cpu" {
  name               = "${local.name_prefix}-web-cpu-${local.env}"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.web.service_namespace
  resource_id        = aws_appautoscaling_target.web.resource_id
  scalable_dimension = aws_appautoscaling_target.web.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 60.0 # %CPU

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    # Scale-in slowly to avoid flapping after traffic spikes; scale-out
    # quickly to keep latency in check.
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
