#!/usr/bin/env bash
# Prepara Google Cloud con MÍNIMO PRIVILEGIO. Es idempotente: puedes volver a ejecutarlo.
#   uso: scripts/gcp-setup.sh PROJECT_ID GITHUB_REPO [REGION]
#   ej:  scripts/gcp-setup.sh silver-fragment-511420-h3 FabrizioVasquez/free-demo-lima-week
#
# Modelo de seguridad:
#   * brujula-runtime  : identidad con la que CORRE la app. No tiene ningún rol: si alguien lograra ejecutar código
#                        dentro del contenedor, no puede leer ni modificar nada más en el proyecto.
#   * github-deployer  : identidad con la que DESPLIEGA GitHub. Solo puede (a) subir imágenes a UN repositorio,
#                        (b) actualizar UN servicio de Cloud Run y (c) usar la identidad de ejecución. Nada más.
#   * Workload Identity Federation: GitHub no guarda llaves; solo tu repo y SOLO la rama main pueden usar el deployer.
set -euo pipefail

PROJECT_ID="${1:?falta PROJECT_ID}"
REPO="${2:?falta GITHUB_REPO (usuario/repositorio)}"
REGION="${3:-us-central1}"
SERVICE="brujula-tech-week"
AR_REPO="brujula"
DEPLOYER="github-deployer"
RUNTIME="brujula-runtime"
POOL="github"
PROVIDER="github-provider"
DEPLOYER_SA="$DEPLOYER@$PROJECT_ID.iam.gserviceaccount.com"
RUNTIME_SA="$RUNTIME@$PROJECT_ID.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
G=(--project "$PROJECT_ID" --quiet)

echo "→ 1/8 APIs necesarias"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com iamcredentials.googleapis.com \
  iam.googleapis.com cloudresourcemanager.googleapis.com "${G[@]}"

echo "→ 2/8 Repositorio de imágenes (tags inmutables: una versión publicada no se puede sobrescribir)"
gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" "${G[@]}" >/dev/null 2>&1 ||
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location "$REGION" --immutable-tags "${G[@]}"

echo "→ 3/8 Cuentas de servicio"
for SA in "$DEPLOYER" "$RUNTIME"; do
  gcloud iam service-accounts describe "$SA@$PROJECT_ID.iam.gserviceaccount.com" "${G[@]}" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$SA" --display-name "$SA" "${G[@]}"
done

echo "→ 4/8 Retirando roles amplios de versiones anteriores de este script (si existen)"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$DEPLOYER_SA" --role "$ROLE" --condition=None --quiet >/dev/null 2>&1 || true
done

echo "→ 5/8 Permisos mínimos del deployer, cada uno sobre UN recurso"
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$REGION" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/artifactregistry.writer "${G[@]}" >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/iam.serviceAccountUser "${G[@]}" >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/serviceusage.serviceUsageConsumer --condition=None --quiet >/dev/null

echo "→ 6/8 Servicio de Cloud Run inicial (imagen de ejemplo) para poder dar permisos sobre ÉL y no sobre todo el proyecto"
gcloud run services describe "$SERVICE" --region "$REGION" "${G[@]}" >/dev/null 2>&1 ||
  gcloud run deploy "$SERVICE" --image us-docker.pkg.dev/cloudrun/container/hello --region "$REGION" \
    --service-account "$RUNTIME_SA" --no-allow-unauthenticated --memory 512Mi --cpu 1 --min-instances 0 --max-instances 2 "${G[@]}"
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
  --member "serviceAccount:$DEPLOYER_SA" --role roles/run.developer "${G[@]}" >/dev/null
# Acceso público de solo invocación (la app es pública). Lo concede el propietario aquí; el deployer NO puede cambiar el IAM.
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
  --member allUsers --role roles/run.invoker "${G[@]}" >/dev/null

echo "→ 7/8 Workload Identity Federation: solo $REPO en la rama main"
gcloud iam workload-identity-pools describe "$POOL" --location global "${G[@]}" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$POOL" --location global --display-name "GitHub" "${G[@]}"
COND="assertion.repository=='$REPO' && assertion.ref=='refs/heads/main'"
MAP="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref"
if gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool "$POOL" --location global "${G[@]}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" --workload-identity-pool "$POOL" --location global \
    --attribute-mapping "$MAP" --attribute-condition "$COND" "${G[@]}"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --workload-identity-pool "$POOL" --location global \
    --issuer-uri "https://token.actions.githubusercontent.com" --attribute-mapping "$MAP" --attribute-condition "$COND" "${G[@]}"
fi
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$REPO" "${G[@]}" >/dev/null

echo "→ 8/8 Verificación: ¿qué roles tiene cada cuenta a nivel de proyecto?"
for SA in "$DEPLOYER_SA" "$RUNTIME_SA"; do
  echo "  $SA:"
  gcloud projects get-iam-policy "$PROJECT_ID" --flatten="bindings[].members" --filter="bindings.members:serviceAccount:$SA" \
    --format="value(bindings.role)" | sed 's/^/    - /' || true
done

WIF="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER"
cat <<OUT

Listo. Variables de GitHub (Settings → Secrets and variables → Actions → Variables):
  GCP_PROJECT_ID      = $PROJECT_ID
  GCP_REGION          = $REGION
  GCP_SERVICE_ACCOUNT = $DEPLOYER_SA
  GCP_WIF_PROVIDER    = $WIF
OUT
