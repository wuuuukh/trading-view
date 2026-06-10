$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath (Join-Path $LogDir "intraday_paper_monitor.log") -Value "[$Stamp] start" -Encoding utf8

python scripts\intraday_paper_monitor.py --execute-paper `
  1>> (Join-Path $LogDir "intraday_paper_monitor.stdout.log") `
  2>> (Join-Path $LogDir "intraday_paper_monitor.stderr.log")

python scripts\update_tracking_report.py `
  1>> (Join-Path $LogDir "intraday_report_refresh.stdout.log") `
  2>> (Join-Path $LogDir "intraday_report_refresh.stderr.log")

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_static_site.ps1 `
  1>> (Join-Path $LogDir "intraday_export.stdout.log") `
  2>> (Join-Path $LogDir "intraday_export.stderr.log")

$Done = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath (Join-Path $LogDir "intraday_paper_monitor.log") -Value "[$Done] done" -Encoding utf8
