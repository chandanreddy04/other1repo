#!/usr/bin/env bash
# Push backend secret values to AWS Secrets Manager + mobile secrets to EAS.
#
# Source of truth : infra/secrets/manifest.json   (which keys, which side)
# Secret values   : infra/secrets/<env>.secrets.env (gitignored, you fill in)
#
# Per environment:
#   dev        -> writes backend/.env and mobile/.env locally. Quiet, no cloud.
#   staging    -> pushes to Secrets Manager + EAS. Prints every action; one confirm.
#   production -> same as staging, with double confirmation.
#
# Non-dev runs are never silent: every secret name and target is printed
# before anything changes. Secret VALUES are never printed.
#
# Usage:
#   infra/aws/scripts/populate-secrets.sh <dev|staging|production>
#
# Non-interactive: set SECRETS_AUTO_APPROVE=1 (or "yes") to skip the
# confirmation prompt for dev/staging. PRODUCTION is intentionally NOT
# bypassable by "1" — to auto-approve a production push you must set
# SECRETS_AUTO_APPROVE=production (the literal env name), so a stray "1"
# left in the environment can never silently overwrite prod secrets.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SECRETS_DIR="$REPO_ROOT/infra/secrets"
MANIFEST_PY="$SECRETS_DIR/manifest.py"

ENV=${1:-}
case "$ENV" in
  dev|staging|production) ;;
  *) echo "Usage: $0 <dev|staging|production>" >&2; exit 1 ;;
esac

VALUE_FILE="$SECRETS_DIR/${ENV}.secrets.env"
if [[ ! -f "$VALUE_FILE" ]]; then
  echo "Value file not found: $VALUE_FILE" >&2
  echo "Create it from the template: cp $SECRETS_DIR/example.secrets.env $VALUE_FILE" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# dev: generate local .env files only.
# ---------------------------------------------------------------------------
if [[ "$ENV" == "dev" ]]; then
  BACKEND_ENV="$REPO_ROOT/backend/.env"
  MOBILE_ENV="$REPO_ROOT/mobile/.env"
  python3 "$MANIFEST_PY" dotenv dev backend "$VALUE_FILE" > "$BACKEND_ENV"
  python3 "$MANIFEST_PY" dotenv dev mobile "$VALUE_FILE" > "$MOBILE_ENV"
  echo "Wrote $BACKEND_ENV"
  echo "Wrote $MOBILE_ENV"
  echo "Done (dev). Local files only — nothing sent to AWS or EAS."
  exit 0
fi

# ---------------------------------------------------------------------------
# staging / production: AWS Secrets Manager + EAS.
# ---------------------------------------------------------------------------
echo "=== populate-secrets ($ENV) ==="

# Hard-fail if any required secret value is blank.
python3 "$MANIFEST_PY" validate "$ENV" "$VALUE_FILE"

REGION="${AWS_REGION:-us-west-2}"
NAME_PREFIX="madeithome"

echo ""
echo "Target region        : $REGION"
echo "Secrets Manager name : ${NAME_PREFIX}-<KEY>-${ENV}"
echo ""
echo "Backend secrets to push (values redacted):"
python3 "$MANIFEST_PY" cloud "$ENV" backend "$VALUE_FILE" \
  | awk -F'\t' -v np="$NAME_PREFIX" -v env="$ENV" \
      '$1=="secret"{printf "  [secret] %s -> sm:%s-%s-%s\n",$2,np,$2,env}'
echo ""
echo "Mobile secrets to push to EAS:"
python3 "$MANIFEST_PY" cloud "$ENV" mobile "$VALUE_FILE" \
  | awk -F'\t' '{printf "  [secret] %s\n",$2}'
echo ""

