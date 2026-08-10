# Deploy MicroGoals to Cloud Run.
#
#   .\deploy\deploy.ps1 -ProjectId your-project-id
#
# Requires the Google Cloud CLI. Deploys ONE service: the FastAPI app serves both the
# agent API (/run, /run_sse) and the dashboard (/app), so there is no second hosting
# platform and no CORS to get wrong at 2am.

param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Service = "microgoals",
    [string]$ModelReasoning = "gemini-3.6-flash",
    [string]$ModelCheap = "gemini-3.5-flash-lite",
    [switch]$KeepWarm   # min-instances=1: use from the day you start rehearsing
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw "gcloud not found. Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install"
}

Write-Host "==> Project: $ProjectId  Region: $Region" -ForegroundColor Cyan
gcloud config set project $ProjectId | Out-Null

Write-Host "==> Enabling APIs (idempotent)" -ForegroundColor Cyan
gcloud services enable `
    run.googleapis.com `
    firestore.googleapis.com `
    aiplatform.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com

# Firestore must exist before the app writes to it. Creating a database twice is an
# error, not a no-op, so check first.
$dbExists = $true
try { gcloud firestore databases describe --database="(default)" 2>$null | Out-Null }
catch { $dbExists = $false }

if (-not $dbExists) {
    Write-Host "==> Creating Firestore database (Native mode, $Region)" -ForegroundColor Cyan
    gcloud firestore databases create --location=$Region --type=firestore-native
} else {
    Write-Host "==> Firestore database already exists" -ForegroundColor DarkGray
}

$minInstances = if ($KeepWarm) { "1" } else { "0" }
if ($KeepWarm) {
    Write-Host "==> min-instances=1 (cold starts will not eat your demo)" -ForegroundColor Yellow
}

$envVars = @(
    "GOOGLE_GENAI_USE_VERTEXAI=TRUE",
    "GOOGLE_CLOUD_PROJECT=$ProjectId",
    "GOOGLE_CLOUD_LOCATION=$Region",
    "CA_MODEL_REASONING=$ModelReasoning",
    "CA_MODEL_CHEAP=$ModelCheap"
) -join ","

Write-Host "==> Deploying $Service" -ForegroundColor Cyan
gcloud run deploy $Service `
    --source . `
    --region $Region `
    --allow-unauthenticated `
    --memory 2Gi `
    --cpu 2 `
    --timeout 3600 `
    --min-instances $minInstances `
    --max-instances 10 `
    --set-env-vars $envVars

$url = gcloud run services describe $Service --region $Region --format "value(status.url)"

Write-Host ""
Write-Host "==> Deployed" -ForegroundColor Green
Write-Host "    dashboard : $url/app"
Write-Host "    agent UI  : $url/"
Write-Host "    health    : $url/healthz"
Write-Host ""
Write-Host "Verify the store actually switched to Firestore:" -ForegroundColor Yellow
Write-Host "    curl $url/healthz     # expect  store=firestore"
Write-Host ""
Write-Host "If it still says memory, the app fell back silently -- check that the"  -ForegroundColor Yellow
Write-Host "service account has roles/datastore.user."  -ForegroundColor Yellow
