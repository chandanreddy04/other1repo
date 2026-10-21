#!/usr/bin/env bash
# One-time per-account-per-region setup for SNS SMS delivery status
# logging.
#
# SetSMSAttributes is an account-level call that configures which IAM
# role SNS writes delivery status events with. The role itself is also
# account-level. Neither belongs in any single env's Terraform stack.
#
# This script:
#   1. Creates an IAM role assumable by sns.amazonaws.com.
#   2. Attaches a policy allowing CloudWatch Logs writes.
#   3. Pre-creates the two delivery-status CloudWatch log groups with a
#      fixed retention.
#   4. Calls SetSMSAttributes to point SNS at the role + sets 100%
#      success-sample rate so every delivery is logged.
#
# Why step 3: SNS only creates the delivery-status log groups LAZILY, on
# the first SMS it actually sends. But the primary Terraform stack reads
# them via a `data "aws_cloudwatch_log_group"` source (sns_delivery.tf):
# in a brand-new account where no SMS has been sent yet, that data source
# fails and `terraform plan` errors out. Pre-creating the groups here
# makes this script the single account-level prerequisite that must run
# BEFORE the first stack apply in a new account — staging or production,
# whichever comes first.
#
# Ownership note: sns_delivery.tf has the PRODUCTION stack own these log
# groups (resource) and the STAGING stack read them (data source). When
# this script pre-creates them for a staging-first bootstrap, the later
# production apply must adopt them instead of recreating:
#   terraform import 'aws_cloudwatch_log_group.sns_sms_success[0]' \
#     "sns/<region>/<account>/DirectPublishToPhoneNumber"
#   terraform import 'aws_cloudwatch_log_group.sns_sms_failure[0]' \
#     "sns/<region>/<account>/DirectPublishToPhoneNumber/Failure"
# The retention created here (default 30d) matches production's
# log_retention_days so the import shows zero drift.
#
# Run ONCE per account+region. Re-runs are idempotent (role create
# tolerates existence; log-group create is guarded; SetSMSAttributes is
# upsert; retention is re-applied each run).
#
# Usage:
#   infra/aws/scripts/setup-sns-delivery-logging.sh [--region us-west-2] [--retention-days 30]

set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
# Default matches production's log_retention_days (logs.tf) so a later
# `terraform import` into the production stack shows no drift.
RETENTION_DAYS=30
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2 ;;
    --retention-days) RETENTION_DAYS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

ROLE_NAME="madeithome-sns-sms-delivery-status"
POLICY_NAME="cwlogs-write"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== SNS SMS delivery logging setup ==="
echo "Account : $ACCOUNT_ID"
echo "Region  : $REGION"
echo "Role    : $ROLE_NAME"
echo ""

ASSUME_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "sns.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
)

# 1. Create the role if it doesn't exist.
# If upgrading from an older policy layout, manually clean stale inline
# policies with `aws iam list-role-policies --role-name $ROLE_NAME` and
# `aws iam delete-role-policy --role-name $ROLE_NAME --policy-name OLD`.
# This script only manages a policy named "cwlogs-write".
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "Role $ROLE_NAME already exists."
else
  echo "Creating role $ROLE_NAME..."
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$ASSUME_POLICY" \
    --description "SNS SMS delivery status writer (managed by setup-sns-delivery-logging.sh)" \
    >/dev/null
fi

INLINE_POLICY=$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:PutMetricFilter",
        "logs:PutRetentionPolicy"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)

echo "Putting inline policy $POLICY_NAME..."
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "$INLINE_POLICY"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"

# 2. Pre-create the delivery-status log groups so the primary stack's
#    data sources resolve in a new account (see header for rationale).
SUCCESS_LG="sns/${REGION}/${ACCOUNT_ID}/DirectPublishToPhoneNumber"
FAILURE_LG="sns/${REGION}/${ACCOUNT_ID}/DirectPublishToPhoneNumber/Failure"
echo ""
echo "Ensuring delivery-status log groups exist (retention ${RETENTION_DAYS}d)..."
for LG in "$SUCCESS_LG" "$FAILURE_LG"; do
  if aws logs describe-log-groups \
       --region "$REGION" \
       --log-group-name-prefix "$LG" \
       --query "logGroups[?logGroupName=='${LG}'] | [0].logGroupName" \
       --output text 2>/dev/null | grep -qx "$LG"; then
    echo "  log group $LG already exists."
  else
    echo "  creating log group $LG..."
    aws logs create-log-group --region "$REGION" --log-group-name "$LG"
  fi
  # Idempotent: re-applies retention every run so it stays in sync.
  aws logs put-retention-policy \
    --region "$REGION" \
    --log-group-name "$LG" \
    --retention-in-days "$RETENTION_DAYS"
done

# 3. Configure SNS to use the role for delivery status logging.
# A just-created IAM role can take several seconds to become usable in the
# iam:PassRole check SetSMSAttributes performs — IAM is eventually
# consistent, so this surfaces as a transient AuthorizationError on a fresh
# role. Retry briefly rather than failing the whole bootstrap.
echo ""
echo "Setting account-level SNS SMS attributes in $REGION..."
attempts=4
for attempt in $(seq 1 "$attempts"); do
  if err=$(aws sns set-sms-attributes \
             --region "$REGION" \
             --attributes "DeliveryStatusIAMRole=${ROLE_ARN},DeliveryStatusSuccessSamplingRate=100" 2>&1); then
    break
  fi
  # Retry only on errors consistent with a freshly-created role not yet
  # propagated (IAM is eventually consistent). The actual error is printed
  # every attempt so a PERMANENT failure (e.g. caller lacks
  # sns:SetSMSAttributes) isn't masked as a propagation delay.
  if [[ "$err" == *PassRole* || "$err" == *AuthorizationError* || "$err" == *"cannot be assumed"* || "$err" == *InvalidParameter* ]] && [[ $attempt -lt $attempts ]]; then
    echo "  set-sms-attributes failed (attempt $attempt/$attempts), retrying in 5s — error: $err" >&2
    sleep 5
  else
    echo "$err" >&2
    exit 1
  fi
done

echo ""
echo "=== Done. ==="
echo ""
echo "Verify with: aws sns get-sms-attributes --region $REGION"
echo "SNS delivery status log groups (pre-created, retention ${RETENTION_DAYS}d):"
echo "  $SUCCESS_LG"
echo "  $FAILURE_LG"
