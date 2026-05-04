$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Site = Join-Path $Root "site"
$SiteReports = Join-Path $Site "reports"
$Docs = Join-Path $Root "docs"
$DocsReports = Join-Path $Docs "reports"

New-Item -ItemType Directory -Force -Path $Site | Out-Null
New-Item -ItemType Directory -Force -Path $SiteReports | Out-Null
New-Item -ItemType Directory -Force -Path $Docs | Out-Null
New-Item -ItemType Directory -Force -Path $DocsReports | Out-Null

Copy-Item -LiteralPath (Join-Path $Root "trading-record.html") -Destination (Join-Path $Site "index.html") -Force
Copy-Item -LiteralPath (Join-Path $Root "trading-record.html") -Destination (Join-Path $Site "trading-record.html") -Force
Copy-Item -LiteralPath (Join-Path $Root "trading-record.html") -Destination (Join-Path $Site "AI_Agent_Trading_System_Report.html") -Force
Copy-Item -LiteralPath (Join-Path $Root "trading-record.html") -Destination (Join-Path $Docs "index.html") -Force
Copy-Item -LiteralPath (Join-Path $Root "trading-record.html") -Destination (Join-Path $Docs "trading-record.html") -Force
Copy-Item -LiteralPath (Join-Path $Root "trading-record.html") -Destination (Join-Path $Docs "AI_Agent_Trading_System_Report.html") -Force

$WebRoot = Join-Path $Root "web"
if (Test-Path -LiteralPath $WebRoot) {
    Copy-Item -LiteralPath (Join-Path $WebRoot "index.html") -Destination (Join-Path $Site "dashboard.html") -Force
    Copy-Item -LiteralPath (Join-Path $WebRoot "index.html") -Destination (Join-Path $Docs "dashboard.html") -Force
    Copy-Item -LiteralPath (Join-Path $WebRoot "styles.css") -Destination (Join-Path $Site "styles.css") -Force
    Copy-Item -LiteralPath (Join-Path $WebRoot "styles.css") -Destination (Join-Path $Docs "styles.css") -Force
    Copy-Item -LiteralPath (Join-Path $WebRoot "app.js") -Destination (Join-Path $Site "app.js") -Force
    Copy-Item -LiteralPath (Join-Path $WebRoot "app.js") -Destination (Join-Path $Docs "app.js") -Force
}

$ReportFiles = @(
    "tracking_summary.md",
    "tracking_log.csv",
    "scan.md",
    "scan.csv",
    "scan.json",
    "paper_scan.md",
    "paper_scan.csv",
    "paper_scan.json",
    "backtest_compare.md",
    "backtest_compare.csv",
    "backtest_compare.json",
    "next_week_projection.md",
    "next_week_projection.csv",
    "next_week_projection.json"
)

foreach ($File in $ReportFiles) {
    $Source = Join-Path $Root "reports\$File"
    if (Test-Path -LiteralPath $Source) {
        Copy-Item -LiteralPath $Source -Destination (Join-Path $SiteReports $File) -Force
        Copy-Item -LiteralPath $Source -Destination (Join-Path $DocsReports $File) -Force
    }
}

Set-Content -LiteralPath (Join-Path $Site ".nojekyll") -Value "" -Encoding ascii
Set-Content -LiteralPath (Join-Path $Docs ".nojekyll") -Value "" -Encoding ascii

Write-Host "Exported static website to $Site"
Write-Host "Exported GitHub Pages website to $Docs"
