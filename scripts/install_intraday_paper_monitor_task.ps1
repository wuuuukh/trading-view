param(
    [string]$TaskName = "TradingView Intraday Paper Monitor",
    [string]$StartAt = "09:00",
    [int]$IntervalMinutes = 5,
    [int]$DurationHours = 5,
    [string]$RunAsUser = ""
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$MonitorScript = Join-Path $Root "scripts\run_intraday_paper_monitor.ps1"

if (!(Test-Path -LiteralPath $MonitorScript)) {
    throw "Monitor script not found: $MonitorScript"
}

$ResolvedRunAsUser = $RunAsUser
if ([string]::IsNullOrWhiteSpace($ResolvedRunAsUser)) {
    $ResolvedRunAsUser = "{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME
}

$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$Start = [DateTime]::ParseExact($StartAt, "HH:mm", $null)
$End = $Start.AddHours($DurationHours)
$EndAt = $End.ToString("HH:mm")
$Command = 'schtasks /Create /TN "{0}" /TR "\"{1}\" -NoProfile -ExecutionPolicy Bypass -File \"{2}\"" /SC MINUTE /MO {3} /ST {4} /ET {5} /F' -f `
    $TaskName,
    $PowerShell,
    $MonitorScript,
    $IntervalMinutes,
    $StartAt,
    $EndAt

cmd.exe /c $Command | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "schtasks failed with exit code $LASTEXITCODE"
}

Write-Host "Installed scheduled task: $TaskName"
Write-Host "Start: $StartAt"
Write-Host "End: $EndAt"
Write-Host "Interval minutes: $IntervalMinutes"
Write-Host "Duration hours: $DurationHours"
Write-Host "Script: $MonitorScript"
