# Rename the product's DISPLAY name across the repo.
#
#   .\scripts\rename.ps1 -NewName "Jigwright" -NewDomain "jigwright.app"          # dry run
#   .\scripts\rename.ps1 -NewName "Jigwright" -NewDomain "jigwright.app" -Apply   # write
#
# SCOPE, deliberately narrow: this changes text a human reads -- README, prompts, the
# UI header and <title>, docs, seed data. It does NOT rename the Python package
# `challenge_accepted`, because that would touch every import, the ADK agent-discovery
# path, and the Dockerfile COPY, for zero judge-visible benefit three weeks before a
# deadline. The package name is invisible; the product name is not.
#
# Rename the GitHub repo separately (gh repo rename <new>), then update the remote:
#   git remote set-url origin https://github.com/<you>/<new>.git

param(
    [Parameter(Mandatory = $true)][string]$NewName,
    [string]$NewDomain = "",
    [string]$OldName = "Challenge Accepted",
    [string]$OldDomain = "challengeaccepted.app",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

$include = @("*.py", "*.md", "*.html", "*.ps1", "*.txt", "*.example", "Dockerfile")
$skipDirs = @("\.venv\", "\.git\", "__pycache__", "\.pytest_cache\")

$files = Get-ChildItem -Path $repo -Recurse -File -Include $include |
    Where-Object { $p = $_.FullName; -not ($skipDirs | Where-Object { $p -like "*$_*" }) } |
    # Exclude THIS script. It carries "Challenge Accepted" as the -OldName default, so
    # a rename run would rewrite its own default and make a second run a no-op against
    # the wrong string -- silently, and only noticed when a rename half-applies.
    Where-Object { $_.FullName -ne $PSCommandPath }

$totalFiles = 0
$totalHits = 0

foreach ($f in $files) {
    $text = Get-Content -Raw -LiteralPath $f.FullName
    if ($null -eq $text) { continue }
    $orig = $text

    # Longest/most specific first, so "challengeaccepted.app" is not half-eaten by the
    # bare-name rule below.
    if ($NewDomain) { $text = $text -replace [regex]::Escape($OldDomain), $NewDomain }
    $text = $text -replace [regex]::Escape($OldName), $NewName
    $text = $text -replace [regex]::Escape($OldName.ToLower()), $NewName.ToLower()
    $text = $text -replace 'challenge-accepted(?!\.app)', ($NewName.ToLower())

    if ($text -ne $orig) {
        $hits = ([regex]::Matches($orig, [regex]::Escape($OldName))).Count
        $totalFiles++
        $totalHits += $hits
        $rel = $f.FullName.Substring($repo.Length + 1)
        Write-Host ("{0,-52} {1} occurrence(s)" -f $rel, $hits) -ForegroundColor Cyan
        if ($Apply) { Set-Content -LiteralPath $f.FullName -Value $text -NoNewline }
    }
}

Write-Host ""
if ($Apply) {
    Write-Host "APPLIED to $totalFiles files ($totalHits name occurrences)." -ForegroundColor Green
    Write-Host "Next:" -ForegroundColor Yellow
    Write-Host "  pytest                                  # nothing should break; names are strings"
    Write-Host "  python scripts\shoot_ui.py              # confirm the header renders"
    Write-Host "  gh repo rename $($NewName.ToLower())"
    Write-Host "  git remote set-url origin https://github.com/<you>/$($NewName.ToLower()).git"
} else {
    Write-Host "DRY RUN: $totalFiles files would change ($totalHits name occurrences)." -ForegroundColor Yellow
    Write-Host "Re-run with -Apply to write." -ForegroundColor Yellow
}
