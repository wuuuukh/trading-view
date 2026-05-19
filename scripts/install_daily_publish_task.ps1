param(
    [string]$TaskName = "TradingView Daily Public Site Update",
    [string]$At = "16:30"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PublishScript = Join-Path $Root "scripts\publish_public_site.ps1"

if (!(Test-Path -LiteralPath $PublishScript)) {
    throw "Publish script not found: $PublishScript"
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PublishScript`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Update private trading data locally, publish only the public dashboard HTML to GitHub Pages." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Daily run time: $At"
Write-Host "Script: $PublishScript"
