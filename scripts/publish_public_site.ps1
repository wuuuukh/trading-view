param(
    [string]$PublishDir = "C:\Users\User\Desktop\Trading View Web Publish",
    [switch]$SkipDataUpdate
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "publish_public_site.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)
    $Line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $Line -Encoding utf8
    Write-Host $Line
}

function Invoke-Git {
    param(
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [Parameter(Mandatory=$true)][string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & git @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

Write-Log "Starting public site publish."
Write-Log "Private root: $Root"
Write-Log "Publish dir: $PublishDir"

if (!(Test-Path -LiteralPath $PublishDir)) {
    throw "Publish directory not found: $PublishDir"
}

if (!$SkipDataUpdate) {
    Write-Log "Running full trading data update."
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\update_all.ps1")
}
else {
    Write-Log "Skipping trading data update."
}

$PublicHtml = Join-Path $Root "docs\index.html"
if (!(Test-Path -LiteralPath $PublicHtml)) {
    $PublicHtml = Join-Path $Root "index.html"
}
if (!(Test-Path -LiteralPath $PublicHtml)) {
    throw "Public index.html source not found."
}

Copy-Item -LiteralPath $PublicHtml -Destination (Join-Path $PublishDir "index.html") -Force
Set-Content -LiteralPath (Join-Path $PublishDir ".nojekyll") -Value "" -Encoding ascii

$ReadmePath = Join-Path $PublishDir "README.md"
if (!(Test-Path -LiteralPath $ReadmePath)) {
    Set-Content -LiteralPath $ReadmePath -Value "# Trading View`nPublic dashboard only." -Encoding utf8
}

Invoke-Git -WorkingDirectory $PublishDir -Arguments @("status", "--short")
Invoke-Git -WorkingDirectory $PublishDir -Arguments @("add", "index.html", ".nojekyll", "README.md")

Push-Location $PublishDir
try {
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Log "No public website changes to commit."
    }
    else {
        $CommitMessage = "Update public dashboard {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm")
        & git commit -m $CommitMessage
        if ($LASTEXITCODE -ne 0) {
            throw "git commit failed with exit code $LASTEXITCODE"
        }

        & git push origin main
        if ($LASTEXITCODE -ne 0) {
            throw "git push origin main failed with exit code $LASTEXITCODE"
        }

        & git push origin HEAD:gh-pages
        if ($LASTEXITCODE -ne 0) {
            throw "git push origin HEAD:gh-pages failed with exit code $LASTEXITCODE"
        }

        Write-Log "Pushed public website to origin/main and origin/gh-pages."
    }
}
finally {
    Pop-Location
}

Write-Log "Public site publish finished."
