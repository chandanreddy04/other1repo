#!/usr/bin/env bash
# Tear down the primary-region stack for an environment.
#
# Does NOT touch the state-bootstrap stack (state bucket + lock table)
# — that's destroyed separately via its own README procedure.
#
# Resources with `prevent_destroy = true` in the TF will block destroy
# until the operator comments out the lifecycle block. That's the
# intended friction.
#
# Usage:
#   infra/aws/scripts/teardown.sh <staging|production>

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
STACK_DIR="$REPO_ROOT/infra/aws/primary"

ENV=${1:-}
case "$ENV" in
  staging|production) ;;
  *) echo "Usage: $0 <staging|production>" >&2; exit 1 ;;
esac

REGION="${AWS_REGION:-us-west-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== AWS teardown ($ENV) ==="
echo "Account : $ACCOUNT_ID"
echo "Region  : $REGION"
echo ""
echo "This will:"
echo "  - terraform destroy the primary stack in $ENV"
echo "  - NOT touch the state bucket or DynamoDB lock table"
echo "  - FAIL to destroy the photos S3 bucket (prevent_destroy = true)."
echo "    To actually destroy: empty the bucket, comment out the lifecycle"
echo "    block in infra/aws/primary/s3.tf, re-apply, then re-run this script."
echo ""

if [[ "$ENV" == "production" ]]; then
  read -rp "PRODUCTION teardown. Type the environment name to continue: " typed
  [[ "$typed" == "production" ]] || { echo "Aborted." >&2; exit 1; }
  read -rp "Are you ABSOLUTELY sure? Type 'destroy production' to continue: " confirm
  [[ "$confirm" == "destroy production" ]] || { echo "Aborted." >&2; exit 1; }
else
  read -rp "Destroy $ENV? Type 'yes': " confirm
  [[ "$confirm" == "yes" ]] || { echo "Aborted." >&2; exit 1; }
fi

cd "$STACK_DIR"

BUCKET="madeithome-tfstate-${ENV}-${ACCOUNT_ID}"
TABLE="madeithome-tfstate-lock-${ENV}"

terraform init \
  -backend-config="bucket=$BUCKET" \
  -backend-config="dynamodb_table=$TABLE" \
  -backend-config="key=primary/terraform.tfstate" \
  -backend-config="region=$REGION" \
  -reconfigure

terraform destroy -var "environment_name=$ENV"
