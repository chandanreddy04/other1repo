#!/usr/bin/env bash
# One-time GCP infrastructure setup for Made It Home.
# Run this once before the first deployment.
# Usage: ./scripts/gcp-setup.sh YOUR_GCP_PROJECT_ID
set -euo pipefail

PROJECT_ID="${1:?Usage: $0 PROJECT_ID}"
REGION="us-central1"
DEPLOYER_SA="made-it-home-deployer@$PROJECT_ID.iam.gserviceaccount.com"
STAGING_SA="made-it-home-staging@$PROJECT_ID.iam.gserviceaccount.com"
PRODUCTION_SA="made-it-home-production@$PROJECT_ID.iam.gserviceaccount.com"

echo "==> Configuring project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

echo "==> Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

echo "==> Creating Artifact Registry repository..."
gcloud artifacts repositories create made-it-home-backend \
  --repository-format=docker \
  --location="$REGION" \
  --description="Made It Home backend images" 2>/dev/null || echo "    Already exists, skipping."

echo "==> Creating service accounts..."
gcloud iam service-accounts create made-it-home-deployer \
  --display-name="Made It Home CI/CD Deployer" 2>/dev/null || echo "    Deployer SA already exists."
gcloud iam service-accounts create made-it-home-staging \
  --display-name="Made It Home Staging Runtime" 2>/dev/null || echo "    Staging SA already exists."
gcloud iam service-accounts create made-it-home-production \
  --display-name="Made It Home Production Runtime" 2>/dev/null || echo "    Production SA already exists."

echo "==> Granting deployer permissions..."
for role in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser roles/secretmanager.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$DEPLOYER_SA" \
    --role="$role" --quiet
done

echo "==> Creating Secret Manager secrets (placeholder values — update before first deploy)..."
STAGING_SECRETS=(
  staging-database-url
  staging-sync-database-url
  staging-secret-key
  staging-inngest-signing-key
  staging-inngest-event-key
)
PRODUCTION_SECRETS=(
  production-database-url
  production-sync-database-url
  production-secret-key
  production-inngest-signing-key
  production-inngest-event-key
  twilio-account-sid
  twilio-auth-token
  twilio-phone-number
  bugsnag-api-key
  stripe-secret-key
  stripe-webhook-secret
  revenuecat-api-key
  revenuecat-webhook-auth-key
)

for secret in "${STAGING_SECRETS[@]}" "${PRODUCTION_SECRETS[@]}"; do
  echo -n "placeholder" | gcloud secrets create "$secret" --data-file=- 2>/dev/null || \
    echo "    $secret already exists, skipping."
done

echo "==> Granting staging runtime access to staging secrets..."
for secret in "${STAGING_SECRETS[@]}"; do
  gcloud secrets add-iam-policy-binding "$secret" \
    --member="serviceAccount:$STAGING_SA" \
    --role="roles/secretmanager.secretAccessor" --quiet
done

echo "==> Granting production runtime access to production secrets..."
for secret in "${PRODUCTION_SECRETS[@]}"; do
  gcloud secrets add-iam-policy-binding "$secret" \
    --member="serviceAccount:$PRODUCTION_SA" \
    --role="roles/secretmanager.secretAccessor" --quiet
done

echo "==> Generating deployer service account key..."
KEY_FILE="/tmp/gcp-credentials-${PROJECT_ID}.json"
gcloud iam service-accounts keys create "$KEY_FILE" --iam-account="$DEPLOYER_SA"

echo ""
echo "========================================================"
echo "Setup complete. Now do the following:"
echo ""
echo "1. Add these secrets to GitHub (repo-level, Settings → Secrets → Actions):"
echo "   GCP_PROJECT_ID  = $PROJECT_ID"
echo "   GCP_CREDENTIALS = $(cat "$KEY_FILE")"
echo ""
echo "2. Create GitHub Environments (Settings → Environments):"
echo "   - 'staging'    — no protection rules needed"
echo "   - 'production' — add yourself as required reviewer"
echo ""
echo "   Each environment needs these secrets (the Neon DB URLs):"
echo "   DATABASE_URL      = postgresql+asyncpg://... (used for migrations in CI)"
echo "   SYNC_DATABASE_URL = postgresql://...         (used for migrations in CI)"
echo ""
echo "3. Update Secret Manager secrets with real values:"
echo "   echo -n 'YOUR_VALUE' | gcloud secrets versions add staging-database-url --data-file=-"
echo "   echo -n 'YOUR_VALUE' | gcloud secrets versions add staging-sync-database-url --data-file=-"
echo "   echo -n 'YOUR_VALUE' | gcloud secrets versions add staging-secret-key --data-file=-"
echo "   # ... repeat for all secrets listed above"
echo ""
echo "4. Delete the credentials file when done:"
echo "   rm $KEY_FILE"
echo "========================================================"
