from __future__ import annotations

import csv
import html
import json
from datetime import date
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SYMBOL_NAMES = {
    "3037": "欣興",
    "4958": "臻鼎-KY",
    "6205": "詮欣",
    "8046": "南電",
    "2313": "華通",
}


def load_custom_watchlist() -> dict[str, dict[str, str]]:
    path = ROOT / "config" / "custom_watchlist.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    result: dict[str, dict[str, str]] = {}
    for item in data.get("items", []):
        symbol = str(item.get("symbol", "")).strip()
        if not symbol:
            continue
        name = str(item.get("name") or SYMBOL_NAMES.get(symbol, symbol))
        result[symbol] = {
            "name": name,
            "label": str(item.get("label") or f"{symbol} {name}"),
            "priority": str(item.get("priority") or ""),
            "reason": str(item.get("reason") or ""),
            "tracking_note": str(item.get("tracking_note") or ""),
        }
    return result


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_scan() -> list[dict]:
    return json.loads((ROOT / "reports" / "scan.json").read_text(encoding="utf-8"))


def load_weekly_selection() -> dict:
    path = ROOT / "reports" / "weekly_selection.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def latest_market_rows() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for path in sorted((ROOT / "data" / "ohlcv").glob("*.csv")):
        rows = read_csv_rows(path)
        if not rows:
            continue
        latest = rows[-1]
        previous = rows[-2] if len(rows) >= 2 else latest
        close = float(latest["close"])
        prev_close = float(previous["close"])
        result[path.stem] = {
            "symbol": path.stem,
            "name": SYMBOL_NAMES.get(path.stem, path.stem),
            "latest_date": latest["timestamp"],
            "close": close,
            "prev_close": prev_close,
            "change_pct": round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
            "volume": int(float(latest["volume"])),
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
        }
    return result


