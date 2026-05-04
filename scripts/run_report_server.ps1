$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = (Get-Command python).Source
$ServerScript = Join-Path $Root "scripts\serve_report.py"

Set-Location -LiteralPath $Root
& $Python $ServerScript --host 0.0.0.0 --port 8765
