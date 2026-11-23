#!/bin/bash
# Deploy the Rudo staff dashboard to Google Cloud Run (owner-run; needs explicit approval for production).
#
#   scripts/deploy_cloud_run.sh <gcp-project-id> [region]
#
# - Builds from a CLEAN clone of the pushed branch (never the working folder, so .env, backups/ and local
#   exports can never be uploaded). The Dockerfile contains no secrets.
# - Database logins and other secrets live in Secret Manager; only the dashboard's own service account can
#   read them. Values are piped from the 0600 files in backups/ and are never printed.
# - Browser-safe Supabase settings (URL + publishable key) are plain environment variables.
# Re-running is safe: secrets get a new version only when the local value changed; the service is redeployed.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=${1:?usage: scripts/deploy_cloud_run.sh <gcp-project-id> [region]}
REGION=${2:-europe-west1}
SERVICE=rudo-dashboard
BRANCH=${RUDO_DEPLOY_BRANCH:-supabase-full-migration}
REPO=https://github.com/Samuel04-png/Chatbot.git
SA="$SERVICE@$PROJECT.iam.gserviceaccount.com"

say() { printf '\n==> %s\n' "$1"; }
value() { # value <file> <KEY>: the value on stdout, for piping only (never echoed). Database URLs get the
  # container's certificate path (/app/deploy/certs/prod-supabase.crt) instead of this Mac's path.
  sed -n "s/^$2=//p" "$1" | head -1 | sed -E 's#sslrootcert=[^&]*#sslrootcert=/app/deploy/certs/prod-supabase.crt#'
}
for f in backups/release1-dashboard.env .env; do
  [[ -f "$f" ]] || { echo "missing $f" >&2; exit 1; }
done
[[ "$(stat -f %Lp backups/release1-dashboard.env)" == "600" ]] || { echo 'backups/release1-dashboard.env must be mode 600' >&2; exit 1; }

say "Enabling Cloud Run, Cloud Build, Artifact Registry and Secret Manager on $PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com \
  --project "$PROJECT"

say "Service account for the dashboard (no project-wide roles)"
gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SERVICE" --project "$PROJECT" --display-name "Rudo dashboard runtime"

put_secret() { # put_secret <name> <file> <key>
  local name=$1 file=$2 key=$3 current
  [[ -n "$(value "$file" "$key")" ]] || { echo "  skip $name ($key not set in $file)"; return 0; }
  if ! gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic >/dev/null
  fi
  current=$(gcloud secrets versions access latest --secret "$name" --project "$PROJECT" 2>/dev/null | shasum -a 256 | cut -c1-64 || true)
  if [[ "$current" != "$(value "$file" "$key" | tr -d '\n' | shasum -a 256 | cut -c1-64)" ]]; then
    value "$file" "$key" | tr -d '\n' | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
    echo "  $name: new version"
  else
    echo "  $name: unchanged"
  fi
  gcloud secrets add-iam-policy-binding "$name" --project "$PROJECT" --member "serviceAccount:$SA" \
    --role roles/secretmanager.secretAccessor >/dev/null
}

say "Storing secrets in Secret Manager (values are never printed)"
put_secret rudo-observer-db       backups/release1-dashboard.env RUDO_OBSERVER_DATABASE_URL
put_secret rudo-observer-audit-db backups/release1-dashboard.env RUDO_OBSERVER_AUDIT_DATABASE_URL
put_secret rudo-staff-admin-db    backups/release1-dashboard.env RUDO_STAFF_ADMIN_DATABASE_URL
put_secret rudo-cursor-secret     backups/release1-dashboard.env RUDO_CURSOR_SECRET
put_secret rudo-sender-db         backups/release1-dashboard.env RUDO_SENDER_DATABASE_URL
for s in whatsapp-token whatsapp-phone-number-id; do
  gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1 && gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" \
    --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null || true
done

NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
URL="https://$SERVICE-$NUMBER.$REGION.run.app"
SECRETS="RUDO_OBSERVER_DATABASE_URL=rudo-observer-db:latest,RUDO_OBSERVER_AUDIT_DATABASE_URL=rudo-observer-audit-db:latest"
SECRETS+=",RUDO_STAFF_ADMIN_DATABASE_URL=rudo-staff-admin-db:latest,RUDO_CURSOR_SECRET=rudo-cursor-secret:latest"
REPLIES=false
if gcloud secrets describe rudo-sender-db --project "$PROJECT" >/dev/null 2>&1 \
   && gcloud secrets describe whatsapp-token --project "$PROJECT" >/dev/null 2>&1 \
   && gcloud secrets describe whatsapp-phone-number-id --project "$PROJECT" >/dev/null 2>&1; then
  SECRETS+=",RUDO_SENDER_DATABASE_URL=rudo-sender-db:latest,WHATSAPP_TOKEN=whatsapp-token:latest,WHATSAPP_PHONE_NUMBER_ID=whatsapp-phone-number-id:latest"
  REPLIES=true
fi
ENVS="RUDO_MODE=observer,RUDO_OBSERVER_ALLOW_REMOTE=true,RUDO_OBSERVER_SOURCE_ID=rudo-production"
ENVS+=",RUDO_IDENTITY_PROVIDERS=supabase,RUDO_BROWSER_AUTH=supabase,RUDO_SUPABASE_SESSION_CHECK=true,SUPABASE_GOOGLE_ENABLED=false"
ENVS+=",SUPABASE_URL=$(value .env SUPABASE_URL),SUPABASE_ANON_KEY=$(value .env SUPABASE_ANON_KEY)"
ENVS+=",RUDO_ALLOWED_ORIGIN=$URL,RUDO_TRUST_PROXY=true,FORWARDED_ALLOW_IPS=*,WEB_CONCURRENCY=1,RUDO_THREADS=8"
ENVS+=",RUDO_ENABLE_STAFF_REPLIES=$REPLIES,WHATSAPP_API_VERSION=v19.0"
[[ "$(value .env SUPABASE_ANON_KEY)" == sb_publishable_* ]] || { echo 'SUPABASE_ANON_KEY must be the publishable key' >&2; exit 1; }

say "Clean clone of $BRANCH (nothing from this folder is uploaded)"
SRC=$(mktemp -d "${TMPDIR:-/tmp}/rudo-deploy.XXXXXX")
trap 'rm -rf -- "$SRC"' EXIT
git clone -q --depth 1 -b "$BRANCH" "$REPO" "$SRC"
printf 'Building commit %s\n' "$(git -C "$SRC" rev-parse --short HEAD)"

say "Deploying $SERVICE to $REGION (staff replies: $REPLIES)"
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --source "$SRC" \
  --service-account "$SA" --allow-unauthenticated --port 8080 \
  --min-instances 0 --max-instances 3 --concurrency 16 --cpu 1 --memory 512Mi --timeout 60 \
  --set-secrets "$SECRETS" --set-env-vars "^@^$(printf '%s' "$ENVS" | tr ',' '@')" --quiet

say "Checking the live service"
curl -fsS "$URL/healthz" && echo
curl -sS "$URL/readyz" && echo
printf '\nRudo dashboard: %s/observer.html\nStaff sign-in:  %s/staff-login.html\n' "$URL" "$URL"
