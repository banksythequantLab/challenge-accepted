# End-to-end smoke test against the DEPLOYED service.
#
# Deploying successfully is not the same as the agents working. This actually creates a
# session and sends one turn, which exercises Vertex model auth via the Cloud Run
# service account -- a path that never runs locally, where an API key is used instead.

$url = "https://challenge-accepted-xk3m7ygefa-uc.a.run.app"
$app = "challenge_accepted"
$user = "smoketest"
$session = "s" + (Get-Random -Maximum 999999)

Write-Host "creating session ..." -ForegroundColor Cyan
try {
    $body = @{ state = @{ user_id = $user; group_id = "grp_smoke" } } | ConvertTo-Json
    $r = Invoke-WebRequest -Uri "$url/apps/$app/users/$user/sessions/$session" `
        -Method Post -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 60
    Write-Host "  session created: $($r.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "  FAILED $($_.Exception.Response.StatusCode.value__): $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "sending one turn (this invokes Gemini via the Cloud Run service account) ..." -ForegroundColor Cyan
$payload = @{
    appName    = $app
    userId     = $user
    sessionId  = $session
    newMessage = @{ role = "user"; parts = @(@{ text = "I want to run a 10k in October." }) }
} | ConvertTo-Json -Depth 8

try {
    $r = Invoke-WebRequest -Uri "$url/run" -Method Post -Body $payload `
        -ContentType "application/json" -UseBasicParsing -TimeoutSec 180
    $txt = $r.Content
    Write-Host "  http $($r.StatusCode), $($txt.Length) bytes" -ForegroundColor Green
    Write-Host ""
    if ($txt -match '"text"\s*:\s*"([^"]{20,400})') {
        Write-Host "AGENT SAID:" -ForegroundColor Green
        Write-Host "  $($matches[1])"
    } else {
        Write-Host "no text part found; first 500 bytes:" -ForegroundColor Yellow
        Write-Host $txt.Substring(0, [Math]::Min(500, $txt.Length))
    }
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Write-Host "  FAILED http $code" -ForegroundColor Red
    try {
        $s = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
        Write-Host $s.ReadToEnd().Substring(0, 600) -ForegroundColor Red
    } catch { Write-Host $_.Exception.Message -ForegroundColor Red }
    exit 1
}
