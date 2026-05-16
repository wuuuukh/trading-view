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
    "1597": "直得",
    "8150": "南茂",
    "2464": "盟立",
    "3057": "喬鼎",
    "2484": "希華",
    "3450": "聯鈞",
    "2492": "華新科",
    "3033": "威健",
    "3048": "益登",
    "3026": "禾伸堂",
    "3481": "群創",
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
        ma55 = float(latest.get("ma55", 0) or 0)
        ma144 = float(latest.get("ma144", 0) or 0)
        ma233 = float(latest.get("ma233", 0) or 0)
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
                "ma55": round(ma55, 2),
                "ma144": round(ma144, 2),
                "ma233": round(ma233, 2),
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


def display_pattern(value: object) -> str:
    labels = {
        "breakout": "突破",
        "w_pattern": "W",
        "n_pattern": "N字",
        "base_breakout": "平台",
        "ma_bloom": "開花",
        "": "待確認",
        None: "待確認",
    }
    return labels.get(value, str(value))


def to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ma_alignment(close: object, ma3: object, ma8: object, ma21: object) -> str:
    close_n = to_float(close)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    ma21_n = to_float(ma21)
    if None in (close_n, ma3_n, ma8_n, ma21_n):
        return "待確認"
    if close_n >= ma3_n and ma3_n > ma8_n > ma21_n:
        return "偏多"
    if close_n >= ma8_n and ma3_n >= ma8_n:
        return "普通偏多"
    return "轉弱警戒"


def risk_note_for_candidate(symbol: str, ma3: object, ma8: object) -> str:
    ma3_text = format_number(ma3)
    ma8_text = format_number(ma8)
    return f"{symbol} 短線看日K 3MA {ma3_text} 與 8MA {ma8_text}；跌破 3MA 先警戒，跌破 8MA 或月K 3MA 結構破壞則移出入選名單。"


def clean_dashboard_reason(symbol: str, item: dict[str, object], group_label: str) -> str:
    pattern = display_pattern(item.get("pattern_type"))
    score = format_number(item.get("score"))
    volume_ratio = format_number(item.get("volume_ratio"))
    if group_label == "入選名單":
        return f"{symbol} 符合本週神秘金字塔篩選條件，列入入選名單；Score {score}，型態 {pattern}，量比 {volume_ratio}。操作組規則待補，暫不直接視為可操作。"
    return f"{symbol} 先列觀察組；Score {score}，型態 {pattern}，量比 {volume_ratio}。補齊籌碼與切入條件前不進操作組。"


