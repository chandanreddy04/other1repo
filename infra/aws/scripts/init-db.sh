#!/usr/bin/env bash
# Provision the least-priv app role + database on RDS via the
# `madeithome-db-init-<env>` ECS task.
#
# RDS is in a private subnet (no public endpoint), so role/DB creation
# (a data-plane SQL op) can only run from inside the VPC. This wraps
# `aws ecs run-task` on the db-init task definition, injecting:
#
#   ADMIN_DSN     -- built from the RDS-managed master secret
#   APP_ROLE      -- parsed from DATABASE_URL in the secrets file
#   APP_PASSWORD  -- same source
#   APP_DB        -- same source
#
# Idempotent — init_db.py upserts the role/db. Run ONCE per env after
# the first CD push (so an `<env>-web` image exists in ECR).
#
# Usage:
#   infra/aws/scripts/init-db.sh <staging|production>
#
# Non-interactive: set DBINIT_AUTO_APPROVE=1 to skip the confirmation
# prompt (for CI or non-TTY shells). Unset, it prompts.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STACK_DIR="$REPO_ROOT/infra/aws/primary"
SECRETS_DIR="$REPO_ROOT/infra/secrets"

ENV=${1:-}
case "$ENV" in
  staging|production) ;;
  *) echo "Usage: $0 <staging|production>" >&2; exit 1 ;;
esac

VALUE_FILE="$SECRETS_DIR/${ENV}.secrets.env"
[[ -f "$VALUE_FILE" ]] || { echo "Missing $VALUE_FILE" >&2; exit 1; }

REGION="${AWS_REGION:-us-west-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

cd "$STACK_DIR"

# Re-init TF for the target env's state backend. The primary stack uses
# a single working directory backed by env-specific S3 buckets, so
# running init-db.sh for a different env than the last bootstrap.sh
# would otherwise read the wrong state's outputs. Idempotent
# (`-reconfigure` is fine to repeat).
echo "▶ Pointing TF at the $ENV state backend..."
BUCKET="madeithome-tfstate-${ENV}-${ACCOUNT_ID}"
TABLE="madeithome-tfstate-lock-${ENV}"
terraform init -input=false -reconfigure \
  -backend-config="bucket=$BUCKET" \
  -backend-config="dynamodb_table=$TABLE" \
  -backend-config="key=primary/terraform.tfstate" \
  -backend-config="region=$REGION" >/dev/null

CLUSTER=$(terraform output -raw ecs_cluster_name)
TASK_FAMILY=$(terraform output -raw db_init_task_definition_family)
SG=$(terraform output -raw worker_task_security_group_id)
ADMIN_SECRET=$(terraform output -raw rds_admin_secret_arn)
DB_HOST=$(terraform output -raw rds_host)
DB_PORT=$(terraform output -raw rds_port)
SUBNETS=$(terraform output -json public_subnet_ids | jq -r 'join(",")')

