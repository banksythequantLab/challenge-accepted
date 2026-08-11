# Post-deploy verification. The one question that matters: did Firestore actually
# engage, or did the app silently fall back to the in-memory store?

$g = "B:\tools\google-cloud-sdk\bin\gcloud.cmd"
$env:CLOUDSDK_CONFIG = "B:\tools\gcloud-config"
$svc = "challenge-accepted"
$region = "us-central1"

$url = & $g run services describe $svc --region $region --format "value(status.url)"
Write-Host "service: $url" -ForegroundColor Cyan

Write-Host ""
Write-Host "=== routes (mine) ===" -ForegroundColor Cyan
try {
    $spec = (Invoke-WebRequest "$url/openapi.json" -UseBasicParsing -TimeoutSec 30).Content | ConvertFrom-Json
    $mine = $spec.paths.PSObject.Properties.Name | Where-Object { $_ -like '/api/*' -or $_ -eq '/healthz' -or $_ -eq '/app' }
    if ($mine) { $mine | ForEach-Object { Write-Host "  $_" } } else { Write-Host "  NONE FOUND" -ForegroundColor Red }
} catch { Write-Host "  openapi fetch failed: $_" -ForegroundColor Red }

Write-Host ""
Write-Host "=== endpoint probes ===" -ForegroundColor Cyan
foreach ($p in @("/api/healthz", "/app", "/api/challenges")) {
    try {
        $r = Invoke-WebRequest "$url$p" -UseBasicParsing -TimeoutSec 30
        $body = $r.Content.Substring(0, [Math]::Min(120, $r.Content.Length)) -replace "`r?`n", " "
        Write-Host ("  {0,-18} {1}  {2}" -f $p, $r.StatusCode, $body)
    } catch {
        Write-Host ("  {0,-18} {1}" -f $p, $_.Exception.Response.StatusCode.value__) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Firestore fallback in logs? ===" -ForegroundColor Cyan
$filter = 'resource.type=cloud_run_revision AND resource.labels.service_name=' + $svc
$logs = & $g logging read $filter --limit 200 --format "value(textPayload)" 2>$null
$bad = $logs | Where-Object { $_ -match "FALLING BACK|Firestore requested" }
if ($bad) {
    Write-Host "  FIRESTORE DID NOT ENGAGE:" -ForegroundColor Red
    $bad | Select-Object -First 3 | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
} else {
    Write-Host "  no fallback logged -- Firestore engaged" -ForegroundColor Green
}

$errs = $logs | Where-Object { $_ -match "Traceback|ERROR|Exception" } | Select-Object -First 5
if ($errs) {
    Write-Host ""
    Write-Host "=== other errors in logs ===" -ForegroundColor Yellow
    $errs | ForEach-Object { Write-Host "  $($_.Substring(0,[Math]::Min(160,$_.Length)))" }
}