def flatten_tracking_rows(
    scan_rows: list[dict],
    market: dict[str, dict[str, object]],
    custom_watchlist: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in scan_rows:
        symbol = str(item["symbol"])
        latest = item.get("details", {}).get("latest", {})
        pattern = item.get("details", {}).get("pattern", {})
        market_row = market.get(symbol, {})
        close = float(market_row.get("close", 0) or latest.get("close", 0) or 0)
        ma3 = float(latest.get("ma3", 0) or 0)
        ma8 = float(latest.get("ma8", 0) or 0)
        ma21 = float(latest.get("ma21", 0) or 0)
        key_level = pattern.get("key_level", "")
        key_level_value = float(key_level or 0) if key_level not in ("", None) else 0.0
        rows.append(
            {
                "run_date": date.today().isoformat(),
                "data_latest_completed_day": market_row.get("latest_date", ""),
                "symbol": symbol,
                "name": market_row.get("name", SYMBOL_NAMES.get(symbol, symbol)),
                "custom_watchlist": custom_watchlist.get(symbol, {}).get("label", ""),
                "decision": item.get("decision", ""),
                "score": item.get("score", ""),
                "tier": item.get("tier", ""),
                "market_state": item.get("market_state", ""),
                "pattern_type": item.get("pattern_type") or "",
                "close": market_row.get("close", ""),
                "change_pct": market_row.get("change_pct", ""),
                "volume": market_row.get("volume", ""),
                "volume_ratio": round(float(latest.get("volume_ratio", 0)), 2),
                "ma3": round(ma3, 2),
                "ma8": round(ma8, 2),
                "ma21": round(ma21, 2),
                "ma3_gap_pct": round((close - ma3) / ma3 * 100, 2) if ma3 else "",
                "ma8_gap_pct": round((close - ma8) / ma8 * 100, 2) if ma8 else "",
                "ma21_gap_pct": round((close - ma21) / ma21 * 100, 2) if ma21 else "",
                "macd_hist": round(float(latest.get("macd_hist", 0)), 2),
                "key_level": key_level,
                "key_level_gap_pct": round((close - key_level_value) / key_level_value * 100, 2) if key_level_value else "",
                "chip_status": "籌碼未確認" if item.get("details", {}).get("chip") is None else "籌碼偏多",
                "reason": item.get("reason", ""),
                "tracking_action": classify_action(item),
            }
        )
    return rows


def classify_action(item: dict) -> str:
    decision = item.get("decision")
    score = float(item.get("score", 0))
    pattern_type = item.get("pattern_type")
    if decision == "hold" and score >= 85 and pattern_type:
        return "優先追蹤，等待5K切入點與60K MACD確認"
    if decision == "hold":
        return "觀察，不追高"
    return "暫不納入進場候選"


def append_tracking_log(rows: list[dict[str, object]], custom_watchlist: dict[str, dict[str, str]]) -> Path:
    path = ROOT / "reports" / "tracking_log.csv"
    existing: list[dict[str, str]] = []
    if path.exists():
        existing = read_csv_rows(path)
    for row in existing:
        row["custom_watchlist"] = custom_watchlist.get(str(row.get("symbol", "")), {}).get("label", "")
    existing_keys = {(row["run_date"], row["data_latest_completed_day"], row["symbol"]) for row in existing}
    new_rows = [
        row for row in rows
        if (str(row["run_date"]), str(row["data_latest_completed_day"]), str(row["symbol"])) not in existing_keys
    ]
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in existing:
            writer.writerow(row)
        writer.writerows(new_rows)
    return path


def market_data_note(latest_day: object) -> str:
    today = date.today().isoformat()
    latest = str(latest_day or "n/a")
    if latest != "n/a" and latest >= today:
        return f"{latest} full daily candle is available; report uses the latest completed daily data."
    return (
        f"{today} full daily candle was not available from the data source at update time; "
        f"report uses latest completed day {latest}."
    )


def write_markdown(rows: list[dict[str, object]]) -> Path:
    path = ROOT / "reports" / "tracking_summary.md"
    latest_day = rows[0]["data_latest_completed_day"] if rows else "n/a"
    lines = [
        "# Trading Tracking Summary",
        "",
        f"- run_date: {date.today().isoformat()}",
        f"- latest_completed_day: {latest_day}",
        f"- note: {market_data_note(latest_day)}",
        "",
        "| rank | symbol | name | watchlist | decision | score | close | change_pct | volume_ratio | action |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for idx, row in enumerate(rows, 1):
        lines.append(
            f"| {idx} | {row['symbol']} | {row['name']} | {row['custom_watchlist']} | {row['decision']} | {float(row['score']):.2f} | "
            f"{float(row['close']):.2f} | {float(row['change_pct']):.2f}% | {float(row['volume_ratio']):.2f} | {row['tracking_action']} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8-sig")
    return path


def pct_class(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number > 0:
        return "pos"
    if number < 0:
        return "neg"
    return ""


def format_symbol_list(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "無"
    return "、".join(f"{row['symbol']} {row['name']}" for row in rows)


def display_group(row: dict[str, object]) -> str:
    if row["decision"] == "hold":
        if str(row.get("tracking_action", "")).startswith("優先追蹤"):
            return "實際操作候選"
        return "觀察組"
    return "暫停/淘汰"


def format_pct(value: object) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def format_number(value: object, digits: int = 2) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "-"


def summarize_risk(row: dict[str, object]) -> str:
    if row["decision"] != "hold":
        return "不進場，等待重新站回強勢結構。"
    if row.get("chip_status") != "籌碼偏多":
        return "只能觀察，籌碼未確認前不列實際操作組。"
    return "等 5K 切入點與 60K MACD 確認後才允許現價切入。"


def next_trigger(row: dict[str, object]) -> str:
    if row["decision"] != "hold":
        return "重新出現型態、量能與均線共振。"
    if row.get("pattern_type") == "ma_bloom":
        return "日線開花續強，等待 5K 紅紅紅或回撤日K 3MA不破。"
    if row.get("pattern_type") == "w_pattern":
        return "W 型有效，等待 5K 節奏與 60K MACD轉強。"
    return "保持觀察，不追高。"


def render_dashboard_card(row: dict[str, object]) -> str:
    decision = str(row["decision"])
    decision_class = "hold" if decision == "hold" else "reject"
    change_class = pct_class(row["change_pct"])
    group = display_group(row)
    key_level = format_number(row.get("key_level")) if row.get("key_level") not in ("", None) else "-"
    key_gap = format_pct(row.get("key_level_gap_pct"))
    return f"""
      <article class="idea-card {decision_class}">
        <div class="idea-top">
          <div>
            <div class="symbol-line">{html.escape(str(row['symbol']))} <span>{html.escape(str(row['name']))}</span></div>
            <div class="muted small">{html.escape(group)} / {html.escape(str(row.get('market_state', '-')))} / {html.escape(str(row.get('pattern_type') or '無型態'))}</div>
          </div>
          <span class="tag {decision_class}">{html.escape(decision)}</span>
        </div>
        <div class="price-line">
          <strong>{format_number(row.get('close'))}</strong>
          <span class="{change_class}">{format_pct(row.get('change_pct'))}</span>
          <span>Score {format_number(row.get('score'))}</span>
        </div>
        <div class="obs-grid">
          <div><span>量比</span><strong>{format_number(row.get('volume_ratio'))}</strong></div>
          <div><span>3MA距離</span><strong>{format_pct(row.get('ma3_gap_pct'))}</strong></div>
          <div><span>8MA距離</span><strong>{format_pct(row.get('ma8_gap_pct'))}</strong></div>
          <div><span>21MA距離</span><strong>{format_pct(row.get('ma21_gap_pct'))}</strong></div>
          <div><span>MACD柱</span><strong>{format_number(row.get('macd_hist'))}</strong></div>
          <div><span>關鍵位</span><strong>{key_level} / {key_gap}</strong></div>
        </div>
        <div class="card-note"><b>下一步：</b>{html.escape(next_trigger(row))}</div>
        <div class="card-note"><b>風控：</b>{html.escape(summarize_risk(row))}</div>
      </article>
    """


def render_observation_row(idx: int, row: dict[str, object]) -> str:
    decision = str(row["decision"])
    tag_class = "hold" if decision == "hold" else "reject"
    change_class = pct_class(row["change_pct"])
    return (
        "<tr>"
        f"<td>{idx}</td>"
        f"<td><strong>{html.escape(str(row['symbol']))}</strong><br><span class=\"muted small\">{html.escape(str(row['name']))}</span></td>"
        f"<td>{html.escape(display_group(row))}<br><span class=\"tag {tag_class}\">{html.escape(decision)}</span></td>"
        f"<td>{format_number(row['score'])}</td>"
        f"<td>{format_number(row['close'])}<br><span class=\"{change_class}\">{format_pct(row['change_pct'])}</span></td>"
        f"<td>{format_number(row['volume_ratio'])}</td>"
        f"<td>{html.escape(str(row['pattern_type'] or '-'))}<br><span class=\"muted small\">{html.escape(str(row['market_state']))}</span></td>"
        f"<td>3MA {format_number(row['ma3'])} ({format_pct(row['ma3_gap_pct'])})<br>8MA {format_number(row['ma8'])} ({format_pct(row['ma8_gap_pct'])})<br>21MA {format_number(row['ma21'])} ({format_pct(row['ma21_gap_pct'])})</td>"
        f"<td>{format_number(row['macd_hist'])}</td>"
        f"<td>{html.escape(str(row['chip_status']))}</td>"
        f"<td>{html.escape(next_trigger(row))}</td>"
        "</tr>"
    )


def render_weekly_group(items: list[dict[str, object]], empty_text: str) -> str:
    if not items:
        return f'<p class="empty-text">{html.escape(empty_text)}</p>'
    lines = []
    for item in items:
        pattern = item.get("pattern_type") or "無型態"
        lines.append(
            "<div class=\"weekly-item\">"
            f"<strong>{html.escape(str(item['symbol']))} {html.escape(str(item['name']))}</strong>"
            f"<span>Score {format_number(item.get('score'))} / {html.escape(str(pattern))} / 量比 {format_number(item.get('volume_ratio'))}</span>"
            f"<p>{html.escape(str(item.get('action', '')))}</p>"
            "</div>"
        )
    return "\n".join(lines)


def write_html(rows: list[dict[str, object]]) -> Path:
    path = ROOT / "index.html"
    weekly = load_weekly_selection()
    weekly_groups = weekly.get("groups", {})
    weekly_operation = weekly_groups.get("operation_group", [])
    weekly_observation = weekly_groups.get("observation_group", [])
    latest_day = rows[0]["data_latest_completed_day"] if rows else "n/a"
    hold_rows = [row for row in rows if row["decision"] == "hold"]
    reject_rows = [row for row in rows if row["decision"] != "hold"]
    priority_rows = [
        row for row in hold_rows
        if str(row.get("tracking_action", "")).startswith("優先追蹤")
    ]
    observe_rows = [
        row for row in hold_rows
        if not str(row.get("tracking_action", "")).startswith("優先追蹤")
    ]
    report_date = date.today().strftime("%Y/%m/%d")
    visible_rows = priority_rows + observe_rows
    weekly_visible = weekly_operation + weekly_observation
    best_score = max((float(row.get("score", 0)) for row in weekly_visible), default=0)
    stale_warning = "" if str(latest_day) >= date.today().isoformat() else "資料不是今日完整日K，僅供追蹤。"
    html_text = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>Trading Decision Dashboard</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #68707d;
      --line: #d9e0e7;
      --accent: #0f766e;
      --warn: #8a5a00;
      --danger: #b42318;
      --ok: #137333;
      --ink: #26313d;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft JhengHei", "PingFang TC", Arial, sans-serif;
      line-height: 1.55;
    }}
    header {{
      background: #26313d;
      color: #ffffff;
      border-bottom: 1px solid var(--line);
      padding: 26px 34px;
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px 24px 42px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 26px 0 12px; font-size: 20px; letter-spacing: 0; }}
    p {{ margin: 6px 0; }}
    header .muted {{ color: #c8d2dc; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .notice {{
      margin-top: 14px;
      padding: 12px 14px;
      border-left: 4px solid #f9c74f;
      background: #fff8e8;
      color: #3b2f12;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric-card, .card, .idea-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .metric {{ font-size: 28px; font-weight: 800; margin-top: 2px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .decision-strip {{
      display: grid;
      grid-template-columns: 1.2fr 1fr 1fr;
      gap: 12px;
      margin-top: 14px;
    }}
    .decision-strip .card {{ border-left: 4px solid var(--line); }}
    .decision-strip .buy {{ border-left-color: var(--ok); }}
    .decision-strip .watch {{ border-left-color: var(--accent); }}
    .decision-strip .avoid {{ border-left-color: var(--danger); }}
    .ideas {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .idea-card.hold {{ border-left: 4px solid var(--accent); }}
    .idea-card.reject {{ border-left: 4px solid var(--danger); }}
    .idea-top, .price-line {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }}
    .symbol-line {{ font-size: 21px; font-weight: 800; }}
    .symbol-line span {{ font-size: 15px; color: var(--muted); font-weight: 600; }}
    .price-line {{ margin: 12px 0; align-items: baseline; justify-content: flex-start; }}
    .price-line strong {{ font-size: 24px; }}
    .price-line span {{ font-weight: 700; }}
    .obs-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .obs-grid div {{ padding: 9px; border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
    .obs-grid div:nth-child(3n) {{ border-right: 0; }}
    .obs-grid div:nth-last-child(-n+3) {{ border-bottom: 0; }}
    .obs-grid span {{ display: block; color: var(--muted); font-size: 12px; }}
    .obs-grid strong {{ display: block; margin-top: 2px; font-size: 14px; }}
    .card-note {{ margin-top: 10px; color: var(--ink); font-size: 14px; }}
    .weekly-board {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .weekly-column {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 150px;
    }}
    .weekly-column.operation {{ border-top: 4px solid var(--ok); }}
    .weekly-column.observe {{ border-top: 4px solid #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }}
    .weekly-item {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
      margin-top: 10px;
    }}
    .weekly-column.operation .weekly-item {{ background: #eef8f0; border: 1px solid #b6d5bf; border-radius: 8px; padding: 10px; }}
    .weekly-column.observe .weekly-item {{ background: #dbeafe; border: 1px solid #93c5fd; border-radius: 8px; padding: 10px; }}
    .weekly-item span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .weekly-item p {{ font-size: 13px; margin-top: 5px; }}
    .empty-text {{ color: var(--muted); font-size: 14px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{ background: #ecefeb; white-space: nowrap; }}
    tr:last-child td {{ border-bottom: 0; }}
    .tag {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid var(--line);
      background: #f7f7f4;
    }}
    .hold {{ color: var(--ok); background: #eef8f0; border-color: #b6d5bf; }}
    .reject {{ color: var(--danger); background: #fff1ef; border-color: #e0b5af; }}
    .watchlist {{ color: #0f5f7a; background: #eaf6fb; border-color: #acd3df; }}
    .pos {{ color: var(--ok); font-weight: 700; }}
    .neg {{ color: var(--danger); font-weight: 700; }}
    ul {{ margin: 8px 0 0 20px; padding: 0; }}
    li {{ margin: 4px 0; }}
    code {{
      background: #eef0ed;
      border: 1px solid #dfe3dc;
      border-radius: 4px;
      padding: 1px 5px;
    }}
    @media (max-width: 820px) {{
      header {{ padding: 22px 18px 16px; }}
      main {{ padding: 18px 12px 32px; }}
      .summary, .grid, .decision-strip, .ideas, .weekly-board {{ grid-template-columns: 1fr; }}
      .obs-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .obs-grid div, .obs-grid div:nth-child(3n), .obs-grid div:nth-last-child(-n+3) {{ border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Trading Decision Dashboard</h1>
    <p class="muted">更新日：{date.today().isoformat()} / 最新完整日線：{html.escape(str(latest_day))} / 每週日更新選股池</p>
    <div class="notice">{html.escape(market_data_note(latest_day))}</div>
  </header>
  <main>
    <section class="summary">
      <div class="metric-card"><div class="metric-label">本週實際操作組</div><div class="metric">{len(weekly_operation)}</div></div>
      <div class="metric-card"><div class="metric-label">本週觀察組</div><div class="metric">{len(weekly_observation)}</div></div>
      <div class="metric-card"><div class="metric-label">候選來源</div><div class="metric">5</div></div>
      <div class="metric-card"><div class="metric-label">最高分</div><div class="metric">{best_score:.2f}</div></div>
      <div class="metric-card"><div class="metric-label">自選股</div><div class="metric">{sum(1 for row in rows if row.get("custom_watchlist"))}</div></div>
    </section>
    <section>
      <h2>本週選股池</h2>
      <p class="muted">選股日：{html.escape(str(weekly.get('selection_date', 'n/a')))} / 來源：{html.escape(str(weekly.get('source', 'n/a')))} / 使用資料：{html.escape(str(weekly.get('source_week', 'n/a')))} / 適用週期：{html.escape(str(weekly.get('target_week', 'n/a')))}</p>
      <p class="muted small">{html.escape(str(weekly.get('method', '')))}</p>
      <div class="weekly-board">
        <div class="weekly-column operation">
          <strong>實際操作組</strong>
          {render_weekly_group(weekly_operation, '本週無股票符合實際操作組；主因是籌碼未確認或切入條件不足。')}
        </div>
        <div class="weekly-column observe">
          <strong>觀察組</strong>
          {render_weekly_group(weekly_observation, '本週無觀察股。')}
        </div>
      </div>
    </section>
    <section>
      <h2>操作規則</h2>
      <div class="grid">
        <div class="card"><strong>進場前置</strong><ul><li>大盤允許，跌幅超過 3% 轉保守。</li><li>只做強勢族群、攻擊量、籌碼偏多、多頭排列。</li><li>型態需先成立，再看 5K 開盤節奏。</li></ul></div>
        <div class="card"><strong>切入確認</strong><ul><li>5K 紅紅紅，高低點墊高且量不衰退。</li><li>5K 爆大量後回撤日K 3MA 不破。</li><li>連三黑但日K結構未破，回測 3MA 不破。</li><li>60K MACD 綠柱縮短或紅柱翻揚。</li></ul></div>
        <div class="card"><strong>持股與汰換</strong><ul><li>短線看日K 3MA / 8MA。</li><li>中線看週K趨勢延續。</li><li>長線看月K 3MA。</li><li>每週日更新選股池，降級股票觀察 1 週。</li></ul></div>
      </div>
    </section>
    <section>
      <h2>資料說明</h2>
      <p class="muted">本頁為研究型輔助報告，不接券商、不自動下單。{html.escape(stale_warning)}</p>
      <p class="muted">保留紀錄：<code>reports/tracking_log.csv</code>、<code>reports/tracking_summary.md</code>、<code>reports/scan.json</code>。</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8-sig")
    return path


def render_row(idx: int, row: dict[str, object]) -> str:
    decision = str(row["decision"])
    tag_class = "hold" if decision == "hold" else "reject"
    change_class = pct_class(row["change_pct"])
    watchlist = str(row.get("custom_watchlist", ""))
    watchlist_cell = (
        f"<span class=\"tag watchlist\">{html.escape(watchlist)}</span>"
        if watchlist
        else "-"
    )
    return (
        "<tr>"
        f"<td>{idx}</td>"
        f"<td>{html.escape(str(row['symbol']))}</td>"
        f"<td>{html.escape(str(row['name']))}</td>"
        f"<td>{watchlist_cell}</td>"
        f"<td><span class=\"tag {tag_class}\">{html.escape(decision)}</span></td>"
        f"<td>{float(row['score']):.2f}</td>"
        f"<td>{float(row['close']):.2f}</td>"
        f"<td class=\"{change_class}\">{float(row['change_pct']):.2f}%</td>"
        f"<td>{float(row['volume_ratio']):.2f}</td>"
        f"<td>{html.escape(str(row['pattern_type'] or '-'))}</td>"
        f"<td>{html.escape(str(row['tracking_action']))}</td>"
        "</tr>"
    )


def render_original_candidate(rank: str, symbol: str, name: str, tier: str, reason: str) -> str:
    return (
        "<tr>"
        f"<td>{html.escape(rank)}</td>"
        f"<td>{html.escape(symbol)}</td>"
        f"<td>{html.escape(name)}</td>"
        f"<td>{html.escape(tier)}</td>"
        f"<td>{html.escape(reason)}</td>"
        "</tr>"
    )


def main() -> None:
    scan_rows = load_scan()
    market = latest_market_rows()
    custom_watchlist = load_custom_watchlist()
    rows = flatten_tracking_rows(scan_rows, market, custom_watchlist)
    append_tracking_log(rows, custom_watchlist)
    write_markdown(rows)
    write_html(rows)
    print("updated reports/tracking_log.csv")
    print("updated reports/tracking_summary.md")
    print("updated index.html")


if __name__ == "__main__":
    main()
