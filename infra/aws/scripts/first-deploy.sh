#!/usr/bin/env bash
# Drive the post-bootstrap "first deploy" sequence for an env:
#
#   populate-secrets.sh ENV   (push SM values from secrets.env)
#   gh workflow run cd.yml    (CD #1 — builds + pushes images;
#                              migrate step fails because db-init
#                              hasn't run, but the image push is
#                              the load-bearing artifact here)
#   init-db.sh ENV            (creates the app DB role + database
#                              against the just-pushed image)
#   gh workflow run cd.yml    (CD #2 — migrate now succeeds, service
#                              rolls to the new image, health probe
#                              verifies the live stack)
#
# Each step is individually idempotent and runnable on its own; this
# wrapper just makes the order + timing safe so an operator doesn't
# have to babysit five separate commands.
#
# Prerequisites (one-time per env, before running this):
#   - bootstrap.sh ENV applied successfully
#   - app domain CNAME in DNS (printed by bootstrap.sh)
#   - infra/secrets/${ENV}.secrets.env has real values
#   - setup-github-oidc.sh ENV has run (sets AWS_ROLE_TO_ASSUME)
#   - `gh` CLI authed with workflow + repo scope on the target repo
#
# Usage:
#   infra/aws/scripts/first-deploy.sh <staging|production>
#
# Non-interactive: respects SECRETS_AUTO_APPROVE (passed through to
# populate-secrets.sh) and DBINIT_AUTO_APPROVE (init-db.sh).

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

ENV=${1:-}
case "$ENV" in
  staging|production) ;;
  *) echo "Usage: $0 <staging|production>" >&2; exit 1 ;;
esac

REPO="${GHA_REPO:-Hey-June-Inc/made-it-home}"

# Sanity: gh must be present and authed. The CD trigger + wait depend
# on it. We don't try to fall back to a manual path here because the
# whole point of this script is sequencing — without gh there's no
# script-driven CD step.
command -v gh >/dev/null || { echo "ERROR: gh CLI required" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: gh not authed" >&2; exit 1; }

run_cd() {
    local label="$1"
    echo ""
    echo "═════════════════════════════════════════════════════════════"
    echo " $label"
    echo "═════════════════════════════════════════════════════════════"
    gh workflow run cd.yml --ref master \
        -f environment="$ENV" --repo "$REPO"
    # Give GitHub a beat to create the run, then resolve its ID.
    sleep 8
    local RUN_ID
    RUN_ID=$(gh run list --workflow=cd.yml --limit 1 --repo "$REPO" \
        --json databaseId --jq '.[0].databaseId')
    echo "Watching run $RUN_ID..."
    # `gh run watch` exits with the run's conclusion code, so a CD that
    # fails (expected for the first run) would kill this script under
    # `set -e`. We tolerate failure here and inspect with the caller.
    gh run watch "$RUN_ID" --repo "$REPO" --exit-status || true
    local CONCLUSION
    CONCLUSION=$(gh api "repos/$REPO/actions/runs/$RUN_ID" --jq '.conclusion')
    echo "$label → $CONCLUSION"
    LAST_RUN_CONCLUSION="$CONCLUSION"
}

echo "═════════════════════════════════════════════════════════════"
echo " Step 1/4: push secrets to AWS Secrets Manager"
echo "═════════════════════════════════════════════════════════════"
"$SCRIPT_DIR/populate-secrets.sh" "$ENV"

run_cd "Step 2/4: CD #1 (build + push images; migrate expected to fail)"

echo ""
echo "═════════════════════════════════════════════════════════════"
echo " Step 3/4: init-db (create app role + database)"
echo "═════════════════════════════════════════════════════════════"
"$SCRIPT_DIR/init-db.sh" "$ENV"

run_cd "Step 4/4: CD #2 (migrate + deploy + health check)"

if [[ "$LAST_RUN_CONCLUSION" != "success" ]]; then
    echo ""
    echo "ERROR: final CD did not succeed — conclusion: $LAST_RUN_CONCLUSION" >&2
    echo "Inspect via: gh run view --repo $REPO" >&2
    exit 1
fi

echo ""
echo "═════════════════════════════════════════════════════════════"
echo " first-deploy ($ENV) complete"
echo "═════════════════════════════════════════════════════════════"
APP_DOMAIN=$( [[ "$ENV" == "production" ]] && echo "app.madeithomeapp.com" || echo "${ENV}-app.madeithomeapp.com" )
echo "Verify: curl https://${APP_DOMAIN}/health/ready"