AUTO="${SECRETS_AUTO_APPROVE:-}"
if [[ "$ENV" == "production" ]]; then
  # Production is NOT bypassable by a generic SECRETS_AUTO_APPROVE=1 (which
  # could be a leftover from a staging run). Auto-approve for prod requires
  # the literal value "production" — the non-interactive mirror of the
  # "type the environment name" guard. Anything else falls through to the
  # interactive double-prompt.
  if [[ "$AUTO" == "production" ]]; then
    echo "SECRETS_AUTO_APPROVE=production — pushing to PRODUCTION without prompt."
  else
    if [[ -n "$AUTO" ]]; then
      echo "SECRETS_AUTO_APPROVE='$AUTO' does not authorize a PRODUCTION push (need 'production'); prompting instead." >&2
    fi
    read -rp "PRODUCTION change. Type the environment name to continue: " typed
    if [[ "$typed" != "production" ]]; then echo "Aborted." >&2; exit 1; fi
    read -rp "Apply the plan above to PRODUCTION? Type 'yes': " confirm
    if [[ "$confirm" != "yes" ]]; then echo "Aborted." >&2; exit 1; fi
  fi
elif [[ "$AUTO" == "1" || "$AUTO" == "yes" || "$AUTO" == "$ENV" ]]; then
  echo "SECRETS_AUTO_APPROVE set — pushing to $ENV without prompt."
else
  read -rp "Apply the plan above to $ENV? Type 'yes': " confirm
  if [[ "$confirm" != "yes" ]]; then echo "Aborted." >&2; exit 1; fi
fi

command -v aws >/dev/null || { echo "aws CLI not found." >&2; exit 1; }

echo ""
echo "--- Pushing backend secrets to Secrets Manager ---"
# Manifest TSV columns: kind, env_var, value. The Secrets Manager name is
# constructed below from env_var.
#
# Prerequisite: bootstrap.sh has been run — Terraform creates the
# secret containers; this script only pushes versions. Missing
# containers will surface as ResourceNotFoundException.
while IFS=$'\t' read -r kind env_var value; do
  [[ "$kind" != "secret" ]] && continue
  SECRET_NAME="${NAME_PREFIX}-${env_var}-${ENV}"
  echo "  sm put-secret-value $SECRET_NAME"
  # `--secret-string=$value` (with =) prevents the CLI from parsing a
  # value that starts with `-` as a new flag.
  aws secretsmanager put-secret-value \
    --secret-id "$SECRET_NAME" \
    --secret-string="$value" \
    --region "$REGION" \
    >/dev/null
done < <(python3 "$MANIFEST_PY" cloud "$ENV" backend "$VALUE_FILE")

echo ""
echo "--- Mobile: EAS project secrets ---"
if command -v eas >/dev/null; then
  # eas-cli >= 14 replaced `secret:create` with `env:create`. EAS has three
  # fixed environments (development/preview/production); staging maps to
  # preview. --force overwrites an existing variable of the same name.
  EAS_ENV=$( [[ "$ENV" == "production" ]] && echo "production" || echo "preview" )
  while IFS=$'\t' read -r kind env_var value; do
    [[ "$kind" != "secret" ]] && continue
    echo "  eas env: $env_var ($EAS_ENV)"
    ( cd "$REPO_ROOT/mobile" && eas env:create --scope project \
        --environment "$EAS_ENV" --name "$env_var" --value "$value" \
        --visibility sensitive --force --non-interactive )
  done < <(python3 "$MANIFEST_PY" cloud "$ENV" mobile "$VALUE_FILE")
  echo "  Note: EAS env vars are project-scoped. The last run wins."
else
  echo "  eas CLI not found — skipping. Install with 'npm i -g eas-cli', then re-run." >&2
fi

echo ""
echo "=== Done ($ENV). Roll the ECS service to pick up new values: ==="
# Resource names follow the convention in infra/aws/README.md, so no TF
# state read needed (which would require switching backends per env).
echo "  aws ecs update-service --cluster madeithome-cluster-${ENV} --service madeithome-web-${ENV} --force-new-deployment --region $REGION"
