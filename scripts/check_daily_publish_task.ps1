param(
    [string]$TaskName = "TradingView Daily Public Site Update"
)

$ErrorActionPreference = "Stop"

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $Task) {
    Write-Host "Scheduled task not found: $TaskName"
    exit 1
}

$Info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host "Task: $TaskName"
Write-Host ("State: {0}" -f $Task.State)
Write-Host ("LastRunTime: {0}" -f $Info.LastRunTime)
Write-Host ("LastTaskResult: {0}" -f $Info.LastTaskResult)
Write-Host ("NextRunTime: {0}" -f $Info.NextRunTime)

Write-Host ""
Write-Host "Triggers:"
$Task.Triggers | Format-List * | Out-String | Write-Host

Write-Host "Actions:"
$Task.Actions | Format-List * | Out-String | Write-Host