def write_html(rows: list[dict[str, object]]) -> Path:
    path = ROOT / "index.html"
    weekly = load_weekly_selection()
    weekly_groups = weekly.get("groups", {})
    market = latest_market_rows()
    current_scan = {str(row.get("symbol")): row for row in rows}
    name_map = {
        "1597": "直得",
        "8150": "南茂",
        "2464": "盟立",
        "3057": "喬鼎",
        "2484": "希華",
        "3450": "聯鈞",
        "2492": "華新科",
        "3033": "威健",
        "3048": "益登",
        "3026": "禾伸堂",
        "3481": "群創",
    }

    def candidate_from_weekly(item: dict[str, object], group_label: str) -> dict[str, object]:
        symbol = str(item.get("symbol", ""))
        market_row = market.get(symbol, {})
        scan_row = current_scan.get(symbol, {})
        close = market_row.get("close", item.get("close", ""))
        change_pct = market_row.get("change_pct", "")
        latest_date = market_row.get("latest_date", "")
        ma3 = scan_row.get("ma3", item.get("ma3", ""))
        ma8 = scan_row.get("ma8", item.get("ma8", ""))
        ma21 = scan_row.get("ma21", item.get("ma21", ""))
        ma55 = scan_row.get("ma55", item.get("ma55", ""))
        ma144 = scan_row.get("ma144", item.get("ma144", ""))
        ma233 = scan_row.get("ma233", item.get("ma233", ""))
        return {
            "symbol": symbol,
            "name": name_map.get(symbol, str(item.get("name", symbol))),
            "latest_price": close,
            "change_pct": change_pct,
            "score": float(item.get("score") or 0),
            "decision": "hold" if group_label == "實際操作組" else str(item.get("decision") or "hold"),
            "reason": clean_dashboard_reason(symbol, item, group_label),
            "market_state": item.get("market_state") or "待確認",
            "pattern_type": display_pattern(item.get("pattern_type")),
            "chip_state": "神秘金字塔週榜偏多；正式籌碼資料待接",
            "entry_trigger": "等待 5K 切入點 + 60K MACD 確認",
            "risk_note": risk_note_for_candidate(symbol, ma3, ma8),
            "group_assignment": group_label,
            "index_state": "正常" if not str(latest_date).startswith("n/a") else "待確認",
            "daily_ma_alignment": ma_alignment(close, ma3, ma8, ma21),
            "weekly_ma_alignment": "週K待接，但本週先依上一週完整日K與週榜分層",
            "monthly_ma_alignment": "月K 3MA 不破才允許續抱",
            "shareholder_score": "-",
            "institution_bias": "待接法人/投信資料",
            "next_1d_return": None,
            "next_3d_return": None,
            "next_5d_return": None,
            "latest_date": latest_date,
            "volume_ratio": item.get("volume_ratio", ""),
            "ma": {
                "3MA": ma3,
                "8MA": ma8,
                "21MA": ma21,
                "55MA": ma55,
                "144MA": ma144,
                "233MA": ma233,
            },
            "patterns": {
                "突破": item.get("pattern_type") == "breakout",
                "W": item.get("pattern_type") == "w_pattern",
                "N字": item.get("pattern_type") == "n_pattern",
                "平台": item.get("pattern_type") == "base_breakout",
                "開花": item.get("pattern_type") == "ma_bloom" or ma_alignment(close, ma3, ma8, ma21) == "偏多",
            },
            "triggers": {
                "開盤八法紅紅紅": False,
                "5K爆大量回撤3MA": False,
                "連三黑回測3MA": False,
                "60K MACD轉強": False,
            },
        }

    weekly_operation = [
        candidate_from_weekly(item, "入選名單")
        for item in weekly_groups.get("operation_group", [])
    ]
    weekly_observation = [
        candidate_from_weekly(item, "觀察組")
        for item in weekly_groups.get("observation_group", [])
    ]
    weekly_trading = [
        candidate_from_weekly(item, "操作組")
        for item in weekly_groups.get("trading_group", [])
    ]
    candidates = weekly_operation + weekly_trading + weekly_observation
    latest_dates = [
        str(row.get("latest_date"))
        for row in market.values()
        if row.get("latest_date")
    ]
    latest_day = max(latest_dates) if latest_dates else (rows[0]["data_latest_completed_day"] if rows else "n/a")
    payload = {
        "generated_at": date.today().isoformat(),
        "latest_completed_day": str(latest_day),
        "market_note": market_data_note(latest_day),
        "selection": {
            "selection_date": weekly.get("selection_date", "n/a"),
            "source_week": weekly.get("source_week", "n/a"),
            "target_week": weekly.get("target_week", "n/a"),
            "source": weekly.get("source", "神秘金字塔股權類股排行週榜條件篩選"),
            "method": weekly.get("method", "每週日用上一週完整日K與神秘金字塔週榜產生下週選股池；每日盤後更新價格、均線、量能與追蹤資料。"),
        },
        "candidates": candidates,
    }
    html_text = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>AI Agent Trading Strategy Dashboard</title>
  <style>
    :root {
      --bg:#f3f6f8; --panel:#fff; --soft:#f8fafc; --line:#d9e1e8;
      --text:#1d2733; --muted:#647282; --green:#0f6b57; --green-soft:#e8f5ef;
      --blue:#1d4f91; --blue-soft:#eaf2ff; --red:#b42318; --red-soft:#fff1ef;
      --amber:#8a5a00; --amber-soft:#fff7df; --dark:#24313f;
    }
    * { box-sizing:border-box; }
    body {
      margin:0; background:var(--bg); color:var(--text);
      font-family:"Microsoft JhengHei","PingFang TC",Arial,sans-serif;
      line-height:1.45; letter-spacing:0;
    }
    header {
      background: #26313d;
      color:#fff; border-bottom:1px solid #1b2633;
    }
    .header-inner { max-width:1440px; margin:0 auto; padding:22px 28px; }
    h1 { margin:0; font-size:25px; }
    h2 { margin:26px 0 12px; font-size:18px; }
    h3 { margin:0 0 10px; font-size:16px; }
    p { margin:6px 0; }
    main { max-width:1440px; margin:0 auto; padding:18px 22px 42px; }
    .muted { color:var(--muted); } header .muted { color:#c7d2dd; }
    .mode { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
    .mode span { border:1px solid #5b6877; padding:5px 9px; border-radius:999px; font-size:12px; }
    .mode .active { background:#e7f4ef; color:#0f513f; border-color:#b7d8ca; }
    .grid { display:grid; gap:12px; }
    .overview { grid-template-columns:1.2fr repeat(4,1fr); }
    .detail-grid { grid-template-columns:1.1fr 1fr 1fr; }
    .pool-grid { grid-template-columns:1fr 1fr 1fr 1fr; }
    .card {
      background:var(--panel); border:1px solid var(--line); border-radius:8px;
      padding:14px; box-shadow:0 1px 2px rgba(15,23,42,.05);
    }
    .metric-label { color:var(--muted); font-size:12px; }
    .metric-value { margin-top:4px; font-size:26px; font-weight:800; }
    .status-normal { border-left:4px solid var(--green); }
    .status-watch { border-left:4px solid var(--blue); }
    .notice { margin-top:10px; padding:10px 12px; border-left:4px solid var(--amber); background:var(--amber-soft); }
    .toolbar { display:flex; gap:10px; justify-content:space-between; align-items:center; margin:10px 0; flex-wrap:wrap; }
    input, select { height:34px; border:1px solid var(--line); border-radius:6px; padding:0 10px; background:#fff; }
    table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    th, td { padding:10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#edf2f4; white-space:nowrap; font-size:12px; color:#435266; }
    tbody tr { cursor:pointer; } tbody tr:hover { background:#f6faf8; } tr:last-child td { border-bottom:0; }
    .symbol { font-size:16px; font-weight:800; }
    .tag { display:inline-block; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:700; border:1px solid var(--line); }
    .tag.selected { color:var(--blue); background:var(--blue-soft); border-color:#bcd2f5; }
    .tag.operation { color:var(--red); background:var(--red-soft); border-color:#e4b7af; }
    .tag.watch { color:var(--text); background:#fff; border-color:var(--line); }
    .tag.eliminate { color:var(--green); background:var(--green-soft); border-color:#b7d8ca; }
    .tag.accept, .tag.hold { color:var(--green); background:var(--green-soft); border-color:#b7d8ca; }
    .tag.reject { color:var(--red); background:var(--red-soft); border-color:#e4b7af; }
    .kv-grid { display:grid; grid-template-columns:repeat(3,1fr); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
    .kv { padding:9px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); min-height:56px; }
    .kv:nth-child(3n) { border-right:0; } .kv:nth-last-child(-n+3) { border-bottom:0; }
    .kv span, .check span { color:var(--muted); font-size:12px; display:block; }
    .kv strong, .check strong { display:block; margin-top:3px; font-size:14px; }
    .check-list { display:grid; gap:8px; }
    .check { display:flex; justify-content:space-between; gap:10px; border-bottom:1px solid var(--line); padding-bottom:7px; }
    .rule-line { border-left:3px solid var(--line); padding:7px 9px; background:var(--soft); margin-top:6px; font-size:13px; }
    .pool-card.operation { border-top:4px solid var(--red); background:var(--red-soft); }
    .pool-card.selected { border-top:4px solid var(--blue); background:var(--blue-soft); }
    .pool-card.watch { border-top:4px solid var(--line); background:#fff; }
    .pool-card.eliminate { border-top:4px solid var(--green); background:var(--green-soft); }
    .pool-item { padding:9px 0; border-top:1px solid var(--line); }
    .pool-item:first-child { border-top:0; }
    .pos { color:var(--green); font-weight:700; } .neg { color:var(--red); font-weight:700; }
    @media (max-width:1100px) { .overview,.detail-grid,.pool-grid { grid-template-columns:1fr; } table { display:block; overflow-x:auto; } }
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <h1>AI Agent Trading Strategy Dashboard</h1>
      <p class="muted">更新日：<span id="generated-at"></span> / 最新完整日K：<span id="latest-day"></span> / 每週日更新選股池</p>
      <div class="mode"><span class="active">Candidate Scan</span><span>Paper Trading</span><span>Research Dashboard</span></div>
    </div>
  </header>
  <main>
    <section class="grid overview">
      <div class="card status-normal"><div class="metric-label">大盤狀態</div><div class="metric-value" id="index-state">正常</div><p class="muted" id="market-note"></p></div>
      <div class="card"><div class="metric-label">掃描股票總數</div><div class="metric-value" id="metric-total">0</div></div>
      <div class="card"><div class="metric-label">Primary Review</div><div class="metric-value" id="metric-primary">0</div></div>
      <div class="card"><div class="metric-label">Secondary Watchlist</div><div class="metric-value" id="metric-secondary">0</div></div>
      <div class="card status-watch"><div class="metric-label">今日操作模式</div><div class="metric-value" id="operation-mode">正常</div></div>
    </section>

    <section>
      <h2>候選股排行榜</h2>
      <p class="muted" id="selection-note"></p>
      <div class="toolbar">
        <input id="search" placeholder="搜尋代號或名稱">
        <div><select id="decision-filter"><option value="all">全部 Decision</option><option value="hold">hold</option><option value="reject">reject</option></select>
        <select id="group-filter"><option value="all">全部分組</option><option value="入選名單">入選名單</option><option value="操作組">操作組</option><option value="觀察組">觀察組</option><option value="淘汰">淘汰</option></select></div>
      </div>
      <table><thead><tr><th>股票</th><th>最新價格</th><th>Agent Score</th><th>Decision</th><th>Group Assignment</th><th>Pattern Type</th><th>Market State</th><th>Chip State</th><th>Entry Trigger</th><th>理由摘要</th></tr></thead><tbody id="candidate-body"></tbody></table>
    </section>

    <section>
      <h2>單一標的詳情</h2>
      <div class="grid detail-grid">
        <div class="card"><h3 id="detail-symbol">-</h3><p class="muted" id="detail-reason">-</p><span id="detail-group" class="tag">-</span><h3 style="margin-top:14px">多週期均線結構</h3><div class="kv-grid" id="ma-grid"></div><div class="check-list" style="margin-top:10px"><div class="check"><span>日K共振</span><strong id="daily-ma-alignment">-</strong></div><div class="check"><span>週K共振</span><strong id="weekly-ma-alignment">-</strong></div><div class="check"><span>月K共振</span><strong id="monthly-ma-alignment">-</strong></div></div></div>
        <div class="card"><h3>型態 + 籌碼 + MACD</h3><div class="check-list"><div class="check"><span>突破型態</span><strong id="pattern-breakout">-</strong></div><div class="check"><span>W 型態</span><strong id="pattern-w">-</strong></div><div class="check"><span>N 字型態</span><strong id="pattern-n">-</strong></div><div class="check"><span>平台整理轉強</span><strong id="pattern-platform">-</strong></div><div class="check"><span>均線開花</span><strong id="pattern-bloom">-</strong></div><div class="check"><span>籌碼總分</span><strong id="shareholder-score">-</strong></div><div class="check"><span>法人/投信</span><strong id="institution-bias">-</strong></div></div></div>
        <div class="card"><h3>進場 / 持股 / 出場</h3><div class="check-list"><div class="check"><span>開盤八法紅紅紅</span><strong id="trigger-red3">-</strong></div><div class="check"><span>5K爆大量回撤3MA</span><strong id="trigger-volume">-</strong></div><div class="check"><span>連三黑回測3MA</span><strong id="trigger-black3">-</strong></div><div class="check"><span>60K MACD轉強</span><strong id="trigger-macd">-</strong></div></div><div style="margin-top:12px"><div class="rule-line">短線：日K 3MA / 8MA</div><div class="rule-line">中線：週K均線排列</div><div class="rule-line">長線：月K 3MA 不破續抱</div><div class="rule-line" id="risk-note">-</div></div></div>
      </div>
    </section>

    <section>
      <h2>選股池更新與汰換</h2>
      <div class="grid pool-grid">
        <div class="card pool-card selected"><h3>入選名單</h3><div id="selected-pool"></div></div>
        <div class="card pool-card operation"><h3>操作組</h3><p class="muted">操作組規則待補，目前先保留空白。</p><div id="operation-pool"></div></div>
        <div class="card pool-card watch"><h3>觀察組</h3><div id="watch-pool"></div></div>
        <div class="card pool-card eliminate"><h3>淘汰清單</h3><p class="muted">刪除或淘汰標的不特別展示；若未來要看歷史，可查 reports。</p><div id="eliminate-pool"></div></div>
      </div>
    </section>

    <section>
      <h2>後驗追蹤</h2>
      <table><thead><tr><th>掃描日期</th><th>股票</th><th>候選分層</th><th>當日價格</th><th>1D</th><th>3D</th><th>5D</th><th>分層驗證</th></tr></thead><tbody id="tracking-body"></tbody></table>
    </section>

    <section>
      <h2>策略規則</h2>
      <div class="grid detail-grid">
        <div class="card"><h3>核心原則</h3><div class="rule-line">大盤跌幅超過 3%：轉保守、不主動攻擊、降低新倉、不追價。</div><div class="rule-line">只做主流題材、強勢族群、攻擊量、法人/籌碼偏多、多頭均線。</div></div>
        <div class="card"><h3>進場 SOP</h3><div class="rule-line">先看型態，再看日/週/月均線共振，最後才看 5K 節奏與 60K MACD。</div><div class="rule-line">第三根 5K 紅K、爆量回撤 3MA、連三黑回測 3MA，需配合動能確認。</div></div>
        <div class="card"><h3>持股與汰換</h3><div class="rule-line">短線看日K 3MA / 8MA；中線看週K；長線看月K 3MA。</div><div class="rule-line">每週日更新選股池；結構破壞、跌破月K 3MA、主流退潮或籌碼鬆動即移出。</div></div>
      </div>
    </section>
  </main>
  <script>
    const dashboardData = __DASHBOARD_DATA__;
    const candidates = dashboardData.candidates || [];
    const state = { query: "", decision: "all", group: "all", selected: candidates[0] || null };
    const byId = (id) => document.getElementById(id);
    const fmt = (value, digits = 2) => value === "" || value === null || value === undefined || Number.isNaN(Number(value)) ? "-" : Number(value).toFixed(digits);
    const pct = (value) => value === null || value === undefined || value === "" ? "-" : `${Number(value).toFixed(2)}%`;
    const yesNo = (value) => value ? '<span class="pos">是</span>' : '<span class="muted">否</span>';
    function tagClass(value) {
      if (value === "入選名單") return "selected";
      if (value === "操作組") return "operation";
      if (value === "觀察組") return "watch";
      if (value === "淘汰") return "eliminate";
      if (value === "hold") return "hold";
      if (value === "accept") return "accept";
      if (value === "reject") return "reject";
      return "watch";
    }
    function filteredCandidates() {
      return candidates.filter((item) => {
        const q = state.query.trim().toLowerCase();
        const matchQuery = !q || `${item.symbol} ${item.name}`.toLowerCase().includes(q);
        const matchDecision = state.decision === "all" || item.decision === state.decision;
        const matchGroup = state.group === "all" || item.group_assignment === state.group;
        return matchQuery && matchDecision && matchGroup;
      }).sort((a, b) => Number(b.score) - Number(a.score));
    }
    function renderMetrics() {
      byId("generated-at").textContent = dashboardData.generated_at;
      byId("latest-day").textContent = dashboardData.latest_completed_day;
      byId("market-note").textContent = dashboardData.market_note;
      byId("selection-note").textContent = `選股日：${dashboardData.selection.selection_date} / 使用資料：${dashboardData.selection.source_week} / 適用週期：${dashboardData.selection.target_week} / 來源：${dashboardData.selection.source}`;
      byId("metric-total").textContent = candidates.length;
      byId("metric-primary").textContent = candidates.filter((x) => x.score >= 85).length;
      byId("metric-secondary").textContent = candidates.filter((x) => x.score >= 55 && x.score < 85).length;
      byId("operation-mode").textContent = candidates.some((x) => x.index_state === "保守") ? "保守" : "正常";
    }
    function renderCandidateTable() {
      const rows = filteredCandidates();
      byId("candidate-body").innerHTML = rows.map((item) => `
        <tr data-symbol="${item.symbol}">
          <td><div class="symbol">${item.symbol}</div><div class="muted">${item.name}</div></td>
          <td>${fmt(item.latest_price)}<br><span class="${Number(item.change_pct) >= 0 ? "pos" : "neg"}">${pct(item.change_pct)}</span></td>
          <td><strong>${fmt(item.score)}</strong></td>
          <td><span class="tag ${tagClass(item.decision)}">${item.decision}</span></td>
          <td><span class="tag ${tagClass(item.group_assignment)}">${item.group_assignment}</span></td>
          <td>${item.pattern_type}</td>
          <td>${item.market_state}</td>
          <td>${item.chip_state}</td>
          <td>${item.entry_trigger}</td>
          <td>${item.reason}</td>
        </tr>`).join("");
      [...byId("candidate-body").querySelectorAll("tr")].forEach((row) => {
        row.addEventListener("click", () => { state.selected = candidates.find((item) => item.symbol === row.dataset.symbol); renderDetail(); });
      });
    }
    function renderDetail() {
      const item = state.selected;
      if (!item) return;
      byId("detail-symbol").textContent = `${item.symbol} ${item.name}`;
      byId("detail-reason").textContent = item.reason;
      byId("detail-group").textContent = item.group_assignment;
      byId("detail-group").className = `tag ${tagClass(item.group_assignment)}`;
      byId("ma-grid").innerHTML = Object.entries(item.ma).map(([key, value]) => `<div class="kv"><span>${key}</span><strong>${fmt(value)}</strong></div>`).join("");
      byId("daily-ma-alignment").textContent = item.daily_ma_alignment;
      byId("weekly-ma-alignment").textContent = item.weekly_ma_alignment;
      byId("monthly-ma-alignment").textContent = item.monthly_ma_alignment;
      byId("pattern-breakout").innerHTML = yesNo(item.patterns["突破"]);
      byId("pattern-w").innerHTML = yesNo(item.patterns["W"]);
      byId("pattern-n").innerHTML = yesNo(item.patterns["N字"]);
      byId("pattern-platform").innerHTML = yesNo(item.patterns["平台"]);
      byId("pattern-bloom").innerHTML = yesNo(item.patterns["開花"]);
      byId("shareholder-score").textContent = item.shareholder_score;
      byId("institution-bias").textContent = item.institution_bias;
      byId("trigger-red3").innerHTML = yesNo(item.triggers["開盤八法紅紅紅"]);
      byId("trigger-volume").innerHTML = yesNo(item.triggers["5K爆大量回撤3MA"]);
      byId("trigger-black3").innerHTML = yesNo(item.triggers["連三黑回測3MA"]);
      byId("trigger-macd").innerHTML = yesNo(item.triggers["60K MACD轉強"]);
      byId("risk-note").textContent = item.risk_note;
    }
    function renderPools() {
      const groups = {
        "selected-pool": candidates.filter((x) => x.group_assignment === "入選名單"),
        "operation-pool": candidates.filter((x) => x.group_assignment === "操作組"),
        "watch-pool": candidates.filter((x) => x.group_assignment === "觀察組"),
        "eliminate-pool": candidates.filter((x) => x.group_assignment === "淘汰")
      };
      Object.entries(groups).forEach(([id, rows]) => {
        byId(id).innerHTML = rows.length ? rows.map((item) => `<div class="pool-item"><strong>${item.symbol} ${item.name}</strong><br><span class="muted">Score ${fmt(item.score)} / ${item.pattern_type} / ${item.entry_trigger}</span></div>`).join("") : '<div class="muted">無</div>';
      });
    }
    function renderTracking() {
      byId("tracking-body").innerHTML = candidates.map((item) => `<tr><td>${dashboardData.selection.selection_date}</td><td><strong>${item.symbol}</strong><br><span class="muted">${item.name}</span></td><td>${item.group_assignment}</td><td>${fmt(item.latest_price)}</td><td>${pct(item.next_1d_return)}</td><td>${pct(item.next_3d_return)}</td><td>${pct(item.next_5d_return)}</td><td class="muted">等待後續日K驗證</td></tr>`).join("");
    }
    function renderAll() { renderMetrics(); renderCandidateTable(); renderDetail(); renderPools(); renderTracking(); }
    byId("search").addEventListener("input", (event) => { state.query = event.target.value; renderCandidateTable(); });
    byId("decision-filter").addEventListener("change", (event) => { state.decision = event.target.value; renderCandidateTable(); });
    byId("group-filter").addEventListener("change", (event) => { state.group = event.target.value; renderCandidateTable(); });
    renderAll();
  </script>
</body>
</html>
"""
    html_text = html_text.replace(
        "__DASHBOARD_DATA__",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
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
