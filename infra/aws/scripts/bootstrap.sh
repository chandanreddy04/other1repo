#!/usr/bin/env bash
# Initialize and apply the AWS primary-region stack for an environment.
#
# Prerequisites:
#   - infra/aws/state-bootstrap/ already applied for this env (the S3
#     state bucket + DynamoDB lock table must exist).
#   - AWS credentials in the current shell (`aws sts get-caller-identity`
#     should succeed).
#   - SNS delivery-status log groups exist in this account+region. The
#     primary stack reads them via a data source (sns_delivery.tf), so the
#     FIRST stack apply in a new account fails without them. Run
#     setup-sns-delivery-logging.sh once per account+region first. This
#     script preflights for them and tells you if they're missing.
#
# Usage:
#   infra/aws/scripts/bootstrap.sh <staging|production>
#
# Non-interactive: set BOOTSTRAP_AUTO_APPROVE=1 to skip the apply
# confirmation prompt (for CI or non-TTY shells). Unset, it prompts.
#
# This script is idempotent — safe to re-run; Terraform will plan + apply
# whatever drifted.

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

BUCKET="madeithome-tfstate-${ENV}-${ACCOUNT_ID}"
TABLE="madeithome-tfstate-lock-${ENV}"

echo "=== AWS bootstrap ($ENV) ==="
echo "Account : $ACCOUNT_ID"
echo "Region  : $REGION"
echo "Bucket  : $BUCKET"
echo "Table   : $TABLE"
echo ""

# State backend: auto-create on first run for this env. Uses workspaces
# in the state-bootstrap stack so staging + production are isolated
# state files inside the same TF working directory.
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "▶ State bucket $BUCKET not found — running state-bootstrap..."
  STATE_DIR="$REPO_ROOT/infra/aws/state-bootstrap"
  (
    cd "$STATE_DIR"
    terraform init -input=false >/dev/null
    # `workspace new` errors if it exists; tolerate and select.
    terraform workspace new "$ENV" 2>/dev/null || true
    terraform workspace select "$ENV"
    terraform apply -input=false -auto-approve -var "environment_name=$ENV"
  )
  echo "✓ State backend ready for $ENV."
fi

# Verify the SNS delivery-status log groups exist. The primary stack reads
# BOTH (success + failure) via data sources (sns_delivery.tf); a missing
# EITHER makes `terraform plan` fail with an opaque "empty result" error,
# so the preflight must check both — not just the success group. Fail early
# with a clear fix.
SNS_SUCCESS_LG="sns/${REGION}/${ACCOUNT_ID}/DirectPublishToPhoneNumber"
SNS_FAILURE_LG="${SNS_SUCCESS_LG}/Failure"
for LG in "$SNS_SUCCESS_LG" "$SNS_FAILURE_LG"; do
  if ! aws logs describe-log-groups \
        --region "$REGION" \
        --log-group-name-prefix "$LG" \
        --query "logGroups[?logGroupName=='${LG}'] | [0].logGroupName" \
        --output text 2>/dev/null | grep -qx "$LG"; then
    echo "ERROR: SNS delivery-status log group $LG not found." >&2
    echo "Run this once per account+region first:" >&2
    echo "  $SCRIPT_DIR/setup-sns-delivery-logging.sh --region $REGION" >&2
    exit 1
  fi
done

cd "$STACK_DIR"

echo "--- terraform init ---"
terraform init \
  -backend-config="bucket=$BUCKET" \
  -backend-config="dynamodb_table=$TABLE" \
  -backend-config="key=primary/terraform.tfstate" \
  -backend-config="region=$REGION" \
  -reconfigure

