param(
    [string]$TaskName = "TradingView Daily Public Site Update",
    [string]$At = "18:00",
    [string]$RunAsUser = ""
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$PublishScript = Join-Path $Root "scripts\publish_public_site.ps1"

if (!(Test-Path -LiteralPath $PublishScript)) {
    throw "Publish script not found: $PublishScript"
}

$ResolvedRunAsUser = $RunAsUser
if ([string]::IsNullOrWhiteSpace($ResolvedRunAsUser)) {
    $ResolvedRunAsUser = "{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -WorkingDirectory $Root `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PublishScript`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $ResolvedRunAsUser -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Update private trading data locally, publish only the public dashboard HTML to GitHub Pages." `
    -Force | Out-Null

Enable-ScheduledTask -TaskName $TaskName | Out-Null

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Daily run time: $At"
Write-Host "Script: $PublishScript"
Write-Host "Run as: $ResolvedRunAsUser"
