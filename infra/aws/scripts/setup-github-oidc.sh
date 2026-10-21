#!/usr/bin/env bash
# Bootstrap GitHub Actions → AWS authentication via OIDC for one env.
#
# Runs once per AWS account. After this:
#   - The OIDC identity provider for token.actions.githubusercontent.com
#     exists in the account (one per account total — idempotent if present)
#   - An IAM role `madeithome-gha-deploy-{env}` exists that the GitHub
#     workflow can assume from the `{env}` GitHub Environment in the
#     `Hey-June-Inc/made-it-home` repo
#   - The role's permissions cover the deploy steps in `deploy-aws.yml`:
#     ECR push, ECS register/update task def, ECS RunTask (migrate +
#     db-init), CloudWatch Logs read, SSM read (deploy container spec),
#     IAM PassRole on the task + exec roles
#   - An ACCOUNT-WIDE read-only role `madeithome-gha-readonly` (AWS-managed
#     ReadOnlyAccess) exists for the scheduled drift-detection workflow, and
#     its ARN is set as the repo secret AWS_READONLY_ROLE_TO_ASSUME
#
# After this script succeeds: copy the printed ARN into the GitHub
# Environment's `AWS_ROLE_TO_ASSUME` secret. The next master push will
# auto-deploy via cd.yml -> deploy-aws.yml.
#
# Usage:
#   AWS_PROFILE=madeithome ./setup-github-oidc.sh staging
#   AWS_PROFILE=madeithome ./setup-github-oidc.sh production
#
# Idempotent: re-running for the same env updates the trust + inline
# policy in place; safe to run after permission tweaks.

set -euo pipefail

ENV="${1:-}"
if [[ -z "$ENV" || ("$ENV" != "staging" && "$ENV" != "production") ]]; then
    echo "usage: $0 (staging|production)" >&2
    exit 2
fi

REPO="${GHA_REPO:-Hey-June-Inc/made-it-home}"
PROVIDER_URL="token.actions.githubusercontent.com"
ROLE_NAME="madeithome-gha-deploy-${ENV}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "▶ Account ${ACCOUNT_ID}, repo ${REPO}, env ${ENV}, role ${ROLE_NAME}"

# ---------------------------------------------------------------------------
# 1. OIDC identity provider (account-level, idempotent)
# ---------------------------------------------------------------------------
PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${PROVIDER_URL}"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
    echo "✓ OIDC provider already exists: $PROVIDER_ARN"
else
    echo "▶ Creating OIDC provider..."
    # Thumbprint is GitHub's (DigiCert root) — required for the legacy
    # IAM JIT verification path; modern IAM trusts based on issuer +
    # audience and the thumbprint is effectively ignored, but the API
    # still requires it be present.
    aws iam create-open-id-connect-provider \
        --url "https://${PROVIDER_URL}" \
        --client-id-list sts.amazonaws.com \
        --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 \
        >/dev/null
    echo "✓ OIDC provider created: $PROVIDER_ARN"
fi

# ---------------------------------------------------------------------------
# 2. Trust policy — only the named env's deploys may assume the role
# ---------------------------------------------------------------------------
# The `sub` claim shape for GitHub Actions:
#   repo:OWNER/REPO:environment:ENV
# pinning environment:ENV refuses assumes from branches/forks that
# bypass the GitHub Environment gate. Combined with `secrets: inherit`
# scoping in cd.yml, this means a PR or fork CANNOT take the role.
TRUST_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "${PROVIDER_ARN}" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "${PROVIDER_URL}:aud": "sts.amazonaws.com",
        "${PROVIDER_URL}:sub": "repo:${REPO}:environment:${ENV}"
      }
    }
  }]
}
EOF
)

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    echo "▶ Updating trust policy on existing role..."
    aws iam update-assume-role-policy --role-name "$ROLE_NAME" \
        --policy-document "$TRUST_DOC" >/dev/null
else
    echo "▶ Creating role $ROLE_NAME..."
    aws iam create-role --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_DOC" \
        --description "GitHub Actions deploy role for env=${ENV}" \
        >/dev/null
fi

# ---------------------------------------------------------------------------
# 3. Inline policy — permissions deploy-aws.yml needs
# ---------------------------------------------------------------------------
# Scoped to the env's resources where AWS resource ARNs support it.
# Kept inline (not a managed policy) so it's tied to the role's
# lifetime and obvious to audit.
POLICY_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuthAndPush",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:DescribeImages",
        "ecr:DescribeRepositories",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECSDeploy",
      "Effect": "Allow",
      "Action": [
        "ecs:RegisterTaskDefinition",
        "ecs:DescribeTaskDefinition",
        "ecs:UpdateService",
        "ecs:DescribeServices",
        "ecs:DescribeClusters",
        "ecs:RunTask",
        "ecs:DescribeTasks",
        "ecs:ListTasks",
        "ecs:TagResource"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ReadDeployContainerSpec",
      "Effect": "Allow",
      "Action": "ssm:GetParameter",
      "Resource": "arn:aws:ssm:*:${ACCOUNT_ID}:parameter/madeithome/*"
    },
    {
      "Sid": "PassRoleToECSTasks",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::${ACCOUNT_ID}:role/madeithome-task-exec-*-${ENV}",
        "arn:aws:iam::${ACCOUNT_ID}:role/madeithome-task-*-${ENV}"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "ecs-tasks.amazonaws.com"
        }
      }
    },
    {
      "Sid": "LogsForDeployVisibility",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:GetLogEvents",
        "logs:FilterLogEvents"
      ],
      "Resource": "arn:aws:logs:*:${ACCOUNT_ID}:log-group:/ecs/madeithome-*:*"
    }
  ]
}
EOF
)