echo ""
# Pre-step: create the ACM cert ahead of the full apply and emit the
# validation CNAME the operator must add to Cloudflare. The full apply
# below blocks on aws_acm_certificate_validation polling that record,
# so without this step the operator never sees the value they need to
# unblock the script. Targeted apply is fast (one resource) and
# idempotent — skipped if a cert for the env's app domain already
# exists. Domain match (vs Tags) because list-certificates does not
# return tags; the env's app domain is unique anyway.
APP_DOMAIN=$( [[ "$ENV" == "production" ]] && echo "app.madeithomeapp.com" || echo "${ENV}-app.madeithomeapp.com" )
if ! aws acm list-certificates --region "$REGION" \
     --query "CertificateSummaryList[?DomainName=='$APP_DOMAIN'].CertificateArn" \
     --output text 2>/dev/null | grep -q arn; then
  echo "--- acm pre-step: create cert + emit validation CNAME ---"
  terraform apply -input=false -auto-approve \
    -var "environment_name=$ENV" \
    -target=aws_acm_certificate.app
  CERT_ARN=$(terraform output -raw acm_certificate_arn 2>/dev/null || true)
  if [[ -n "$CERT_ARN" ]]; then
    REC=$(aws acm describe-certificate --region "$REGION" \
      --certificate-arn "$CERT_ARN" \
      --query 'Certificate.DomainValidationOptions[0].ResourceRecord' --output json)
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo " Add this CNAME in Cloudflare BEFORE the apply will unblock"
    echo "════════════════════════════════════════════════════════════"
    echo "$REC" | jq .
    echo ""
    echo " Proxy: DNS only (gray cloud). TTL: Auto."
    echo "════════════════════════════════════════════════════════════"
    echo ""
  fi
fi

echo "--- terraform plan ---"
terraform plan -var "environment_name=$ENV" -out=tfplan
echo ""

if [[ "${BOOTSTRAP_AUTO_APPROVE:-}" == "1" || "${BOOTSTRAP_AUTO_APPROVE:-}" == "yes" ]]; then
  echo "BOOTSTRAP_AUTO_APPROVE set — applying without prompt."
else
  read -rp "Apply this plan? Type 'yes': " confirm
  if [[ "$confirm" != "yes" ]]; then
    echo "Aborted."
    rm -f tfplan
    exit 1
  fi
fi

echo "--- terraform apply ---"
terraform apply tfplan
rm -f tfplan

echo ""
echo "=== Bootstrap complete ($ENV) ==="
echo ""
ALB_DNS=$(terraform output -raw alb_dns_name 2>/dev/null || true)
APP_DOMAIN=$(terraform output -raw app_domain 2>/dev/null || true)
if [[ -n "$ALB_DNS" && -n "$APP_DOMAIN" ]]; then
  echo "════════════════════════════════════════════════════════════"
  echo " Add the app DNS in Cloudflare (CD's health check needs it)"
  echo "════════════════════════════════════════════════════════════"
  echo "  Type   : CNAME"
  echo "  Name   : ${APP_DOMAIN}"
  echo "  Target : ${ALB_DNS}"
  echo "  Proxy  : DNS only (gray cloud)"
  echo "  TTL    : Auto"
  echo "════════════════════════════════════════════════════════════"
  echo ""
fi
echo "Next steps:"
echo "  1. Add the app CNAME above in Cloudflare."
echo "  2. Fill secret values:    cp $REPO_ROOT/infra/secrets/example.secrets.env $REPO_ROOT/infra/secrets/${ENV}.secrets.env"
echo "  3. Wire OIDC + GH env:    $SCRIPT_DIR/setup-github-oidc.sh $ENV"
echo "  4. Drive first deploy:    $SCRIPT_DIR/first-deploy.sh $ENV"
echo "                            (push secrets → CD → init-db → CD → verify;"
echo "                             each step is individually idempotent and"
echo "                             runnable on its own — see the script header)"
echo "  5. Re-trigger CD migrate, then verify:  curl https://\$(terraform output -raw app_domain)/health/ready"
echo ""
echo "Outstanding manual steps (Cloudflare side):"
echo "  - Add the ACM validation CNAMEs from 'terraform output acm_validation_records'"
echo "  - Add a CNAME for the app domain pointing at the ALB DNS"
echo ""
echo "Note: SNS SMS delivery logging ($SCRIPT_DIR/setup-sns-delivery-logging.sh)"
echo "      is a PREREQUISITE checked above, not a post-step — already in place."
echo "      If this was a staging-first bootstrap, the later production apply must"
echo "      adopt the shared log groups it's designed to own:"
echo "        terraform import 'aws_cloudwatch_log_group.sns_sms_success[0]' sns/$REGION/$ACCOUNT_ID/DirectPublishToPhoneNumber"
echo "        terraform import 'aws_cloudwatch_log_group.sns_sms_failure[0]' sns/$REGION/$ACCOUNT_ID/DirectPublishToPhoneNumber/Failure"
