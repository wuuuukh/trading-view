$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $Root

$Symbols = @("4958", "8046", "3037", "2313", "6205")
$Today = Get-Date -Format "yyyy-MM-dd"

python scripts\update_ohlcv_tw.py @Symbols --months 18 --end $Today --out data\ohlcv
python -m trading_agent.cli scan --ohlcv data\ohlcv --out reports
python -m trading_agent.cli paper --ohlcv data\ohlcv --out reports
python -m trading_agent.cli backtest --ohlcv data\ohlcv --out reports
python -m trading_agent.cli project --capital 1000000 --out reports
python scripts\update_tracking_report.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_static_site.ps1

Write-Host "Updated data, reports, tracking log, and HTML."