aws iam put-role-policy --role-name "$ROLE_NAME" \
    --policy-name "deploy" \
    --policy-document "$POLICY_DOC" >/dev/null

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "✓ Role ready: $ROLE_ARN"

# ---------------------------------------------------------------------------
# 3b. Read-only role for scheduled drift detection (.github/workflows/
#     drift-detection.yml). ACCOUNT-WIDE (one role, both envs) — a drift
#     `terraform plan` must read every resource but writes nothing, so it gets
#     the AWS-managed ReadOnlyAccess policy. The drift workflow is NOT env-gated
#     (it runs on a schedule from the default branch), so the trust matches any
#     ref/environment in THIS repo (StringLike repo:REPO:*) — safe because the
#     role is read-only and a fork's `repo:` claim never matches.
# ---------------------------------------------------------------------------
RO_ROLE_NAME="madeithome-gha-readonly"
RO_TRUST_DOC=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "${PROVIDER_ARN}" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "${PROVIDER_URL}:aud": "sts.amazonaws.com" },
      "StringLike": { "${PROVIDER_URL}:sub": "repo:${REPO}:*" }
    }
  }]
}
EOF
)
if aws iam get-role --role-name "$RO_ROLE_NAME" >/dev/null 2>&1; then
    echo "▶ Updating trust on existing read-only role..."
    aws iam update-assume-role-policy --role-name "$RO_ROLE_NAME" \
        --policy-document "$RO_TRUST_DOC" >/dev/null
else
    echo "▶ Creating read-only role $RO_ROLE_NAME..."
    aws iam create-role --role-name "$RO_ROLE_NAME" \
        --assume-role-policy-document "$RO_TRUST_DOC" \
        --description "GitHub Actions read-only role for terraform drift detection" \
        >/dev/null
fi
aws iam attach-role-policy --role-name "$RO_ROLE_NAME" \
    --policy-arn "arn:aws:iam::aws:policy/ReadOnlyAccess" >/dev/null
RO_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${RO_ROLE_NAME}"
echo "✓ Read-only role ready: $RO_ROLE_ARN"

# ---------------------------------------------------------------------------
# 4. Push the role ARN to the GitHub Environment secret + create the
#    environment if it doesn't exist. Idempotent: gh secret set updates
#    an existing value, the env create returns the same env if present.
#
# Requires `gh` authed with `admin:repo` scope on the repo. When `gh`
# is missing/unauthed the script prints manual instructions and exits 0
# so it remains usable in restricted-CLI environments.
# ---------------------------------------------------------------------------
SKIP_GH="${SKIP_GH:-}"
print_manual_steps() {
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo " Manual step: set the GitHub Environment secret"
    echo "════════════════════════════════════════════════════════════"
    echo ""
    echo "  gh secret set AWS_ROLE_TO_ASSUME \\"
    echo "    --env ${ENV} \\"
    echo "    --body '${ROLE_ARN}' \\"
    echo "    --repo ${REPO}"
    echo ""
    echo " Or via the GitHub UI:"
    echo "   Settings → Environments → ${ENV} → Add secret"
    echo "     AWS_ROLE_TO_ASSUME = ${ROLE_ARN}"
    echo ""
    echo " And the repo-level read-only role for drift detection:"
    echo "  gh secret set AWS_READONLY_ROLE_TO_ASSUME \\"
    echo "    --body '${RO_ROLE_ARN}' \\"
    echo "    --repo ${REPO}"
    echo ""
}

if [[ -n "$SKIP_GH" ]]; then
    echo "SKIP_GH set — not touching GitHub."
    print_manual_steps
    exit 0
fi
if ! command -v gh >/dev/null 2>&1; then
    echo "ℹ gh CLI not found — skipping GitHub Environment setup."
    print_manual_steps
    exit 0
fi
if ! gh auth status >/dev/null 2>&1; then
    echo "ℹ gh CLI not authed — skipping GitHub Environment setup."
    print_manual_steps
    exit 0
fi

# Create the environment (idempotent; the API returns the same env on
# repeat). Some restricted PATs can't create environments; tolerate
# the failure and proceed to secret set, which is the load-bearing op.
echo "▶ Ensuring GitHub Environment ${ENV} exists..."
gh api -X PUT "repos/${REPO}/environments/${ENV}" >/dev/null 2>&1 || true

echo "▶ Setting AWS_ROLE_TO_ASSUME on ${ENV}..."
gh secret set AWS_ROLE_TO_ASSUME \
    --env "${ENV}" \
    --body "${ROLE_ARN}" \
    --repo "${REPO}"
echo "✓ GitHub Environment '${ENV}' has AWS_ROLE_TO_ASSUME = ${ROLE_ARN}"

# Repo-level (not env-scoped): the drift workflow isn't env-gated.
echo "▶ Setting repo secret AWS_READONLY_ROLE_TO_ASSUME..."
gh secret set AWS_READONLY_ROLE_TO_ASSUME \
    --body "${RO_ROLE_ARN}" \
    --repo "${REPO}"
echo "✓ Repo secret AWS_READONLY_ROLE_TO_ASSUME = ${RO_ROLE_ARN}"
