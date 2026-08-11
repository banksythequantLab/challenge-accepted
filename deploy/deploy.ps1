# Deploy Challenge Accepted to Cloud Run.
#
#   .\deploy\deploy.ps1 -ProjectId your-project-id
#
# Requires the Google Cloud CLI. Deploys ONE service: the FastAPI app serves both the
# agent API (/run, /run_sse) and the dashboard (/app), so there is no second hosting
# platform and no CORS to get wrong at 2am.

param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [string]$Region = "us-central1",
    [string]$Service = "challenge-accepted",
    [string]$ModelReasoning = "gemini-3.6-flash",
    [string]$ModelCheap = "gemini-3.5-flash-lite",
    # MUST be "global", not the Cloud Run region. Deploying with us-central1 produced:
    #   404 NOT_FOUND: Publisher model .../locations/us-central1/publishers/google/
    #   models/gemini-3.6-flash was not found or your project does not have access
    # The 3.x Gemini models are served from the global endpoint on Vertex AI. The
    # service still RUNS in $Region; this only sets where the genai client looks.
    [string]$ModelLocation = "global",
    [switch]$KeepWarm   # min-instances=1: use from the day you start rehearsing
)

# NOT "Stop". gcloud writes advisories to STDERR -- e.g.
#   [environment: untagged] Read more to tag: g.co/cloud/project-env-tag.
# and under "Stop" PowerShell promotes native stderr to a TERMINATING error the moment
# the script's streams are redirected. So this:
#     .\deploy\deploy.ps1 -ProjectId x *> deploy.log
# died on line 2 -- on an informational notice -- while the identical interactive run
# worked, and the log it left behind looked like a deploy that was merely slow. An
# unattended deploy that dies quietly is worse than one that fails loudly.
# Correctness here rests on explicit $LASTEXITCODE checks and `throw`, both of which
# work regardless of this setting.
$ErrorActionPreference = "Continue"
$PSNativeCommandUseErrorActionPreference = $false   # PowerShell 7.3+; ignored on 5.1

# Resolve gcloud explicitly. A detached process does not reliably inherit a User PATH
# that was set in the current session, and the SDK here lives at a non-standard root.
$gcloud = (Get-Command gcloud -ErrorAction SilentlyContinue).Source
if (-not $gcloud) { $gcloud = "B:\tools\google-cloud-sdk\bin\gcloud.cmd" }
if (-not (Test-Path $gcloud)) {
    throw "gcloud not found. Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install"
}
# Credentials live off C:\ -- see the comment in bin\gcloud.cmd for why.
if (-not $env:CLOUDSDK_CONFIG) { $env:CLOUDSDK_CONFIG = "B:\tools\gcloud-config" }
Write-Host "==> gcloud: $gcloud" -ForegroundColor DarkGray

Write-Host "==> Project: $ProjectId  Region: $Region" -ForegroundColor Cyan
& $gcloud config set project $ProjectId | Out-Null

Write-Host "==> Enabling APIs (idempotent)" -ForegroundColor Cyan
& $gcloud services enable `
    run.googleapis.com `
    firestore.googleapis.com `
    aiplatform.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com
if ($LASTEXITCODE -ne 0) {
    throw "Enabling APIs failed (gcloud exit $LASTEXITCODE). Nothing was deployed."
}

# Firestore must exist before the app writes to it. Creating a database twice is an
# error, not a no-op, so check first.
# Check the exit code, not a catch block: native stderr only becomes a catchable
# exception under some combinations of PowerShell version and stream redirection, so
# try/catch here was quietly unreliable -- on a fresh project it could report the
# database as existing and skip creating it.
& $gcloud firestore databases describe --database="(default)" 2>$null | Out-Null
$dbExists = ($LASTEXITCODE -eq 0)

if (-not $dbExists) {
    Write-Host "==> Creating Firestore database (Native mode, $Region)" -ForegroundColor Cyan
    & $gcloud firestore databases create --location=$Region --type=firestore-native
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
    "GOOGLE_CLOUD_LOCATION=$ModelLocation",
    "CA_MODEL_REASONING=$ModelReasoning",
    "CA_MODEL_CHEAP=$ModelCheap"
) -join ","

Write-Host "==> Deploying $Service" -ForegroundColor Cyan
& $gcloud run deploy $Service `
    --source . `
    --region $Region `
    --allow-unauthenticated `
    --memory 2Gi `
    --cpu 2 `
    --timeout 3600 `
    --min-instances $minInstances `
    --max-instances 10 `
    --set-env-vars $envVars

# gcloud is a native executable, and PowerShell does NOT throw on a non-zero exit from
# one -- $ErrorActionPreference="Stop" only governs cmdlets. The first version of this
# script printed "==> Deployed" over a PERMISSION_DENIED build failure. Check explicitly.
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "==> DEPLOY FAILED (gcloud exit $LASTEXITCODE). Nothing was deployed." -ForegroundColor Red
    Write-Host "If the build failed on IAM, the default compute service account needs:" -ForegroundColor Yellow
    Write-Host "  gcloud projects add-iam-policy-binding $ProjectId ``"
    Write-Host "    --member serviceAccount:<PROJECT_NUMBER>-compute@developer.gserviceaccount.com ``"
    Write-Host "    --role roles/cloudbuild.builds.builder"
    exit 1
}

$url = & $gcloud run services describe $Service --region $Region --format "value(status.url)"
if ($LASTEXITCODE -ne 0 -or -not $url) {
    Write-Host "==> Deploy reported success but the service has no URL. Investigate." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==> Deployed" -ForegroundColor Green
Write-Host "    dashboard : $url/app"
Write-Host "    agent UI  : $url/"
Write-Host "    health    : $url/api/healthz"
Write-Host ""
Write-Host "Verify the store actually switched to Firestore:" -ForegroundColor Yellow
Write-Host "    curl $url/api/healthz     # expect  store=firestore"
Write-Host ""
Write-Host "If it still says memory, the app fell back silently -- check that the"  -ForegroundColor Yellow
Write-Host "service account has roles/datastore.user."  -ForegroundColor Yellow
