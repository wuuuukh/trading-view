param(
    [string]$TaskName = "TradingView Daily Public Site Update"
)

$ErrorActionPreference = "Stop"

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $Existing) {
    Write-Host "Scheduled task not found: $TaskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Uninstalled scheduled task: $TaskName"

