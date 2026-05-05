# Trading View Project State

- Recorded at: 2026-05-05
- Local project path: `C:\Users\User\Desktop\Trading View`
- GitHub repo: `https://github.com/wuuuukh/trading-view`
- Live website: `https://wuuuukh.github.io/trading-view/`
- GitHub Pages source: `main` branch, `/docs` folder
- Main report page: `AI Agent Trading System Report`
- Public entry file: `docs/index.html`
- Direct report URL: `https://wuuuukh.github.io/trading-view/`

## Update Flow

- GitHub Actions workflow: `.github/workflows/update-site.yml`
- Automatic update job: `Update trading website`
- Manual trigger path: GitHub repo -> Actions -> Update trading website -> Run workflow
- Update script: `scripts/update_all.ps1`
- Report generator: `scripts/update_tracking_report.py`
- Static export script: `scripts/export_static_site.ps1`
- GitHub Pages keeps the same URL after every automatic update.

## Custom Watchlist

- Custom watchlist config: `config/custom_watchlist.yaml`
- Current priority custom watchlist stock: `6205 詮欣`
- Human-readable watchlist note: `records/watchlist/6205.md`
- Website report column: `自選股`
- Expected display value: `6205 詮欣`
- Important note: do not hard-code watchlist labels in generated HTML. The report generator reads `config/custom_watchlist.yaml`.

## Next Read Instructions

When resuming this project, read these files first:

1. `records/project_state.md`
2. `config/custom_watchlist.yaml`
3. `records/watchlist/6205.md`
4. `.github/workflows/update-site.yml`
5. `scripts/update_tracking_report.py`
