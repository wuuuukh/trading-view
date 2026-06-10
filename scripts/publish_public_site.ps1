param(
    [string]$PublishDir = "C:\Users\User\Desktop\Trading View Web Publish",
    [switch]$SkipDataUpdate,
    [int]$DataUpdateTimeoutMinutes = 8
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LogDir = Join-Path $Root "logs"
$LogFile = Join-Path $LogDir "publish_public_site.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# In some sandboxed environments, the current user cannot write to the default global gitconfig
# path under another user's profile. Use a repo-local global config file instead.
$env:GIT_CONFIG_GLOBAL = Join-Path $Root ".gitconfig.codex"

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

function Ensure-GitSafeDirectory {
    param([Parameter(Mandatory=$true)][string]$Path)

    try {
        & git config --global --add safe.directory $Path | Out-Null
    }
    catch {
        # best effort; continue
    }
}

function Stop-ProcessTree {
    param([Parameter(Mandatory=$true)][int]$ProcessId)

    $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($Child in $Children) {
        Stop-ProcessTree -ProcessId ([int]$Child.ProcessId)
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Invoke-DataUpdate {
    $UpdateScript = Join-Path $Root "scripts\update_all.ps1"
    $StdOut = Join-Path $LogDir "update_all.stdout.log"
    $StdErr = Join-Path $LogDir "update_all.stderr.log"
    $Timeout = [TimeSpan]::FromMinutes([Math]::Max(1, $DataUpdateTimeoutMinutes))
    $PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`""

    Write-Log "Running full trading data update with timeout ${DataUpdateTimeoutMinutes}m."
    $Process = Start-Process `
        -FilePath $PowerShell `
        -ArgumentList $Arguments `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $StdOut `
        -RedirectStandardError $StdErr `
        -PassThru `
        -WindowStyle Hidden

    if (!$Process.WaitForExit([int]$Timeout.TotalMilliseconds)) {
        Write-Log "WARNING: Full trading data update timed out; stopping process tree."
        Stop-ProcessTree -ProcessId $Process.Id
        return $false
    }

    $Process.Refresh()
    if ($Process.ExitCode -ne 0) {
        Write-Log "WARNING: Full trading data update failed with exit code $($Process.ExitCode)."
        return $false
    }

    Write-Log "Full trading data update completed."
    return $true
}

function Invoke-ReportFallback {
    Write-Log "Running report fallback from existing data."
    Push-Location $Root
    try {
        & python scripts\update_tracking_report.py
        if ($LASTEXITCODE -ne 0) {
            throw "python scripts\update_tracking_report.py failed with exit code $LASTEXITCODE"
        }

        & powershell -NoProfile -ExecutionPolicy Bypass -File scripts\export_static_site.ps1
        if ($LASTEXITCODE -ne 0) {
            throw "scripts\export_static_site.ps1 failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
    Write-Log "Report fallback completed."
}

Write-Log "Starting public site publish."
Write-Log "Private root: $Root"
Write-Log "Publish dir: $PublishDir"

function Test-DirectoryWritable {
    param([Parameter(Mandatory=$true)][string]$Path)

    try {
        $TestFile = Join-Path $Path (".__writetest_{0}.tmp" -f ([Guid]::NewGuid().ToString("N")))
        Set-Content -LiteralPath $TestFile -Value "ok" -Encoding ascii
        Remove-Item -LiteralPath $TestFile -Force
        return $true
    }
    catch {
        return $false
    }
}

$RequestedPublishDir = $PublishDir

if (!(Test-Path -LiteralPath $PublishDir)) {
    throw "Publish directory not found: $PublishDir"
}

Ensure-GitSafeDirectory -Path $Root
Ensure-GitSafeDirectory -Path $RequestedPublishDir

if (!(Test-DirectoryWritable -Path $PublishDir)) {
    $FallbackPublishDir = Join-Path $Root "Web Publish"
    Write-Log "WARNING: Publish directory is not writable: $PublishDir"
    Write-Log "WARNING: Falling back to: $FallbackPublishDir"

    New-Item -ItemType Directory -Force -Path $FallbackPublishDir | Out-Null
    $PublishDir = $FallbackPublishDir
}

Ensure-GitSafeDirectory -Path $PublishDir

if (!(Test-Path -LiteralPath (Join-Path $PublishDir ".git"))) {
    if ($PublishDir -eq $RequestedPublishDir) {
        throw "Publish directory is not a git repository: $PublishDir"
    }

    Write-Log "Fallback publish dir is not a git repo; cloning origin from requested publish dir."
    $OriginUrl = $null
    try {
        $OriginUrl = (& git -C $RequestedPublishDir remote get-url origin).Trim()
    }
    catch {
        throw "Unable to read origin URL from requested publish directory: $RequestedPublishDir"
    }

    if ([string]::IsNullOrWhiteSpace($OriginUrl)) {
        throw "Origin URL is empty in requested publish directory: $RequestedPublishDir"
    }

    $ExistingItems = @(Get-ChildItem -LiteralPath $PublishDir -Force -ErrorAction SilentlyContinue)
    if ($ExistingItems.Count -gt 0) {
        throw "Fallback publish directory is not empty; cannot safely clone into: $PublishDir"
    }

    Invoke-Git -WorkingDirectory $Root -Arguments @("clone", $OriginUrl, $PublishDir)
    Write-Log "Cloned $OriginUrl into fallback publish dir."
}

if (!$SkipDataUpdate) {
    $DataUpdateOk = Invoke-DataUpdate
    if (!$DataUpdateOk) {
        Invoke-ReportFallback
    }
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
