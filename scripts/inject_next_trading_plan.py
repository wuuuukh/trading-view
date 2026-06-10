from __future__ import annotations

import csv
import json
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_FILES = [ROOT / "index.html", ROOT / "docs" / "index.html", ROOT / "site" / "index.html"]
PLAN_PATH = ROOT / "reports" / "next_trading_plan_latest.json"
PAPER_INITIAL_CAPITAL = 10_000.0
MIN_DAILY_VOLUME_SHARES = 500_000
MIN_DAILY_VOLUME_LOTS = 500


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def to_float(value: object, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: object, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def is_low_daily_volume(volume: object) -> bool:
    return to_float(volume, 0.0) < MIN_DAILY_VOLUME_SHARES


def volume_lots(volume: object) -> float:
    return to_float(volume, 0.0) / 1000


def next_weekday(day_text: str) -> str:
    try:
        day = datetime.strptime(day_text, "%Y-%m-%d").date()
    except ValueError:
        day = date.today()
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def latest_paper_trade_file() -> Path | None:
    files = sorted((ROOT / "reports").glob("paper_trade_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def build_account_state(candidates_by_symbol: dict[str, dict[str, object]]) -> dict[str, object]:
    cash = PAPER_INITIAL_CAPITAL
    positions: dict[str, dict[str, object]] = {}
    trade_file = latest_paper_trade_file()
    for row in read_csv_rows(trade_file) if trade_file else []:
        symbol = str(row.get("symbol", "")).strip()
        if not symbol:
            continue
        side = str(row.get("side", "")).lower()
        shares = to_int(row.get("shares"))
        price = to_float(row.get("price"))
        gross = to_float(row.get("gross_amount"), price * shares)
        if side == "buy":
            cash -= gross
        elif side == "sell":
            cash += gross
        position = positions.setdefault(
            symbol,
            {"symbol": symbol, "name": row.get("name") or candidates_by_symbol.get(symbol, {}).get("name", symbol), "shares": 0, "cost_basis": 0.0},
        )
        old_shares = to_int(position["shares"])
        old_cost = to_float(position["cost_basis"])
        if side == "buy":
            new_shares = old_shares + shares
            position["cost_basis"] = ((old_shares * old_cost) + gross) / new_shares if new_shares else 0.0
            position["shares"] = new_shares
        elif side == "sell":
            position["shares"] = max(0, old_shares - shares)

    open_positions = []
    position_value = 0.0
    unrealized_pnl = 0.0
    for symbol, position in positions.items():
        shares = to_int(position["shares"])
        if shares <= 0:
            continue
        latest = to_float(candidates_by_symbol.get(symbol, {}).get("latest_price"), to_float(position["cost_basis"]))
        cost = to_float(position["cost_basis"])
        value = latest * shares
        pnl = (latest - cost) * shares
        position_value += value
        unrealized_pnl += pnl
        open_positions.append(
            {
                "symbol": symbol,
                "name": position["name"],
                "shares": shares,
                "cost_basis": round(cost, 2),
                "latest_price": round(latest, 2),
                "market_value": round(value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pct": round((latest - cost) / cost * 100, 2) if cost else 0.0,
                "status": "持有，一定盯盤；依日3MA/8MA與週/月3MA交會管理",
            }
        )
    total_assets = cash + position_value
    return {
        "initial_capital": PAPER_INITIAL_CAPITAL,
        "cash": round(cash, 2),
        "position_value": round(position_value, 2),
        "total_assets": round(total_assets, 2),
        "realized_pnl": 0.0,
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_pnl": round(total_assets - PAPER_INITIAL_CAPITAL, 2),
        "capital_usage_pct": round(position_value / total_assets * 100, 2) if total_assets else 0.0,
        "positions": open_positions,
    }


def ma_from_ohlcv(symbol: str) -> dict[str, float]:
    path = ROOT / "data" / "ohlcv" / f"{symbol}.csv"
    rows = read_csv_rows(path)
    closes = [to_float(row.get("close")) for row in rows if row.get("close") not in ("", None)]
    daily3 = sum(closes[-3:]) / 3 if len(closes) >= 3 else 0.0
    daily8 = sum(closes[-8:]) / 8 if len(closes) >= 8 else 0.0
    weeks: dict[tuple[int, int], tuple[datetime, float]] = {}
    months: dict[tuple[int, int], tuple[datetime, float]] = {}
    for row in rows:
        try:
            d = datetime.strptime(str(row.get("timestamp") or row.get("date")), "%Y-%m-%d")
        except ValueError:
            continue
        close = to_float(row.get("close"))
        weeks[d.isocalendar()[:2]] = (d, close)
        months[(d.year, d.month)] = (d, close)
    weekly = [close for _, close in sorted(weeks.values(), key=lambda item: item[0])]
    monthly = [close for _, close in sorted(months.values(), key=lambda item: item[0])]
    return {
        "daily3": round(daily3, 2),
        "daily8": round(daily8, 2),
        "weekly3": round(sum(weekly[-3:]) / 3, 2) if len(weekly) >= 3 else 0.0,
        "monthly3": round(sum(monthly[-3:]) / 3, 2) if len(monthly) >= 3 else 0.0,
    }


def support_range(symbol: str, ma: dict[str, float]) -> str:
    values = [ma.get("weekly3", 0.0), ma.get("monthly3", 0.0), ma.get("daily3", 0.0)]
    values = [value for value in values if value > 0]
    if not values:
        return "-"
    return f"{min(values):.2f} - {max(values):.2f}"


def holding_plan(position: dict[str, object]) -> dict[str, object]:
    symbol = str(position["symbol"])
    ma = ma_from_ohlcv(symbol)
    shares = to_int(position.get("shares"))
    half_shares = max(1, shares // 2) if shares else 0
    latest = to_float(position.get("latest_price"))
    add_shares = int(1500 // latest) if latest else 0
    return {
        **position,
        "scenarios": [
            {
                "title": "情境一：開盤跌破日K 3MA",
                "condition": f"開盤價低於日K 3MA {fmt(ma['daily3'])}，不等收盤確認。",
                "action": f"立即出售 1/2，約 {half_shares} 股；剩餘部位改用日K 8MA {fmt(ma['daily8'])} 防守。",
            },
            {
                "title": "情境二：強勢續攻",
                "condition": f"開盤站穩日K 3MA {fmt(ma['daily3'])}，且5K續紅、沒有爆量黑K。",
                "action": f"續抱 {shares} 股，不追高加碼；若回測不破再評估。",
            },
            {
                "title": "情境三：回測攻擊線",
                "condition": f"回測日K 3MA {fmt(ma['daily3'])} 或週/月3MA交會 {support_range(symbol, ma)}，量縮止跌、5K 轉強。",
                "action": f"可加碼約 1500，約 {add_shares} 股；多檔同時觸發時先排序。",
            },
            {
                "title": "情境四：盤中跌破日K 3MA",
                "condition": f"開盤未破，但盤中跌破日K 3MA {fmt(ma['daily3'])} 且無法快速站回。",
                "action": f"先賣 1/2，約 {half_shares} 股；若再跌破日K 8MA {fmt(ma['daily8'])} 則做全出防守。",
            },
            {
                "title": "情境五：爆量開高後轉黑",
                "condition": "開高但連續 5K 放量黑K，追價失敗。",
                "action": "不追、不加碼，等下一次回測支撐。",
            },
        ],
    }


def symbol_plan(item: dict[str, object], cash: float) -> dict[str, object]:
    symbol = str(item.get("symbol"))
    name = str(item.get("name") or symbol)
    price = to_float(item.get("latest_price"))
    high = to_float(item.get("latest_high"), price)
    ma = ma_from_ohlcv(symbol)
    budget = min(2000.0, cash)
    volume = item.get("volume")
    low_volume = is_low_daily_volume(volume)
    trigger = ma["daily3"] or price
    status = "盤中同步盯；符合條件即動態升級"
    if symbol == "6770":
        status = "操作組，但週/月爆量不追"
    elif symbol == "2492":
        status = "特殊規則股，非最後關緊閉日不追"
    elif item.get("group_assignment") == "觀察組":
        status = "觀察組，站回日3MA或週/月3MA交會可動態升級"
    if low_volume:
        status = f"日成交量約 {fmt(volume_lots(volume), 0)} 張，低於 {MIN_DAILY_VOLUME_LOTS} 張，不操作"
    scenarios = [
        {
            "title": "情境一：站回日K 3MA",
            "condition": f"盤中站回日K 3MA {fmt(ma['daily3'])}，5K 紅K確認且 60K MACD 不轉弱。",
            "action": "直接拉進操作組判斷；依剩餘現金與訊號品質小買。",
        },
        {
            "title": "情境二：回測週/月3MA交會",
            "condition": f"回測 {support_range(symbol, ma)} 不破，尤其回撤月K 3MA 時直接視為承接買點。",
            "action": "依新規則直接買入；不必等待5K轉紅，但仍要控管持股上限與現金。",
        },
        {
            "title": "情境三：跌破日K 8MA",
            "condition": f"跌破日K 8MA {fmt(ma['daily8'])} 且站不回。",
            "action": "不買，轉防守/淘汰。",
        },
    ]
    if symbol == "6770":
        scenarios[0]["action"] = "照使用者規則不追，記錄為等待次週回撤月K 3MA。"
    if symbol == "2492":
        scenarios = [
            {"title": "情境一：不是最後關緊閉日", "condition": "即使續漲，也沒有確認是最後一日。", "action": "不追，僅觀察。"},
            {"title": "情境二：最後關緊閉日且續強", "condition": "若確認為最後關緊閉日，且 13:15 前價格持續上漲。", "action": "依使用者特殊規則，13:15 現價買入，股數依剩餘現金控管。"},
            {"title": "情境三：跌破日3MA", "condition": f"跌破日K 3MA {fmt(ma['daily3'])} 且站不回。", "action": "特殊買入條件取消。"},
        ]
    if low_volume:
        scenarios = [
            {
                "title": "情境一：量能不足",
                "condition": f"日成交量約 {fmt(volume_lots(volume), 0)} 張，低於新增門檻 {MIN_DAILY_VOLUME_LOTS} 張。",
                "action": "不進場；即使站回日3MA或回測週/月3MA交會，也只觀察不買。",
            },
            {
                "title": "情境二：量能恢復",
                "condition": f"下一個完整交易日成交量重新大於 {MIN_DAILY_VOLUME_LOTS} 張，且符合日3MA/週月3MA交會與5K/60K確認。",
                "action": "才重新納入操作排序。",
            },
            {
                "title": "情境三：持續低量",
                "condition": f"連續維持低於 {MIN_DAILY_VOLUME_LOTS} 張。",
                "action": "不主動追蹤買點，週篩時降級或淘汰。",
            },
        ]
    return {
        "symbol": symbol,
        "name": name,
        "latest_price": price,
        "latest_high": high,
        "key_level": trigger,
        "trigger_price": trigger,
        "score": item.get("score"),
        "pattern_type": item.get("pattern_type"),
        "volume_ratio": item.get("volume_ratio"),
        "volume": volume,
        "volume_lots": round(volume_lots(volume), 2),
        "volume_gate": "blocked_under_500_lots" if low_volume else "pass",
        "ma3": ma["daily3"],
        "ma8": ma["daily8"],
        "budget_cap": round(budget, 2),
        "rough_budget_low": round(min(1000.0, cash), 2),
        "rough_budget_high": round(budget, 2),
        "rough_shares_low": int(min(1000.0, cash) // price) if price else 0,
        "rough_shares_high": int(budget // price) if price else 0,
        "entry_status": status,
        "sizing_formula": "日成交量低於500張不操作；通過量能門檻後，盤中全部盯盤，觀察組符合日3MA站回或週/月3MA交會時，直接動態升操作組，再依剩餘現金與訊號品質排序配置。",
        "stop_price": ma["daily8"],
        "support_range": support_range(symbol, ma),
        "scenarios": scenarios,
    }


def build_next_plan(data: dict[str, object]) -> dict[str, object]:
    candidates = list(data.get("candidates") or [])
    candidates_by_symbol = {str(item.get("symbol")): item for item in candidates}
    account = build_account_state(candidates_by_symbol)
    held = {str(position["symbol"]) for position in account["positions"]}
    preferred = ["2375", "2484", "3057", "3450", "8150", "6770", "2492"]
    dynamic = [str(item.get("symbol")) for item in candidates if item.get("group_assignment") in ("操作組", "入選名單", "觀察組")]
    symbols = []
    for symbol in preferred + dynamic:
        if symbol in candidates_by_symbol and symbol not in held and symbol not in symbols:
            symbols.append(symbol)
    locked = [
        {
            "group": "持有觀察",
            "symbol": position["symbol"],
            "name": position["name"],
            "latest_price": position["latest_price"],
            "score": candidates_by_symbol.get(str(position["symbol"]), {}).get("score", "-"),
            "pattern_type": candidates_by_symbol.get(str(position["symbol"]), {}).get("pattern_type", "-"),
            "volume_ratio": candidates_by_symbol.get(str(position["symbol"]), {}).get("volume_ratio", "-"),
            "status": "持有，一定盯盤",
        }
        for position in account["positions"]
    ]
    locked.extend(
        {
            "group": candidates_by_symbol[symbol].get("group_assignment"),
            "symbol": symbol,
            "name": candidates_by_symbol[symbol].get("name"),
            "latest_price": candidates_by_symbol[symbol].get("latest_price"),
            "score": candidates_by_symbol[symbol].get("score"),
            "pattern_type": candidates_by_symbol[symbol].get("pattern_type"),
            "volume_ratio": candidates_by_symbol[symbol].get("volume_ratio"),
            "status": (
                f"日成交量約 {fmt(volume_lots(candidates_by_symbol[symbol].get('volume')), 0)} 張，低於500張，不操作"
                if is_low_daily_volume(candidates_by_symbol[symbol].get("volume"))
                else "盤中同步盯；符合條件即動態升級"
            ),
        }
        for symbol in symbols
    )
    latest_day = str(data.get("latest_completed_day") or date.today().isoformat())
    cash = to_float(account.get("cash"))
    reserve = round(cash * 0.15, 2)
    return {
        "updated_at": f"{date.today().isoformat()} 18:00",
        "applies_to": next_weekday(latest_day),
        "basis_day": latest_day,
        "cash_allocation_note": f"剩餘資金 {cash:,.0f}；盤中全部盯盤，觀察組符合條件可直接升操作組。多檔同時觸發時先保留約 {reserve:,.0f}，其餘按型態乾淨度、週/月3MA交會、5K確認強弱排序。",
        "account": account,
        "locked_stocks": locked,
        "holding_plans": [holding_plan(position) for position in account["positions"]],
        "symbol_plans": [symbol_plan(candidates_by_symbol[symbol], cash) for symbol in symbols],
    }


def extract_dashboard_data(html_text: str) -> dict[str, object]:
    match = re.search(r"const dashboardData = (.*?);\s*\n\s*const candidates", html_text, re.S)
    if not match:
        raise RuntimeError("Cannot find dashboardData in HTML")
    return json.loads(match.group(1))


def replace_dashboard_data(html_text: str, data: dict[str, object]) -> str:
    payload = "const dashboardData = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n    const candidates"
    return re.sub(r"const dashboardData = .*?;\s*\n\s*const candidates", payload, html_text, flags=re.S)


def ensure_next_plan_ui(html_text: str) -> str:
    if ".account-grid" not in html_text:
        html_text = html_text.replace(
            ".pool-item:first-child { border-top:0; }\n    .pos",
            ".pool-item:first-child { border-top:0; }\n"
            "    .account-grid { grid-template-columns:repeat(6,minmax(0,1fr)); }\n"
            "    .plan-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }\n"
            "    .scenario-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }\n"
            "    .scenario-card h4 { margin:0 0 8px; font-size:14px; }\n"
            "    .scenario-card p { font-size:13px; }\n"
            "    .plan-symbol { margin-top:14px; }\n"
            "    .pos",
        )
        html_text = html_text.replace(
            "@media (max-width:1100px) { .overview,.detail-grid,.pool-grid { grid-template-columns:1fr; }",
            "@media (max-width:1100px) { .overview,.detail-grid,.pool-grid,.account-grid,.plan-grid { grid-template-columns:1fr; }",
        )
    if "<h2>下個交易日操作</h2>" not in html_text:
        section = """
    <section>
      <h2>下個交易日操作</h2>
      <p class="muted" id="next-plan-note">-</p>
      <h3>鎖定股</h3>
      <table><thead><tr><th>分組</th><th>股票</th><th>收盤價</th><th>分數</th><th>型態</th><th>量比</th><th>狀態</th></tr></thead><tbody id="locked-stock-body"></tbody></table>
      <h3 style="margin-top:16px">帳戶狀態</h3>
      <div class="grid account-grid" id="account-status"></div>
      <h3 style="margin-top:16px">持有部位</h3>
      <table><thead><tr><th>股票</th><th>股數</th><th>成本</th><th>現價</th><th>市值</th><th>未實現損益</th><th>損益率</th><th>狀態</th></tr></thead><tbody id="holding-body"></tbody></table>
      <div id="next-symbol-plans"></div>
    </section>

"""
        html_text = html_text.replace("    <section>\n      <h2>後驗追蹤</h2>", section + "    <section>\n      <h2>後驗追蹤</h2>")
    if "const nextPlan = dashboardData.next_trading_plan || {};" not in html_text:
        html_text = html_text.replace(
            "const candidates = dashboardData.candidates || [];\n",
            "const candidates = dashboardData.candidates || [];\n    const nextPlan = dashboardData.next_trading_plan || {};\n",
        )
    if "function renderNextTradingPlan()" not in html_text:
        render_js = r'''
    function renderNextTradingPlan() {
      if (!nextPlan || !nextPlan.account) return;
      byId("next-plan-note").textContent = `${nextPlan.applies_to || "-"} / 基準日 ${nextPlan.basis_day || "-"} / ${nextPlan.cash_allocation_note || ""}`;
      byId("locked-stock-body").innerHTML = (nextPlan.locked_stocks || []).map((item) => `<tr><td>${item.group}</td><td><strong>${item.symbol}</strong><br><span class="muted">${item.name}</span></td><td>${fmt(item.latest_price)}</td><td>${fmt(item.score)}</td><td>${item.pattern_type}</td><td>${fmt(item.volume_ratio)}</td><td>${item.status}</td></tr>`).join("");
      const account = nextPlan.account || {};
      const accountItems = [
        ["現金", account.cash], ["持股市值", account.position_value], ["總資產", account.total_assets],
        ["已實現損益", account.realized_pnl], ["未實現損益", account.unrealized_pnl], ["總損益", account.total_pnl],
      ];
      byId("account-status").innerHTML = accountItems.map(([label, value]) => `<div class="card"><div class="metric-label">${label}</div><div class="metric-value">${fmt(value)}</div></div>`).join("");
      byId("holding-body").innerHTML = (account.positions || []).map((item) => `<tr><td><strong>${item.symbol}</strong><br><span class="muted">${item.name}</span></td><td>${item.shares}</td><td>${fmt(item.cost_basis)}</td><td>${fmt(item.latest_price)}</td><td>${fmt(item.market_value)}</td><td class="${Number(item.unrealized_pnl) >= 0 ? "pos" : "neg"}">${fmt(item.unrealized_pnl)}</td><td>${pct(item.unrealized_pct)}</td><td>${item.status}</td></tr>`).join("");
      const card = (item, titlePrefix) => `<div class="card plan-symbol"><h3>${titlePrefix}${item.symbol} ${item.name}</h3><p class="muted">狀態：${item.entry_status || "持有觀察"} / 支撐區：${item.support_range || "-"} / 日3MA：${fmt(item.ma3)} / 日8MA：${fmt(item.ma8)}</p><div class="grid plan-grid">${(item.scenarios || []).map((scenario) => `<div class="scenario-card"><h4>${scenario.title}</h4><p><b>條件：</b>${scenario.condition}</p><p><b>操作：</b>${scenario.action}</p></div>`).join("")}</div></div>`;
      const holdingPlans = (nextPlan.holding_plans || []).map((item) => card(item, "持有：")).join("");
      const symbolPlans = (nextPlan.symbol_plans || []).map((item) => card(item, "盯盤：")).join("");
      byId("next-symbol-plans").innerHTML = `${holdingPlans}${symbolPlans}` || '<p class="muted">目前沒有下個交易日操作劇本。</p>';
    }
'''
        html_text = html_text.replace("    function renderTracking() {", render_js + "\n    function renderTracking() {")
    html_text = html_text.replace(
        "function renderAll() { renderMetrics(); renderCandidateTable(); renderDetail(); renderPools(); renderTracking(); }",
        "function renderAll() { renderMetrics(); renderCandidateTable(); renderDetail(); renderPools(); renderNextTradingPlan(); renderTracking(); }",
    )
    return html_text


def update_html(path: Path, write_plan: bool = False) -> None:
    html_text = path.read_text(encoding="utf-8-sig")
    data = extract_dashboard_data(html_text)
    data["next_trading_plan"] = build_next_plan(data)
    if write_plan:
        PLAN_PATH.write_text(json.dumps(data["next_trading_plan"], ensure_ascii=False, indent=2), encoding="utf-8")
    html_text = ensure_next_plan_ui(html_text)
    html_text = replace_dashboard_data(html_text, data)
    path.write_text(html_text, encoding="utf-8-sig")


def main() -> None:
    root_html = HTML_FILES[0]
    if root_html.exists():
        update_html(root_html, write_plan=True)
    for path in HTML_FILES[1:]:
        path.parent.mkdir(parents=True, exist_ok=True)
        if root_html.exists():
            shutil.copy2(root_html, path)
    for report_dir in (ROOT / "docs" / "reports", ROOT / "site" / "reports"):
        report_dir.mkdir(parents=True, exist_ok=True)
        if PLAN_PATH.exists():
            shutil.copy2(PLAN_PATH, report_dir / PLAN_PATH.name)
    print("injected next trading plan into index/docs/site")


if __name__ == "__main__":
    main()
