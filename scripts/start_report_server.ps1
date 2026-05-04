$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Port = 8765
$OutLog = Join-Path $Root "reports\report_server.out.log"
$ErrLog = Join-Path $Root "reports\report_server.err.log"
$Python = (Get-Command python).Source
$ServerScript = Join-Path $Root "scripts\serve_report.py"
$Runner = Join-Path $Root "scripts\run_report_server.ps1"

New-Item -ItemType Directory -Force -Path (Join-Path $Root "reports") | Out-Null

$Existing = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "Report server already appears to be listening on port $Port."
    exit 0
}

Start-Process -FilePath "powershell" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$Runner`"") `
    -WorkingDirectory "$Root" `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog

Write-Host "Started report server on port $Port."