# Parse DATABASE_URL -> APP_ROLE / APP_PASSWORD / APP_DB.
#
# Shell-string parsing assumes the password contains no '@' as the last
# char before the host (rare but legal in libpq). We validate APP_ROLE
# below as a sanity check.
DB_URL=$(grep -E '^DATABASE_URL=' "$VALUE_FILE" | head -1 | cut -d= -f2-)
[[ -n "$DB_URL" ]] || { echo "DATABASE_URL not set in $VALUE_FILE" >&2; exit 1; }
noscheme=${DB_URL#*://}
creds=${noscheme%@*}
hostpart=${noscheme#*@}
APP_ROLE=${creds%%:*}
APP_PASSWORD=${creds#*:}
APP_DB=${hostpart#*/}; APP_DB=${APP_DB%%\?*}

# Sanity-check APP_ROLE — Postgres identifiers are alphanumeric +
# underscore. Anything else points at a parsing failure.
if [[ ! "$APP_ROLE" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
  echo "ERROR: parsed APP_ROLE=$APP_ROLE doesn't look like a Postgres identifier." >&2
  echo "Check that DATABASE_URL in $VALUE_FILE is well-formed." >&2
  exit 1
fi

# Fetch the master password from Secrets Manager and build ADMIN_DSN.
#
# Visibility caveat: ADMIN_DSN is sent to AWS as part of `--overrides`
# and lands in the task's container environment. Anyone with
# ecs:DescribeTasks during the few seconds the task is running can see
# it. We tolerate this because the task is transient (auto-stops) and
# the master role is high-privilege for only a short window.
ADMIN_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "$ADMIN_SECRET" \
  --region "$REGION" \
  --query SecretString --output text)
ADMIN_USER=$(echo "$ADMIN_JSON" | jq -r '.username')
ADMIN_PASS=$(echo "$ADMIN_JSON" | jq -r '.password')
ADMIN_DSN="host=${DB_HOST} port=${DB_PORT} dbname=postgres user=${ADMIN_USER} password=${ADMIN_PASS} sslmode=require"

echo "=== db-init ($ENV) ==="
echo "Cluster   : $CLUSTER"
echo "Task      : $TASK_FAMILY"
echo "DB host   : $DB_HOST:$DB_PORT"
echo "App role  : $APP_ROLE"
echo "App DB    : $APP_DB"
echo ""

if [[ "${DBINIT_AUTO_APPROVE:-}" == "1" || "${DBINIT_AUTO_APPROVE:-}" == "yes" ]]; then
  echo "DBINIT_AUTO_APPROVE set — running db-init without prompt."
else
  read -rp "Run db-init now? Type 'yes': " confirm
  [[ "$confirm" == "yes" ]] || { echo "Aborted." >&2; exit 1; }
fi

# Build the env-var overrides JSON. Each value is a string; jq handles
# special-character escaping for us.
OVERRIDES=$(jq -nc \
  --arg admin_dsn "$ADMIN_DSN" \
  --arg app_role "$APP_ROLE" \
  --arg app_password "$APP_PASSWORD" \
  --arg app_db "$APP_DB" \
  '{
    containerOverrides: [{
      name: "db-init",
      environment: [
        {name: "ADMIN_DSN", value: $admin_dsn},
        {name: "APP_ROLE", value: $app_role},
        {name: "APP_PASSWORD", value: $app_password},
        {name: "APP_DB", value: $app_db}
      ]
    }]
  }')

# The db-init task def lives at the TF-managed placeholder image
# (nginx) until something patches it. CD intentionally doesn't touch
# db-init (it's operator-only), so we register a new revision here
# with the most recent web image — that has Python + init_db.py.
echo "--- Patching db-init image to latest web image ---"
LATEST_WEB_TAG=$(aws ecr describe-images --region "$REGION" \
  --repository-name "madeithome-web-$ENV" \
  --query 'sort_by(imageDetails,&imagePushedAt)[-1].imageTags[0]' \
  --output text)
if [[ -z "$LATEST_WEB_TAG" || "$LATEST_WEB_TAG" == "None" ]]; then
  echo "ERROR: no images in ECR repo madeithome-web-$ENV; run CD first" >&2
  exit 1
fi
ACCT=$(aws sts get-caller-identity --query Account --output text)
WEB_IMAGE="${ACCT}.dkr.ecr.${REGION}.amazonaws.com/madeithome-web-${ENV}:${LATEST_WEB_TAG}"
echo "  Image: $WEB_IMAGE"
BASE=$(aws ecs describe-task-definition --region "$REGION" \
  --task-definition "$TASK_FAMILY" --query 'taskDefinition' --output json)
REGISTER_INPUT=$(echo "$BASE" | jq --arg image "$WEB_IMAGE" '
  del(.revision, .status, .registeredAt, .registeredBy,
      .taskDefinitionArn, .requiresAttributes, .compatibilities)
  | .containerDefinitions |= map(.image = $image)
')
NEW_REVISION=$(aws ecs register-task-definition --region "$REGION" \
  --cli-input-json "$REGISTER_INPUT" \
  --query 'taskDefinition.taskDefinitionArn' --output text)
echo "  Registered: $NEW_REVISION"

echo "--- Starting db-init task ---"
TASK_ARN=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$NEW_REVISION" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SG],assignPublicIp=ENABLED}" \
  --overrides "$OVERRIDES" \
  --region "$REGION" \
  --query 'tasks[0].taskArn' --output text)

echo "Task ARN: $TASK_ARN"
echo "--- Waiting for task to stop ---"
aws ecs wait tasks-stopped \
  --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION"

# Inspect exit code + reason.
EXIT_CODE=$(aws ecs describe-tasks \
  --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' --output text)
REASON=$(aws ecs describe-tasks \
  --cluster "$CLUSTER" --tasks "$TASK_ARN" --region "$REGION" \
  --query 'tasks[0].stoppedReason' --output text)

if [[ "$EXIT_CODE" != "0" ]]; then
  echo "ERROR: db-init failed (exitCode=$EXIT_CODE, reason: $REASON)" >&2
  echo "Logs: aws logs tail /madeithome/$ENV/db-init --since 10m --region $REGION" >&2
  exit 1
fi

echo ""
echo "=== db-init succeeded ($ENV). Now run migrations (re-trigger CD or start migrate task). ==="
