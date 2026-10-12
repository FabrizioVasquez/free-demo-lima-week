#!/usr/bin/env bash
# Prepara Google Cloud una sola vez: APIs, repositorio de imágenes, cuenta de servicio y
# Workload Identity Federation para que GitHub Actions despliegue SIN llaves.
#   uso: scripts/gcp-setup.sh PROJECT_ID GITHUB_REPO [REGION]
#   ej:  scripts/gcp-setup.sh silver-fragment-511420-h3 FabrizioVasquez/free-demo-lima-week
set -euo pipefail

PROJECT_ID="${1:?falta PROJECT_ID}"
REPO="${2:?falta GITHUB_REPO (usuario/repositorio)}"
REGION="${3:-southamerica-west1}"
SA_NAME="github-deployer"
POOL="github"
PROVIDER="github-provider"
SA="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

echo "→ Habilitando APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iamcredentials.googleapis.com \
  iam.googleapis.com cloudresourcemanager.googleapis.com --project "$PROJECT_ID"

echo "→ Repositorio de imágenes"
gcloud artifacts repositories describe brujula --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud artifacts repositories create brujula --repository-format=docker --location "$REGION" --project "$PROJECT_ID"

echo "→ Cuenta de servicio"
gcloud iam service-accounts describe "$SA" --project "$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud iam service-accounts create "$SA_NAME" --display-name "GitHub Actions deployer" --project "$PROJECT_ID"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role "$ROLE" --condition=None --quiet >/dev/null
done

echo "→ Workload Identity Federation (solo tu repo puede usarla)"
gcloud iam workload-identity-pools describe "$POOL" --location global --project "$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$POOL" --location global --display-name "GitHub" --project "$PROJECT_ID"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool "$POOL" --location global --project "$PROJECT_ID" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --workload-identity-pool "$POOL" --location global \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition "assertion.repository=='$REPO'" --project "$PROJECT_ID"
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT_ID" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$REPO" >/dev/null

WIF="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
cat <<OUT

Listo. Guarda estas variables en GitHub (Settings → Secrets and variables → Actions → Variables):
  GCP_PROJECT_ID      = $PROJECT_ID
  GCP_REGION          = $REGION
  GCP_SERVICE_ACCOUNT = $SA
  GCP_WIF_PROVIDER    = $WIF

o, con GitHub CLI:
  gh variable set GCP_PROJECT_ID --body "$PROJECT_ID" --repo $REPO
  gh variable set GCP_REGION --body "$REGION" --repo $REPO
  gh variable set GCP_SERVICE_ACCOUNT --body "$SA" --repo $REPO
  gh variable set GCP_WIF_PROVIDER --body "$WIF" --repo $REPO
OUT
