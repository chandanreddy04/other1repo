# Outputs consumed by sibling stacks (failover/) and by populate-secrets.sh
# (which reads them to push real resource names into Secrets Manager).
#
# More outputs land in PRs 8-12 as the corresponding resources are added
# (RDS endpoint, ECR repo URLs, ALB DNS, etc.).

output "vpc_id" {
  value       = aws_vpc.main.id
  description = "ID of the primary-region VPC."
}

output "vpc_cidr" {
  value       = aws_vpc.main.cidr_block
  description = "CIDR block of the primary-region VPC."
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "Public subnet IDs (ALB + Fargate tasks)."
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Private subnet IDs (RDS)."
}

output "availability_zones" {
  value       = local.azs
  description = "The two AZs this stack uses, indexed to match subnet ordering."
}

# --- Data layer (PR 8) ---------------------------------------------------

output "rds_endpoint" {
  value       = aws_db_instance.main.endpoint
  description = "RDS Postgres endpoint as host:port. Convenience; for separate consumption see rds_host / rds_port."
}

output "rds_host" {
  value       = aws_db_instance.main.address
  description = "RDS Postgres hostname (no port). Used by populate-secrets.sh to construct DATABASE_URL."
}

output "rds_port" {
  value       = aws_db_instance.main.port
  description = "RDS Postgres port. Always 5432 here; output so the script doesn't have to assume."
}

output "rds_admin_secret_arn" {
  # RDS-managed: created automatically by manage_master_user_password=true
  # in rds.tf. AWS handles rotation. init-db.sh reads from this secret.
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
  description = "ARN of the RDS-managed Secrets Manager secret holding the master (mihadmin) password. Read by init-db.sh."
  sensitive   = true
}

output "rds_security_group_id" {
  value       = aws_security_group.rds.id
  description = "RDS security group ID. ECS task SG (PR 9/10) adds an ingress rule to this SG."
}

output "photos_bucket" {
  value       = aws_s3_bucket.photos.id
  description = "S3 photo bucket name. Pushed to AWS_S3_BUCKET in Secrets Manager by populate-secrets.sh."
}

output "app_secret_arns" {
  value       = { for k, v in aws_secretsmanager_secret.app : k => v.arn }
  description = "Map of secret name → ARN. Consumed by ECS task definitions (PR 10) for env var injection."
  sensitive   = true
}

# --- Compute foundation (PR 9) -------------------------------------------

output "ecr_web_repo_url" {
  value       = aws_ecr_repository.app["web"].repository_url
  description = "ECR repo URL for the web image. Used by deploy-aws.yml (PR 16) as the docker push target."
}

output "ecr_worker_repo_url" {
  value       = aws_ecr_repository.app["worker"].repository_url
  description = "ECR repo URL for the worker image."
}

output "ecs_cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "ECS cluster name. Consumed by the web + worker services + one-off task definitions."
}

output "ecs_task_execution_role_arn" {
  value       = aws_iam_role.task_execution.arn
  description = "IAM role ARN for ECS task execution (image pull, log shipping, secret injection)."
}

output "ecs_task_role_arn" {
  value       = aws_iam_role.task.arn
  description = "IAM role ARN assumed by the running container (S3 + SNS access)."
}

output "log_group_names" {
  value       = { for k, v in aws_cloudwatch_log_group.task : k => v.name }
  description = "Map of task name → CloudWatch log group. Consumed by task definitions' awslogs config."
}

# --- Web service + ALB (PR 10) ------------------------------------------

output "alb_dns_name" {
  value       = aws_lb.web.dns_name
  description = "ALB DNS name. Cloudflare CNAME for the app domain points here."
}

output "alb_zone_id" {
  value       = aws_lb.web.zone_id
  description = "ALB hosted zone ID. Needed for Route53 ALIAS records (currently unused — Cloudflare CNAME)."
}

output "app_domain" {
  value       = local.app_domain
  description = "Public app domain for this env. Cloudflare CNAME for this name should point at alb_dns_name."
}

output "acm_certificate_arn" {
  value       = aws_acm_certificate.app.arn
  description = "ACM certificate ARN. PENDING_VALIDATION until the operator adds the DNS validation CNAME to Cloudflare."
}

output "acm_validation_records" {
  value = {
    for dvo in aws_acm_certificate.app.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }
  description = "DNS validation records the operator must add to Cloudflare to validate the ACM certificate."
}

output "ecs_web_service_name" {
  value       = aws_ecs_service.web.name
  description = "Web ECS service name. Used by deploy-aws.yml to roll new task-definition revisions."
}

output "web_task_definition_family" {
  value       = aws_ecs_task_definition.web.family
  description = "Task definition family — deploy-aws.yml registers new revisions under this family."
}

# --- Worker + one-off tasks (PR 11) -------------------------------------

output "worker_task_definition_family" {
  value       = aws_ecs_task_definition.worker.family
  description = "Worker task definition family. CD registers new revisions under this family and update-services the worker with them."
}

output "ecs_worker_service_name" {
  value       = aws_ecs_service.worker.name
  description = "Worker ECS service name (always-on warm loop). Used by deploy-aws.yml to roll new task-definition revisions."
}

output "migrate_task_definition_family" {
  value       = aws_ecs_task_definition.migrate.family
  description = "Migrate task definition family. deploy-aws.yml runs this BEFORE swapping the web image."
}

output "db_init_task_definition_family" {
  value       = aws_ecs_task_definition.db_init.family
  description = "DB-init task family. infra/aws/scripts/init-db.sh runs this once per env."
}

output "worker_task_security_group_id" {
  value       = aws_security_group.worker_task.id
  description = "Security group used by worker / migrate / db-init tasks. Scripts pass this to `aws ecs run-task --network-configuration`."
}

# --- SNS delivery pipeline (PR 12) --------------------------------------

output "sns_bridge_lambda_arn" {
  value       = aws_lambda_function.sns_bridge.arn
  description = "Lambda that forwards SNS SMS delivery events to the backend webhook."
}

output "sns_bridge_lambda_name" {
  value       = aws_lambda_function.sns_bridge.function_name
  description = "Lambda function name. Useful for ad-hoc invocation in incident debugging."
}

output "sns_sms_delivery_log_group" {
  value       = local.sns_sms_success_log_group_name
  description = "CloudWatch Logs group SNS writes successful SMS delivery events to. Account-level SNS attributes must point at the matching role for this pipeline to activate (see infra/aws/scripts/setup-sns-delivery-logging.sh, PR 13)."
}
