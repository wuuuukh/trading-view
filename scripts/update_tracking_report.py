from __future__ import annotations

import csv
import html
import json
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request
from urllib.request import urlopen

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
    "2375": "凱美",
    "2478": "大毅",
    "4916": "事欣科",
    "6141": "柏承",
    "6770": "力積電",
}

PAPER_INITIAL_CAPITAL = 10_000.0
MIN_DAILY_VOLUME_SHARES = 500_000
MIN_DAILY_VOLUME_LOTS = 500


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


def load_latest_paper_trades() -> dict[str, object]:
    paths = sorted(
        (ROOT / "reports").glob("paper_trade_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        return {"source_file": "", "rows": []}
    path = paths[0]
    rows = read_csv_rows(path)
    for row in rows:
        symbol = str(row.get("symbol", ""))
        if row.get("name") == symbol:
            row["name"] = SYMBOL_NAMES.get(symbol, symbol)
    return {"source_file": path.name, "rows": rows}


def load_operation_events(latest_day: str) -> dict[str, object]:
    path = ROOT / "reports" / f"operation_events_{latest_day}.csv"
    if not path.exists():
        return {"source_file": "", "rows": []}
    return {"source_file": path.name, "rows": read_csv_rows(path)}


def build_postmarket_risk_review(paper_trading: dict[str, object], latest_day: str) -> dict[str, object]:
    rows = [
        row for row in paper_trading.get("rows", [])
        if "auto risk executor" not in str(row.get("notes", ""))
    ]
    state = _ledger_state_for_risk(rows)
    findings: list[dict[str, object]] = []

    for symbol, position in state["positions"].items():
        shares = int(position.get("shares", 0))
        if shares <= 0:
            continue
        risk_row = _latest_daily_risk_row(symbol)
        if not risk_row or risk_row["date"] != latest_day:
            findings.append(
                {
                    "symbol": symbol,
                    "name": SYMBOL_NAMES.get(symbol, symbol),
                    "severity": "data_missing",
                    "missed_action": "無法判斷",
                    "reason": f"{symbol} 缺少 {latest_day} 完整日K，不能盤後回看風控。",
                    "next_day_feedback": "明日盤前先確認資料源，資料未更新時不得自動交易。",
                }
            )
            continue
        ma3 = risk_row.get("ma3")
        ma8 = risk_row.get("ma8")
        open_price = float(risk_row.get("open") or 0.0)
        close_price = float(risk_row.get("close") or 0.0)
        cost_basis = float(position.get("cost_basis") or 0.0)
        if not ma3 or not ma8 or open_price <= 0 or close_price <= 0 or cost_basis <= 0:
            continue

        if open_price < float(ma3):
            findings.append(
                {
                    "symbol": symbol,
                    "name": SYMBOL_NAMES.get(symbol, symbol),
                    "severity": "missed_intraday_risk",
                    "missed_action": "盤中應先減碼 1/2",
                    "reason": f"開盤 {open_price:.2f} < 日K 3MA {float(ma3):.2f}，盤中監控若有啟動應立即先出 1/2。",
                    "next_day_feedback": "明日盤中監控必須先處理持有股開盤 3MA 風控；若資料缺失，記為 blocked 不能默默跳過。",
                }
            )
        stop_price = cost_basis * 0.97
        if close_price <= stop_price:
            findings.append(
                {
                    "symbol": symbol,
                    "name": SYMBOL_NAMES.get(symbol, symbol),
                    "severity": "missed_stop_loss",
                    "missed_action": "盤中/收盤前應全出",
                    "reason": f"收盤 {close_price:.2f} <= 3% 停損價 {stop_price:.2f}，應列為重大漏判。",
                    "next_day_feedback": "明日不允許攤平；若仍持有，開盤優先檢查是否補救出場。",
                }
            )
        elif close_price < float(ma8):
            findings.append(
                {
                    "symbol": symbol,
                    "name": SYMBOL_NAMES.get(symbol, symbol),
                    "severity": "missed_exit_rule",
                    "missed_action": "跌破日K 8MA 應全出",
                    "reason": f"收盤 {close_price:.2f} < 日K 8MA {float(ma8):.2f}，盤中監控應升級為出場風控。",
                    "next_day_feedback": "明日開盤若仍未站回 8MA，優先出清剩餘部位。",
                }
            )

    review = {
        "date": latest_day,
        "source": "postmarket_review_only_not_trade_execution",
        "summary": "盤後只做漏判檢討與明日決策回饋，不再補寫交易帳本。",
        "findings": findings,
    }
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"postmarket_review_{latest_day}.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    return review


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


def fetch_json(url: str) -> object:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def build_yahoo_index(symbol: str, label: str) -> dict[str, object]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?range=10d&interval=1d"
    data = fetch_json(url)
    results = data.get("chart", {}).get("result") or []
    if not results:
        raise ValueError(f"No chart data returned for {symbol}")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators", {}).get("quote") or [{}])[0]
    opens = quotes.get("open") or []
    highs = quotes.get("high") or []
    lows = quotes.get("low") or []
    closes = quotes.get("close") or []
    volumes = quotes.get("volume") or []
    rows: list[dict[str, object]] = []
    for idx, timestamp in enumerate(timestamps):
        close = closes[idx] if idx < len(closes) else None
        open_price = opens[idx] if idx < len(opens) else None
        high = highs[idx] if idx < len(highs) else None
        low = lows[idx] if idx < len(lows) else None
        if close is None or open_price is None or high is None or low is None:
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(int(timestamp)).date().isoformat(),
                "open": float(open_price),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volumes[idx]) if idx < len(volumes) and volumes[idx] is not None else None,
            }
        )
    if not rows:
        raise ValueError(f"No completed daily candle returned for {symbol}")
    latest = rows[-1]
    previous_close = rows[-2]["close"] if len(rows) >= 2 else result.get("meta", {}).get("chartPreviousClose", latest["close"])
    previous_close = float(previous_close or latest["close"])
    change = float(latest["close"]) - previous_close
    return {
        "label": label,
        "symbol": symbol,
        "date": latest["date"],
        "value": round(float(latest["close"]), 2),
        "change": round(change, 2),
        "pct": round(change / previous_close * 100, 2) if previous_close else 0.0,
        "volume": round(float(latest["volume"]) / 100_000_000, 1) if latest.get("volume") else "",
        "open": round(float(latest["open"]), 2),
        "high": round(float(latest["high"]), 2),
        "low": round(float(latest["low"]), 2),
        "prev": round(previous_close, 2),
        "source": "Yahoo Finance chart",
    }


def parse_float(value: object) -> float:
    return float(str(value).replace(",", "").strip())


def roc_date_to_iso(value: object) -> str:
    text = str(value).strip()
    if len(text) == 7:
        year = int(text[:3]) + 1911
        return f"{year:04d}-{int(text[3:5]):02d}-{int(text[5:7]):02d}"
    if len(text) == 8:
        return f"{int(text[:4]):04d}-{int(text[4:6]):02d}-{int(text[6:8]):02d}"
    return text


def build_tpex_official_index() -> dict[str, object]:
    index_rows = fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_index")
    amount_rows = fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_daily_trading_index")
    if not isinstance(index_rows, list) or not index_rows:
        raise ValueError("No TPEx index data returned")
    completed_rows = [row for row in index_rows if row.get("Close") not in ("", None, "--")]
    if not completed_rows:
        raise ValueError("No completed TPEx index candle returned")
    latest = sorted(completed_rows, key=lambda row: str(row.get("Date", "")))[-1]
    close = parse_float(latest["Close"])
    change = parse_float(latest.get("Change", 0))
    prev = close - change
    trade_amount = ""
    if isinstance(amount_rows, list):
        latest_date = str(latest.get("Date", ""))
        roc_date = f"{int(latest_date[:4]) - 1911:03d}{latest_date[4:]}" if len(latest_date) == 8 else latest_date
        amount_by_date = {str(row.get("Date")): row for row in amount_rows}
        amount = amount_by_date.get(roc_date, {}).get("TradeAmount")
        if amount not in ("", None):
            trade_amount = round(parse_float(amount) / 100_000_000, 1)
    return {
        "label": "上櫃指數",
        "symbol": "TPEx",
        "date": roc_date_to_iso(latest.get("Date", "")),
        "value": round(close, 2),
        "change": round(change, 2),
        "pct": round(change / prev * 100, 2) if prev else 0.0,
        "volume": trade_amount,
        "open": round(parse_float(latest["Open"]), 2),
        "high": round(parse_float(latest["High"]), 2),
        "low": round(parse_float(latest["Low"]), 2),
        "prev": round(prev, 2),
        "source": "TPEx OpenAPI tpex_index",
    }


def build_market_indices() -> dict[str, dict[str, object]]:
    fallback = {
        "twse": {
            "label": "加權指數",
            "symbol": "^TWII",
            "date": "",
            "value": "",
            "change": "",
            "pct": "",
            "volume": "",
            "open": "",
            "high": "",
            "low": "",
            "prev": "",
            "source": "unavailable",
        },
        "otc": {
            "label": "上櫃指數",
            "symbol": "^TWOII",
            "date": "",
            "value": "",
            "change": "",
            "pct": "",
            "volume": "",
            "open": "",
            "high": "",
            "low": "",
            "prev": "",
            "source": "unavailable",
        },
    }
    try:
        fallback["twse"] = build_yahoo_index("^TWII", "加權指數")
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError):
        pass
    try:
        fallback["otc"] = build_tpex_official_index()
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError):
        pass
    return fallback


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
    latest = item.get("details", {}).get("latest", {})
    if is_low_daily_volume(latest.get("volume")):
        return "成交量低於500張，不操作"
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


def to_float(value: object, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_low_daily_volume(volume: object) -> bool:
    value = to_float(volume, 0.0) or 0.0
    return value < MIN_DAILY_VOLUME_SHARES


def volume_lots(volume: object) -> float:
    return (to_float(volume, 0.0) or 0.0) / 1000


def to_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


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


def period_3ma(symbol: str) -> dict[str, float]:
    rows = read_csv_rows(ROOT / "data" / "ohlcv" / f"{symbol}.csv")
    weeks: dict[tuple[int, int], tuple[datetime, float]] = {}
    months: dict[tuple[int, int], tuple[datetime, float]] = {}
    for row in rows:
        day_text = str(row.get("timestamp") or row.get("date") or "")
        try:
            day = datetime.strptime(day_text, "%Y-%m-%d")
        except ValueError:
            continue
        close = to_float(row.get("close"))
        if close is None:
            continue
        weeks[day.isocalendar()[:2]] = (day, close)
        months[(day.year, day.month)] = (day, close)
    weekly = [close for _, close in sorted(weeks.values(), key=lambda item: item[0])]
    monthly = [close for _, close in sorted(months.values(), key=lambda item: item[0])]
    return {
        "weekly3": round(sum(weekly[-3:]) / 3, 2) if len(weekly) >= 3 else 0.0,
        "monthly3": round(sum(monthly[-3:]) / 3, 2) if len(monthly) >= 3 else 0.0,
    }


def proximity_label(price: float | None, level: float | None, tolerance: float = 0.025) -> str:
    if not price or not level:
        return "待確認"
    gap = (price - level) / level
    if abs(gap) <= tolerance:
        return "正在測試"
    if gap > tolerance:
        return "站上"
    return "跌破"


def dynamic_reason(symbol: str, item: dict[str, object], group_label: str, close: object, low: object, ma3: object, ma8: object, ma21: object) -> str:
    close_n = to_float(close)
    low_n = to_float(low)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    ma21_n = to_float(ma21)
    volume_ratio = to_float(item.get("volume_ratio"), 0.0) or 0.0
    pattern = display_pattern(item.get("pattern_type"))
    score = format_number(item.get("score"))
    if close_n is None or ma3_n is None or ma8_n is None:
        return f"{symbol} 資料不足，先維持 {group_label}，等下一次日K與盤中5K確認。"

    period = period_3ma(symbol)
    weekly3 = period["weekly3"]
    monthly3 = period["monthly3"]
    low_to_confluence = bool(low_n and weekly3 and monthly3 and low_n <= max(weekly3, monthly3) * 1.02 and close_n >= min(weekly3, monthly3) * 0.98)
    above_attack = close_n >= ma3_n and ma3_n >= ma8_n
    between_3_8 = close_n < ma3_n and close_n >= ma8_n
    below_8 = close_n < ma8_n

    if group_label == "操作組" and symbol in {"3481", "6141"}:
        return f"{symbol} 已持有，重點不是重新分類，而是用日3MA {format_number(ma3)}、日8MA {format_number(ma8)}、週3MA {format_number(weekly3)}、月3MA {format_number(monthly3)} 管理續抱/加碼/防守。"
    if is_low_daily_volume(item.get("volume")):
        return f"{symbol} 日成交量約 {format_number(volume_lots(item.get('volume')), 0)} 張，低於新增門檻 {MIN_DAILY_VOLUME_LOTS} 張；即使型態符合，也不列入新進場操作。"
    if low_to_confluence:
        return f"{symbol} 低點回測週3MA {format_number(weekly3)} 與月3MA {format_number(monthly3)} 交會區後收回，屬於盤中可動態升級的承接型候選；依新規則，回撤月K 3MA 時可直接買入，不必等待5K轉紅。"
    if above_attack and volume_ratio >= 1.2:
        return f"{symbol} 收盤站上日3MA {format_number(ma3)} 且3MA高於8MA，量比 {format_number(volume_ratio)}，偏攻擊結構；盤中若5K乾淨可升操作判斷。"
    if above_attack:
        return f"{symbol} 價格仍站上日3MA {format_number(ma3)}，但量比 {format_number(volume_ratio)} 不算強，屬於量能待確認的偏多觀察，不適合直接追。"
    if between_3_8:
        return f"{symbol} 跌破日3MA {format_number(ma3)} 但仍守日8MA {format_number(ma8)}，屬觀察候選；盤中站回3MA才升操作，跌破8MA轉防守。"
    if below_8:
        return f"{symbol} 已跌破日8MA {format_number(ma8)}，短線結構轉弱，除非快速站回，否則不主動操作。"
    if ma21_n and close_n >= ma21_n:
        return f"{symbol} 結構尚未完全破壞，但未站回攻擊線，先觀察週/月支撐是否重新形成。"
    return f"{symbol} Score {score}，型態 {pattern}，目前不是乾淨攻擊點，等待重新站回日3MA或回測週/月3MA交會。"


def dynamic_entry_trigger(symbol: str, group_label: str, close: object, low: object, ma3: object, ma8: object) -> str:
    close_n = to_float(close)
    low_n = to_float(low)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    period = period_3ma(symbol)
    weekly3 = period["weekly3"]
    monthly3 = period["monthly3"]
    if group_label == "操作組" and symbol in {"3481", "6141"}:
        return "持有管理：續抱 / 回測加碼 / 跌破8MA防守"
    if low_n and weekly3 and monthly3 and low_n <= max(weekly3, monthly3) * 1.02:
        return "回測週/月3MA交會；回撤月K3MA直接買，不等5K轉紅"
    if close_n and ma3_n and close_n >= ma3_n:
        return "站上日3MA，等5K紅K與60K MACD確認"
    if close_n and ma8_n and close_n >= ma8_n:
        return "跌破3MA但守8MA，站回3MA才升操作"
    return "跌破8MA或結構弱化，不主動進場"


def dynamic_entry_trigger_with_volume(symbol: str, item: dict[str, object], group_label: str, close: object, low: object, ma3: object, ma8: object) -> str:
    if is_low_daily_volume(item.get("volume")):
        return f"日成交量低於{MIN_DAILY_VOLUME_LOTS}張，取消新進場"
    return dynamic_entry_trigger(symbol, group_label, close, low, ma3, ma8)


def dynamic_risk_note(symbol: str, close: object, ma3: object, ma8: object) -> str:
    period = period_3ma(symbol)
    close_n = to_float(close)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    if close_n and ma8_n and close_n < ma8_n:
        return f"{symbol} 已低於日8MA {format_number(ma8)}，短線以防守為主；重新站回8MA前不拉操作組。"
    if close_n and ma3_n and close_n < ma3_n:
        return f"{symbol} 跌破日3MA {format_number(ma3)} 但未必轉空；若守住日8MA {format_number(ma8)}，盤中站回3MA才可升級。週3MA {format_number(period['weekly3'])}、月3MA {format_number(period['monthly3'])} 作為回測交會參考。"
    return f"{symbol} 短線守日3MA {format_number(ma3)} 偏強；回測週3MA {format_number(period['weekly3'])} / 月3MA {format_number(period['monthly3'])} 不破才是較好的加碼或新進場位置。"


def dynamic_risk_note_with_volume(symbol: str, item: dict[str, object], close: object, ma3: object, ma8: object) -> str:
    if is_low_daily_volume(item.get("volume")):
        return f"{symbol} 日成交量約 {format_number(volume_lots(item.get('volume')), 0)} 張，低於{MIN_DAILY_VOLUME_LOTS}張；新進場一律擋下，持有股只做既有部位防守。"
    return dynamic_risk_note(symbol, close, ma3, ma8)


def dynamic_period_alignment(symbol: str, close: object, ma3: object, ma8: object, ma21: object) -> tuple[str, str, str]:
    close_n = to_float(close)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    ma21_n = to_float(ma21)
    period = period_3ma(symbol)
    daily = ma_alignment(close, ma3, ma8, ma21)
    if close_n and ma3_n and ma8_n and close_n < ma3_n and close_n >= ma8_n:
        daily = "觀察：跌破3MA但守8MA"
    elif close_n and ma8_n and close_n < ma8_n:
        daily = "防守：跌破8MA"
    weekly = f"{proximity_label(close_n, period['weekly3'])}週3MA {format_number(period['weekly3'])}"
    monthly = f"{proximity_label(close_n, period['monthly3'])}月3MA {format_number(period['monthly3'])}"
    if ma3_n and ma8_n and ma21_n and ma3_n > ma8_n > ma21_n:
        daily += "，均線多排"
    return daily, weekly, monthly


def dynamic_patterns(item: dict[str, object], close: object, ma3: object, ma8: object, ma21: object) -> dict[str, bool]:
    pattern_type = item.get("pattern_type")
    close_n = to_float(close)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    ma21_n = to_float(ma21)
    volume_ratio = to_float(item.get("volume_ratio"), 0.0) or 0.0
    return {
        "突破": bool(close_n and item.get("key_level") and close_n >= to_float(item.get("key_level"), 10**9) and volume_ratio >= 1.0),
        "W": pattern_type == "w_pattern",
        "N字": pattern_type == "n_pattern",
        "平台": pattern_type == "base_breakout",
        "開花": bool(close_n and ma3_n and ma8_n and ma21_n and close_n >= ma3_n and ma3_n > ma8_n > ma21_n),
    }


def dynamic_triggers(symbol: str, close: object, low: object, ma3: object, ma8: object, change_pct: object, volume_ratio: object) -> dict[str, bool]:
    close_n = to_float(close)
    low_n = to_float(low)
    ma3_n = to_float(ma3)
    ma8_n = to_float(ma8)
    change_n = to_float(change_pct, 0.0) or 0.0
    vol_n = to_float(volume_ratio, 0.0) or 0.0
    period = period_3ma(symbol)
    confluence = bool(low_n and period["weekly3"] and period["monthly3"] and low_n <= max(period["weekly3"], period["monthly3"]) * 1.02)
    return {
        "開盤八法紅紅紅": bool(close_n and ma3_n and close_n >= ma3_n and change_n > 0 and vol_n >= 1.0),
        "5K爆大量回撤3MA": bool(low_n and ma3_n and ma8_n and low_n <= ma3_n * 1.02 and close_n and close_n >= ma8_n and vol_n >= 1.0),
        "連三黑回測3MA": bool(close_n and ma3_n and ma8_n and close_n < ma3_n and close_n >= ma8_n),
        "60K MACD轉強": bool((close_n and ma3_n and close_n >= ma3_n and vol_n >= 1.0) or confluence),
    }


def clean_dashboard_reason(symbol: str, item: dict[str, object], group_label: str) -> str:
    pattern = display_pattern(item.get("pattern_type"))
    score = format_number(item.get("score"))
    volume_ratio = format_number(item.get("volume_ratio"))
    if group_label == "操作組":
        return f"{symbol} 符合操作組或持有管理條件；Score {score}，型態 {pattern}，量比 {volume_ratio}。等待 5K 切入點、60K MACD 或持股管理訊號。"
    if group_label == "入選名單":
        return f"{symbol} 符合本週神秘金字塔篩選條件，列入入選名單；Score {score}，型態 {pattern}，量比 {volume_ratio}。操作組規則待補，暫不直接視為可操作。"
    return f"{symbol} 先列觀察組；Score {score}，型態 {pattern}，量比 {volume_ratio}。補齊籌碼與切入條件前不進操作組。"


def next_weekday(value: str) -> str:
    try:
        day = date.fromisoformat(value)
    except ValueError:
        day = date.today()
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.isoformat()


def build_account_state(paper_trading: dict[str, object], market: dict[str, dict[str, object]]) -> dict[str, object]:
    cash = PAPER_INITIAL_CAPITAL
    realized_pnl = 0.0
    positions: dict[str, dict[str, object]] = {}

    for row in paper_trading.get("rows", []):
        symbol = str(row.get("symbol", ""))
        if not symbol:
            continue
        side = str(row.get("side", "")).lower()
        shares = to_int(row.get("shares"))
        price = to_float(row.get("price"), 0.0) or 0.0
        if row.get("cash_after") not in ("", None):
            cash = to_float(row.get("cash_after"), cash) or cash
        if row.get("realized_pnl") not in ("", None):
            realized_pnl = to_float(row.get("realized_pnl"), realized_pnl) or realized_pnl

        position = positions.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": SYMBOL_NAMES.get(symbol, str(row.get("name") or symbol)),
                "shares": 0,
                "cost_basis": 0.0,
            },
        )
        if side == "buy":
            old_shares = int(position["shares"])
            old_cost = float(position["cost_basis"])
            new_shares = old_shares + shares
            if new_shares > 0:
                position["cost_basis"] = ((old_shares * old_cost) + (shares * price)) / new_shares
            position["shares"] = new_shares
        elif side == "sell":
            position["shares"] = max(0, int(position["shares"]) - shares)

    open_positions = []
    position_value = 0.0
    unrealized_pnl = 0.0
    for symbol, position in positions.items():
        shares = int(position["shares"])
        if shares <= 0:
            continue
        latest_price = to_float(market.get(symbol, {}).get("close"), to_float(position["cost_basis"], 0.0)) or 0.0
        cost_basis = float(position["cost_basis"])
        value = latest_price * shares
        pnl = (latest_price - cost_basis) * shares
        position_value += value
        unrealized_pnl += pnl
        open_positions.append(
            {
                "symbol": symbol,
                "name": position["name"],
                "shares": shares,
                "cost_basis": round(cost_basis, 2),
                "latest_price": round(latest_price, 2),
                "market_value": round(value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pct": round((latest_price - cost_basis) / cost_basis * 100, 2) if cost_basis else 0.0,
                "status": "持有管理",
            }
        )

    total_assets = cash + position_value
    return {
        "initial_capital": PAPER_INITIAL_CAPITAL,
        "cash": round(cash, 2),
        "position_value": round(position_value, 2),
        "total_assets": round(total_assets, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "total_pnl": round(total_assets - PAPER_INITIAL_CAPITAL, 2),
        "capital_usage_pct": round(position_value / total_assets * 100, 2) if total_assets else 0.0,
        "positions": open_positions,
    }


def _ledger_state_for_risk(rows: list[dict[str, object]]) -> dict[str, object]:
    cash = PAPER_INITIAL_CAPITAL
    realized_pnl = 0.0
    positions: dict[str, dict[str, object]] = {}

    for row in rows:
        symbol = str(row.get("symbol", ""))
        if not symbol:
            continue
        side = str(row.get("side", "")).lower()
        shares = to_int(row.get("shares"))
        price = to_float(row.get("price"), 0.0) or 0.0
        if row.get("cash_after") not in ("", None):
            cash = to_float(row.get("cash_after"), cash) or cash
        if row.get("realized_pnl") not in ("", None):
            realized_pnl = to_float(row.get("realized_pnl"), realized_pnl) or realized_pnl

        position = positions.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": SYMBOL_NAMES.get(symbol, str(row.get("name") or symbol)),
                "shares": 0,
                "cost_basis": 0.0,
            },
        )
        if side == "buy":
            old_shares = int(position["shares"])
            old_cost = float(position["cost_basis"])
            new_shares = old_shares + shares
            if new_shares > 0:
                position["cost_basis"] = ((old_shares * old_cost) + (shares * price)) / new_shares
            position["shares"] = new_shares
        elif side == "sell":
            sold = min(shares, int(position["shares"]))
            cost_basis = float(position["cost_basis"])
            if row.get("realized_pnl") in ("", None):
                realized_pnl += (price - cost_basis) * sold
            position["shares"] = max(0, int(position["shares"]) - sold)

    return {"cash": cash, "realized_pnl": realized_pnl, "positions": positions}


def _latest_daily_risk_row(symbol: str) -> dict[str, object] | None:
    path = ROOT / "data" / "ohlcv" / f"{symbol}.csv"
    if not path.exists():
        return None
    rows = read_csv_rows(path)
    if not rows:
        return None
    closes = [to_float(row.get("close"), 0.0) or 0.0 for row in rows]
    latest = rows[-1]

    def avg_tail(count: int) -> float | None:
        values = closes[-count:]
        if len(values) < count or any(value <= 0 for value in values):
            return None
        return sum(values) / count

    return {
        "date": str(latest.get("timestamp", "")),
        "open": to_float(latest.get("open"), 0.0) or 0.0,
        "close": to_float(latest.get("close"), 0.0) or 0.0,
        "ma3": avg_tail(3),
        "ma8": avg_tail(8),
    }


def _next_trade_id(rows: list[dict[str, object]]) -> int:
    max_id = 0
    for row in rows:
        value = str(row.get("trade_id", "")).strip().upper()
        if value.startswith("T"):
            try:
                max_id = max(max_id, int(value[1:]))
            except ValueError:
                continue
    return max_id + 1


def _append_sell_trade(
    rows: list[dict[str, object]],
    fieldnames: list[str],
    trade_no: int,
    day: str,
    time_label: str,
    symbol: str,
    price: float,
    shares: int,
    cash: float,
    realized_pnl: float,
    remaining_shares: int,
    reason: str,
    sop_check: str,
    action_key: str,
) -> dict[str, str]:
    gross = round(price * shares, 2)
    row = {
        "trade_id": f"T{trade_no:03d}",
        "date": day,
        "time": time_label,
        "symbol": symbol,
        "name": SYMBOL_NAMES.get(symbol, symbol),
        "side": "sell",
        "price": f"{price:.2f}",
        "shares": str(shares),
        "gross_amount": f"{gross:.2f}",
        "fee_tax": "0.00",
        "cash_after": f"{cash:.2f}",
        "position_after": str(remaining_shares),
        "reason": reason,
        "sop_check": sop_check,
        "hold_days": "",
        "realized_pnl": f"{realized_pnl:.2f}",
        "unrealized_pnl": "0.00",
        "notes": f"auto risk executor; risk_action={action_key}; source_day={day}",
    }
    return {name: str(row.get(name, "")) for name in fieldnames}


def apply_paper_trade_risk_exits(paper_trading: dict[str, object], latest_day: str) -> dict[str, object]:
    # Deprecated: postmarket checks must never create simulated trades.
    # Use build_postmarket_risk_review() for missed-action review instead.
    return paper_trading

    source_file = str(paper_trading.get("source_file") or "")
    if not source_file or latest_day == "n/a":
        return paper_trading

    path = ROOT / "reports" / source_file
    if not path.exists():
        return paper_trading

    rows: list[dict[str, object]] = list(paper_trading.get("rows", []))
    if not rows:
        return paper_trading

    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
    if not fieldnames:
        return paper_trading

    state = _ledger_state_for_risk(rows)
    cash = float(state["cash"])
    realized_pnl = float(state["realized_pnl"])
    positions = state["positions"]
    next_id = _next_trade_id(rows)
    appended: list[dict[str, str]] = []
    existing_actions = {
        (str(row.get("date")), str(row.get("symbol")), str(row.get("notes")))
        for row in rows
        if str(row.get("side", "")).lower() == "sell"
    }

    def already_done(symbol: str, action_key: str) -> bool:
        marker = f"risk_action={action_key}"
        return any(day == latest_day and sym == symbol and marker in notes for day, sym, notes in existing_actions)

    for symbol, position in positions.items():
        shares = int(position.get("shares", 0))
        if shares <= 0:
            continue
        risk_row = _latest_daily_risk_row(symbol)
        if not risk_row or risk_row["date"] != latest_day:
            continue
        ma3 = risk_row.get("ma3")
        ma8 = risk_row.get("ma8")
        open_price = float(risk_row.get("open") or 0.0)
        close_price = float(risk_row.get("close") or 0.0)
        cost_basis = float(position.get("cost_basis") or 0.0)
        if not ma3 or not ma8 or open_price <= 0 or close_price <= 0 or cost_basis <= 0:
            continue

        reduced_at_open = already_done(symbol, "open_below_3ma_reduce")
        if open_price < float(ma3) and not already_done(symbol, "open_below_3ma_reduce"):
            sell_shares = max(1, shares // 2)
            pnl = (open_price - cost_basis) * sell_shares
            cash += open_price * sell_shares
            realized_pnl += pnl
            shares -= sell_shares
            position["shares"] = shares
            reduced_at_open = True
            row = _append_sell_trade(
                rows,
                fieldnames,
                next_id,
                latest_day,
                "09:00_risk",
                symbol,
                open_price,
                sell_shares,
                cash,
                realized_pnl,
                shares,
                "自動風控：開盤跌破日K 3MA，先出 1/2",
                f"open {open_price:.2f} < 3MA {float(ma3):.2f}; 8MA {float(ma8):.2f}",
                "open_below_3ma_reduce",
            )
            rows.append(row)
            appended.append(row)
            existing_actions.add((latest_day, symbol, row["notes"]))
            next_id += 1

        if shares <= 0:
            continue

        stop_price = cost_basis * 0.97
        close_exit_reason = ""
        close_action_key = ""
        if close_price <= stop_price:
            close_exit_reason = "自動風控：突破型虧損達 3%，剩餘部位全出"
            close_action_key = "breakout_stop_loss_exit"
        elif close_price < float(ma8):
            close_exit_reason = "自動風控：收盤跌破日K 8MA，剩餘部位全出"
            close_action_key = "close_below_8ma_exit"
        elif (
            close_price < float(ma3)
            and not reduced_at_open
            and not already_done(symbol, "close_below_3ma_reduce")
        ):
            close_exit_reason = "自動風控：收盤跌破日K 3MA，剩餘部位再降 1/2"
            close_action_key = "close_below_3ma_reduce"

        if close_exit_reason and not already_done(symbol, close_action_key):
            sell_shares = shares if close_action_key.endswith("_exit") else max(1, shares // 2)
            pnl = (close_price - cost_basis) * sell_shares
            cash += close_price * sell_shares
            realized_pnl += pnl
            shares -= sell_shares
            position["shares"] = shares
            row = _append_sell_trade(
                rows,
                fieldnames,
                next_id,
                latest_day,
                "13:30_risk",
                symbol,
                close_price,
                sell_shares,
                cash,
                realized_pnl,
                shares,
                close_exit_reason,
                f"close {close_price:.2f}; 3MA {float(ma3):.2f}; 8MA {float(ma8):.2f}; stop {stop_price:.2f}",
                close_action_key,
            )
            rows.append(row)
            appended.append(row)
            existing_actions.add((latest_day, symbol, row["notes"]))
            next_id += 1

    if not appended:
        return paper_trading

    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{name: str(row.get(name, "")) for name in fieldnames} for row in rows])

    return load_latest_paper_trades()


def promote_held_candidates(candidates: list[dict[str, object]], account: dict[str, object]) -> None:
    held_symbols = {str(position.get("symbol")) for position in account.get("positions", [])}
    for item in candidates:
        if str(item.get("symbol")) in held_symbols:
            ma = item.get("ma", {}) if isinstance(item.get("ma"), dict) else {}
            symbol = str(item.get("symbol"))
            item["group_assignment"] = "操作組"
            item["decision"] = "hold"
            item["entry_trigger"] = "持有部位管理：續抱 / 減碼 / 加碼條件"
            item["reason"] = dynamic_reason(
                symbol,
                item,
                "操作組",
                item.get("latest_price"),
                item.get("latest_low", item.get("latest_price")),
                ma.get("3MA"),
                ma.get("8MA"),
                ma.get("21MA"),
            )


def build_symbol_plan(item: dict[str, object], account: dict[str, object], max_budget: float) -> dict[str, object]:
    price = to_float(item.get("latest_price"), 0.0) or 0.0
    high = to_float(item.get("latest_high"), price) or price
    key_level = to_float(item.get("key_level"), 0.0) or 0.0
    ma = item.get("ma", {}) if isinstance(item.get("ma"), dict) else {}
    ma3 = to_float(ma.get("3MA"), 0.0) or 0.0
    ma8 = to_float(ma.get("8MA"), 0.0) or 0.0
    cash = to_float(account.get("cash"), 0.0) or 0.0
    rough_budget_low = min(2_500.0, cash)
    rough_budget_high = min(3_000.0, cash)
    trigger_price = max(price, high, key_level)
    rough_shares_low = int(rough_budget_low // trigger_price) if trigger_price else 0
    rough_shares_high = int(rough_budget_high // trigger_price) if trigger_price else 0
    stop_price = round(price * 0.97, 2) if price else 0.0
    support_low = round(ma3 * 0.995, 2) if ma3 else 0.0
    support_high = round(ma3 * 1.015, 2) if ma3 else 0.0
    return {
        "symbol": item["symbol"],
        "name": item["name"],
        "latest_price": price,
        "trigger_price": round(trigger_price, 2),
        "score": item.get("score"),
        "pattern_type": item.get("pattern_type"),
        "volume_ratio": item.get("volume_ratio"),
        "ma3": ma3,
        "ma8": ma8,
        "budget_cap": round(max_budget, 2),
        "rough_budget_low": round(rough_budget_low, 2),
        "rough_budget_high": round(rough_budget_high, 2),
        "rough_shares_low": rough_shares_low,
        "rough_shares_high": rough_shares_high,
        "entry_status": "等待盯盤突破確認",
        "sizing_formula": f"前一日粗估 {format_number(rough_budget_low, 0)} - {format_number(rough_budget_high, 0)}；實際股數 = floor(投入資金 / 突破確認後成交價)",
        "stop_price": stop_price,
        "support_range": f"{support_low:.2f} - {support_high:.2f}" if support_low else "-",
        "scenarios": [
            {
                "title": "情境 1：突破確認才進場",
                "condition": f"開盤站穩 {format_number(price)}，或盯盤資料確認突破 {format_number(trigger_price)}；5K 量能放大且不是爆量黑K，60K MACD 同步轉強。",
                "action": f"買第一筆；前一日先抓 {format_number(rough_budget_low, 0)} - {format_number(rough_budget_high, 0)}，約 {rough_shares_low} - {rough_shares_high} 股，實際用成交價重算。",
            },
            {
                "title": "情境 2：突破後回測不破",
                "condition": f"先突破、再回測 {support_low:.2f} - {support_high:.2f} 或突破價不破，回檔量縮後重新轉強。" if support_low else "先突破、再回測突破價不破，回檔量縮後重新轉強。",
                "action": f"低接買；資金仍抓 {format_number(rough_budget_low, 0)} - {format_number(rough_budget_high, 0)}，但未先突破前不低接。",
            },
            {
                "title": "情境 3：未突破或假突破",
                "condition": f"未突破 {format_number(trigger_price)}、突破後馬上跌回、爆量黑K，或跌破 3MA {format_number(ma3)}。",
                "action": f"不進場；沒有量不做，走弱不追，跌破 8MA {format_number(ma8)} 則移回觀察。",
            },
        ],
    }


def build_holding_plan(position: dict[str, object]) -> dict[str, object]:
    latest = to_float(position.get("latest_price"), 0.0) or 0.0
    cost = to_float(position.get("cost_basis"), 0.0) or 0.0
    shares = to_int(position.get("shares"))
    half_shares = shares // 2
    add_shares = min(20, max(0, int(1_000 // latest))) if latest else 0
    return {
        "symbol": str(position["symbol"]),
        "name": position["name"],
        "shares": shares,
        "cost_basis": cost,
        "latest_price": latest,
        "market_value": position.get("market_value"),
        "unrealized_pnl": position.get("unrealized_pnl"),
        "unrealized_pct": position.get("unrealized_pct"),
        "scenarios": [
            {"title": "情境 1：開盤跌破日K 3MA", "condition": "每日開盤，持有股開盤價低於盤前日K 3MA。", "action": f"立即賣出 1/2，約 {half_shares} 股；不等收盤確認。"},
            {"title": "情境 2：開盤站穩日K 3MA", "condition": f"開盤站穩日K 3MA，且沒有爆量黑K。成本 {format_number(cost)} 僅作損益參考。", "action": f"續抱 {shares} 股；放量突破且回測不破才考慮加碼 {add_shares} 股。"},
            {"title": "情境 3：盤中跌破3MA或成本", "condition": f"開盤未破，但盤中跌破日K 3MA或跌破成本 {format_number(cost)} 後站不回。", "action": f"先賣 {half_shares} 股；不攤平、不加碼，跌破日K 8MA 全出。"},
        ],
    }


def build_next_trading_plan(candidates: list[dict[str, object]], account: dict[str, object], latest_day: str) -> dict[str, object]:
    held_symbols = {str(position.get("symbol")) for position in account["positions"]}
    operation_candidates = [
        item
        for item in candidates
        if item.get("group_assignment") == "操作組" and str(item.get("symbol")) not in held_symbols
    ]
    cash = to_float(account.get("cash"), 0.0) or 0.0
    reserve_cash = round(cash * 0.15, 2)
    deployable_cash = max(0.0, cash - reserve_cash)
    per_symbol_budget = deployable_cash / len(operation_candidates) if operation_candidates else 0.0
    return {
        "updated_at": f"{date.today().isoformat()} 18:00",
        "applies_to": next_weekday(latest_day),
        "basis_day": latest_day,
        "cash_allocation_note": f"剩餘資金 {format_number(cash, 0)}；單檔觸發前一日先粗估 2,500 - 3,000，多檔同時觸發時保留 {format_number(reserve_cash, 0)} 後再按強弱分配。",
        "account": account,
        "locked_stocks": [
            {
                "group": item.get("group_assignment"),
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "latest_price": item.get("latest_price"),
                "score": item.get("score"),
                "pattern_type": item.get("pattern_type"),
                "volume_ratio": item.get("volume_ratio"),
                "status": "等待切入點",
            }
            for item in operation_candidates
        ],
        "holding_plans": [build_holding_plan(position) for position in account["positions"]],
        "symbol_plans": [build_symbol_plan(item, account, per_symbol_budget) for item in operation_candidates],
    }


def build_research_dashboard_template() -> str:
    return """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <title>海牛AI自動化交易系統</title>
  <style>
    :root {
      --bg:#f5f7f2; --paper:#ffffff; --panel:#ffffffcc; --ink:#17212b; --muted:#607080;
      --line:#dbe4e8; --teal:#14866d; --teal-soft:#e8f6f0; --blue:#2f67c6; --blue-soft:#eaf2ff;
      --violet:#7a5ad8; --violet-soft:#f0ecff; --orange:#b96b18; --orange-soft:#fff3df;
      --red:#bf2f2f; --red-soft:#fff0ee; --gray:#6c7680; --gray-soft:#f1f3f5;
      --shadow:0 10px 28px rgba(35,48,60,.08);
    }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; color:var(--ink); background:
      radial-gradient(circle at 18% -10%, #e0f2ff 0, transparent 34%),
      radial-gradient(circle at 86% 6%, #e9f7ef 0, transparent 30%),
      linear-gradient(180deg,#f8fbf7 0,#eef4f7 100%);
      font-family:"Aptos","Microsoft JhengHei","PingFang TC",sans-serif; line-height:1.5; letter-spacing:0; }
    main, .header-inner { width:min(1480px, calc(100% - 44px)); margin:0 auto; }
    header { border-bottom:1px solid var(--line); background:rgba(255,255,255,.76); backdrop-filter:blur(14px); position:sticky; top:0; z-index:10; }
    .header-inner { padding:18px 0; display:flex; justify-content:space-between; gap:18px; align-items:center; }
    h1, h2, h3, p { margin:0; }
    h1 { font-size:24px; letter-spacing:.2px; }
    h2 { font-size:20px; margin:30px 0 14px; }
    h3 { font-size:15px; margin-bottom:8px; }
    .subtitle { color:var(--muted); font-size:14px; margin-top:4px; }
    .mode { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
    .badge, .tag { display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:4px 9px; font-size:12px; font-weight:700; border:1px solid var(--line); white-space:nowrap; }
    .badge { background:#fff; color:var(--muted); }
    .page-nav { display:flex; gap:8px; flex-wrap:wrap; margin:18px 0 0; }
    .tab-btn { border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:6px; padding:10px 13px; font-weight:800; font-size:13px; cursor:pointer; }
    .tab-btn.active { background:var(--teal); color:#fff; border-color:var(--teal); }
    .page { display:none; }
    .page.active { display:block; }
    .page.active.hero { display:grid; }
    .hero { display:grid; grid-template-columns:1.2fr .8fr; gap:18px; padding:24px 0 6px; align-items:stretch; }
    .hero-copy, .preview, .card, .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; box-shadow:var(--shadow); }
    .hero-copy { padding:28px; min-height:260px; display:flex; flex-direction:column; justify-content:space-between; }
    .hero-title { font-size:34px; line-height:1.12; max-width:780px; }
    .hero-text { color:var(--muted); max-width:820px; margin-top:12px; }
    .market-snapshot { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin-top:14px; }
    .index-stack { display:grid; gap:10px; }
    .index-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:var(--shadow); }
    .index-card.primary { border-color:#ffd1d6; background:linear-gradient(180deg,#fff,#fff7f8); }
    .index-name { color:var(--muted); font-size:13px; font-weight:800; }
    .index-value { font-size:26px; line-height:1.1; font-weight:900; margin-top:3px; }
    .index-change { margin-top:4px; font-weight:900; }
    .market-picture { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; box-shadow:var(--shadow); }
    .market-picture-top { display:grid; grid-template-columns:1fr auto; gap:14px; align-items:start; }
    .market-big { font-size:38px; line-height:1; color:#ff3347; font-weight:900; letter-spacing:.4px; }
    .market-change { color:#ff3347; font-weight:900; margin-top:7px; }
    .market-date { margin-left:6px; font-weight:600; color:var(--muted); }
    .market-stat-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:14px 0; }
    .market-stat { text-align:center; border-right:1px solid var(--line); }
    .market-stat:last-child { border-right:0; }
    .market-stat span { display:block; color:var(--muted); font-size:12px; }
    .market-stat strong { font-size:17px; }
    .preview { padding:18px; }
    .preview-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-top:12px; }
    .mini { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; min-height:76px; }
    .mini span, .metric span { color:var(--muted); font-size:12px; display:block; }
    .mini strong, .metric strong { font-size:24px; display:block; margin-top:4px; }
    .grid { display:grid; gap:12px; }
    .metrics { grid-template-columns:repeat(6,1fr); }
    .metric { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:var(--shadow); }
    .flow { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
    .flow-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; min-height:138px; position:relative; }
    .flow-card.route { border-color:#d8cfff; background:linear-gradient(180deg,#fff,#f7f4ff); }
    .flow-card.risk { border-color:#bfe5d7; background:linear-gradient(180deg,#fff,#effaf5); }
    .flow-card small { color:var(--muted); display:block; margin-bottom:8px; }
    .flow-card p { color:var(--muted); font-size:13px; }
    .toolbar { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:10px; }
    input, select { height:36px; border:1px solid var(--line); border-radius:6px; background:#fff; padding:0 10px; color:var(--ink); }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:8px; background:#fff; box-shadow:var(--shadow); }
    table { width:100%; border-collapse:collapse; min-width:980px; }
    th, td { padding:11px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
    th { background:#f2f6f7; color:#445464; font-size:12px; white-space:nowrap; }
    tbody tr { cursor:pointer; } tbody tr:hover { background:#f8fbfb; }
    .detail-grid { grid-template-columns:1fr 1.1fr 1.1fr 1fr; }
    .card { padding:15px; }
    .kv-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
    .kv { background:#f8fafb; border:1px solid var(--line); border-radius:6px; padding:9px; }
    .kv span { color:var(--muted); font-size:12px; display:block; }
    .kv strong { margin-top:3px; display:block; }
    .split { grid-template-columns:1fr 1fr; }
    .account-grid { grid-template-columns:repeat(6,1fr); margin-bottom:12px; }
    .history-grid { grid-template-columns:repeat(5,1fr); margin-bottom:12px; }
    .history-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:var(--shadow); min-height:130px; }
    .history-card.current { border-color:#b9e5d5; background:linear-gradient(180deg,#fff,#effaf5); }
    .history-card.missing { background:#f8fafb; color:var(--muted); }
    .history-card strong { display:block; font-size:18px; margin:4px 0; }
    .scenario-grid { grid-template-columns:repeat(3,1fr); margin-top:10px; }
    .scenario { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }
    .weekly-pool-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
    .pool-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; min-height:360px; box-shadow:var(--shadow); }
    .pool-card.selected { background:#eef6ff; border-top:4px solid var(--blue); }
    .pool-card.operation { background:#fff1ef; border-top:4px solid var(--red); }
    .pool-card.watch { background:#fff; border-top:4px solid #cfd9df; }
    .pool-card.eliminate { background:#effaf5; border-top:4px solid var(--teal); }
    .pool-item { border-bottom:1px solid var(--line); padding:10px 0; }
    .pool-item:last-child { border-bottom:0; }
    .review-grid { grid-template-columns:repeat(5,1fr); }
    .review-cards { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
    .issue-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:var(--shadow); }
    .issue-card h3 { color:var(--teal); }
    .review-toolbar { display:flex; align-items:center; gap:10px; margin:10px 0 14px; }
    .review-toolbar label { color:var(--muted); font-size:13px; font-weight:800; }
    .review-toolbar select { min-width:240px; padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:#fff; color:var(--ink); font-weight:800; }
    tr.selected-row { background:#effaf5; box-shadow:inset 4px 0 0 var(--teal); }
    .tag.primary,.tag.approved,.tag.enter,.tag.accept { background:var(--teal-soft); color:var(--teal); border-color:#b9e5d5; }
    .tag.secondary,.tag.long_hold,.tag.long-hold { background:var(--blue-soft); color:var(--blue); border-color:#c8d9ff; }
    .tag.intraday { background:var(--violet-soft); color:var(--violet); border-color:#d7ccff; }
    .tag.wait,.tag.hold,.tag.build,.tag.add,.tag.reduce { background:var(--orange-soft); color:var(--orange); border-color:#f0d2a5; }
    .tag.reject,.tag.blocked,.tag.risk_off,.tag.risk-off,.tag.risk-blocked,.tag.exit,.tag.avoid { background:var(--red-soft); color:var(--red); border-color:#efc1bc; }
    .tag.watch,.tag.none,.tag.not-triggered { background:var(--gray-soft); color:var(--gray); border-color:#d8dde2; }
    .pos { color:var(--red); font-weight:800; } .neg { color:var(--teal); font-weight:800; }
    @media (max-width:1180px) { .hero,.metrics,.flow,.detail-grid,.split,.account-grid,.history-grid,.scenario-grid,.review-grid,.review-cards,.weekly-pool-grid { grid-template-columns:1fr 1fr; } .market-snapshot { grid-template-columns:1fr; } }
    @media (max-width:720px) { main,.header-inner { width:min(100% - 24px, 1480px); } .header-inner,.hero,.metrics,.flow,.detail-grid,.split,.account-grid,.history-grid,.scenario-grid,.market-stat-grid,.review-grid,.review-cards,.weekly-pool-grid { grid-template-columns:1fr; display:grid; } .hero-title { font-size:28px; } .mode { justify-content:flex-start; } .market-big { font-size:34px; } }
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <div>
        <h1>海牛AI自動化交易系統</h1>
        <p class="subtitle">每日盤後整合台股日K、週選股、模擬交易與追蹤結果，分成持有管理、隔日候選、風控提醒與後驗復盤。</p>
      </div>
      <div class="mode">
        <span class="badge" id="today-badge">-</span><span class="badge">研究模式</span><span class="badge">模擬交易</span><span class="badge">人工確認</span>
      </div>
    </div>
  </header>
  <main>
    <nav class="page-nav">
      <button class="tab-btn active" data-page="overview">看大盤總覽</button>
      <button class="tab-btn" data-page="candidates">看隔日候選</button>
      <button class="tab-btn" data-page="weekly">本週名單</button>
      <button class="tab-btn" data-page="trading">看操作管理</button>
      <button class="tab-btn" data-page="tracking">看追蹤結果</button>
      <button class="tab-btn" data-page="review">今日複盤</button>
    </nav>

    <section class="hero page active" data-page="overview">
      <div class="hero-copy">
        <div>
          <h2 class="hero-title">大盤行情</h2>
          <div class="market-snapshot" aria-label="大盤上市上櫃行情圖片">
            <div class="market-picture">
              <div class="market-picture-top">
                <div>
                  <div class="subtitle"><span id="twse-label">加權指數</span><span class="market-date" id="twse-date"></span></div>
                  <div class="market-big" id="twse-index">-</div>
                  <div class="market-change" id="twse-change">-</div>
                </div>
                <div class="subtitle">成交 <strong id="twse-volume">-</strong> 億</div>
              </div>
              <div class="market-stat-grid">
                <div class="market-stat"><span>開盤</span><strong id="twse-open">-</strong></div>
                <div class="market-stat"><span>最高</span><strong id="twse-high">-</strong></div>
                <div class="market-stat"><span>最低</span><strong id="twse-low">-</strong></div>
                <div class="market-stat"><span>昨收</span><strong id="twse-prev">-</strong></div>
              </div>
            </div>
            <div class="market-picture">
              <div class="market-picture-top">
                <div>
                  <div class="subtitle"><span id="otc-label">上櫃指數</span><span class="market-date" id="otc-date"></span></div>
                  <div class="market-big" id="otc-index">-</div>
                  <div class="market-change" id="otc-change">-</div>
                </div>
                <div class="subtitle">成交 <strong id="otc-volume">-</strong> 億</div>
              </div>
              <div class="market-stat-grid">
                <div class="market-stat"><span>開盤</span><strong id="otc-open">-</strong></div>
                <div class="market-stat"><span>最高</span><strong id="otc-high">-</strong></div>
                <div class="market-stat"><span>最低</span><strong id="otc-low">-</strong></div>
                <div class="market-stat"><span>昨收</span><strong id="otc-prev">-</strong></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <aside class="preview">
        <h3>收盤後推估摘要</h3>
        <p class="subtitle" id="market-note">-</p>
        <div class="preview-grid" id="preview-grid"></div>
      </aside>
    </section>

    <section id="metrics" class="page active" data-page="overview"><h2>核心數據</h2><div class="grid metrics" id="metric-grid"></div></section>
    <section id="agent-flow" class="page active" data-page="overview"><h2>系統流程</h2><div class="flow" id="flow-grid"></div></section>

    <section id="candidates" class="page" data-page="candidates">
      <h2>下個交易日候選股總表</h2>
      <p class="subtitle" id="candidate-date-note">-</p>
      <div class="toolbar">
        <input id="search" placeholder="搜尋代號或名稱">
        <div><select id="route-filter"><option value="all">全部路由</option><option value="long_hold">長期波段</option><option value="intraday">盤中切入觀察</option><option value="day_trade">當沖候選</option><option value="watch">觀察</option><option value="reject">排除</option></select>
        <select id="decision-filter"><option value="all">全部決策</option><option value="enter">可進場</option><option value="wait">等待</option><option value="reject">排除</option><option value="reduce">減碼</option><option value="exit">出場</option></select></div>
      </div>
      <div class="table-wrap"><table><thead><tr><th>股票</th><th>最新價</th><th>候選層級</th><th>策略路由</th><th>分數</th><th>最後決策</th><th>波段判斷</th><th>盤中切入判斷</th><th>風控</th><th>理由摘要</th></tr></thead><tbody id="candidate-body"></tbody></table></div>
    </section>

    <section id="weekly-pools" class="page" data-page="weekly">
      <h2>本週名單</h2>
      <p class="subtitle">沿用週選股池分組，保留入選名單、操作組、觀察組與淘汰清單四塊。</p>
      <div class="weekly-pool-grid" id="weekly-pool-grid"></div>
    </section>

    <section id="detail" class="page" data-page="candidates"><h2>單一標的詳情</h2><div class="grid detail-grid" id="detail-grid"></div></section>
    <section id="next-plan" class="page" data-page="trading">
      <h2>過去五個交易日操作概述</h2>
      <p class="subtitle">只統整交易日實際留下的模擬操作紀錄；無成交也會明確標示，避免把預測檔誤當交易紀錄。</p>
      <div class="grid history-grid" id="operation-history-grid"></div>
      <h2 id="next-target-title">下個交易日操作預測</h2>
      <p class="subtitle" id="next-plan-note">-</p>
      <div class="table-wrap"><table><thead><tr><th>優先順序</th><th>股票</th><th>類型</th><th>核心判斷</th><th>觸發條件</th><th>預計動作</th><th>防守</th></tr></thead><tbody id="next-action-priority-body"></tbody></table></div>
      <div class="grid account-grid" id="account-grid"></div>
      <div class="table-wrap"><table><thead><tr><th>股票</th><th>股數</th><th>成本</th><th>現價</th><th>市值</th><th>未實現</th><th>報酬率</th><th>狀態</th></tr></thead><tbody id="holding-body"></tbody></table></div>
      <div id="plan-blocks"></div>
      <h2>交易紀錄</h2>
      <p class="subtitle">來源：<span id="paper-trade-source">-</span>。這裡只列紙上交易帳本，不拿策略預測檔混充。</p>
      <div class="table-wrap"><table><thead><tr><th>編號</th><th>日期</th><th>時間</th><th>股票</th><th>操作</th><th>價格</th><th>股數</th><th>金額</th><th>事後現金</th><th>事後持股</th><th>已實現</th><th>理由</th></tr></thead><tbody id="trade-record-body"></tbody></table></div>
    </section>
    <section id="long-hold" class="page" data-page="trading"><h2>長期波段持有</h2><div class="table-wrap"><table><thead><tr><th>股票</th><th>判斷</th><th>持倉階段</th><th>日K 3MA</th><th>日K 8MA</th><th>月K 3MA</th><th>風險提醒</th><th>理由</th></tr></thead><tbody id="long-hold-body"></tbody></table></div></section>
    <section id="intraday" class="page" data-page="trading"><h2>盤中切入觀察</h2><p class="subtitle">這裡只判斷盤中是否出現切入訊號；不是當沖，買進後仍依不能當沖與3MA/8MA規則管理。</p><div class="table-wrap"><table><thead><tr><th>股票</th><th>盤中判斷</th><th>切入條件</th><th>60K MACD</th><th>5K 開盤結構</th><th>量能</th><th>風險提醒</th></tr></thead><tbody id="intraday-body"></tbody></table></div></section>
    <section id="risk" class="page" data-page="tracking"><h2>決策風控裁判</h2><div class="grid split" id="risk-grid"></div></section>
    <section id="performance" class="page" data-page="tracking"><h2>後驗追蹤</h2><div class="grid metrics" id="performance-metrics"></div><div class="table-wrap"><table><thead><tr><th>掃描日期</th><th>股票</th><th>當時層級</th><th>策略路由</th><th>最後決策</th><th>當時價格</th><th>1日</th><th>3日</th><th>5日</th><th>波段結果</th><th>盤中切入結果</th><th>支持判斷</th></tr></thead><tbody id="performance-body"></tbody></table></div></section>
    <section id="daily-review" class="page" data-page="review">
      <h2>今日複盤</h2>
      <p class="subtitle">每日模擬交易後檢查 Agent 是否依照 SOP 執行、風控是否有擋單、長期波段與盤中切入觀察是否分流正確，以及明天要觀察什麼。</p>
      <h2>今日市場環境總結</h2>
      <div class="grid review-grid" id="review-market"></div>
      <h2>今日候選股摘要</h2>
      <div class="grid metrics" id="review-summary"></div>
      <h2>交易日操作事件</h2>
      <p class="subtitle">這裡不是事後成交清單，而是交易日每筆 Agent 判斷事件：成交、減碼、出場、等待、只觀察、被風控擋下都要留下原因。</p>
      <div class="table-wrap"><table><thead><tr><th>時間</th><th>股票代號</th><th>股票名稱</th><th>策略類型</th><th>是否操作</th><th>Agent 決策</th><th>風控結果</th><th>今日動作</th><th>說明</th></tr></thead><tbody id="review-operation-body"></tbody></table></div>
      <h2>今日操作詳細資料</h2>
      <div class="grid detail-grid" id="review-operation-detail"></div>
      <h2>風控裁判複盤</h2>
      <div class="grid review-grid" id="review-risk"></div>
      <h2>風控明細查詢</h2>
      <div class="review-toolbar"><label for="risk-event-select">選擇股票</label><select id="risk-event-select"></select></div>
      <div class="grid detail-grid" id="review-risk-detail"></div>
      <h2>長期波段持有複盤</h2>
      <div class="table-wrap"><table><thead><tr><th>股票代號</th><th>股票名稱</th><th>原本狀態</th><th>今日狀態</th><th>波段決策</th><th>原因</th><th>風險備註</th></tr></thead><tbody id="review-long-hold"></tbody></table></div>
      <h2>盤中切入複盤</h2>
      <div class="table-wrap"><table><thead><tr><th>股票代號</th><th>股票名稱</th><th>盤中型態</th><th>盤中決策</th><th>進場觸發</th><th>模擬結果</th><th>原因</th></tr></thead><tbody id="review-intraday"></tbody></table></div>
      <h2>今日錯誤與改進事項</h2>
      <div class="review-cards" id="review-improvements"></div>
      <h2>明日觀察清單</h2>
      <div class="table-wrap"><table><thead><tr><th>股票代號</th><th>股票名稱</th><th>分類</th><th>明日觀察重點</th><th>觸發條件</th></tr></thead><tbody id="review-watchlist"></tbody></table></div>
      <h2>下個交易日詳細模擬操作</h2>
      <div class="table-wrap"><table><thead><tr><th>股票代號</th><th>股票名稱</th><th>策略類型</th><th>情境</th><th>觸發條件</th><th>預估資金</th><th>模擬操作</th><th>風控規則</th></tr></thead><tbody id="review-next-operation"></tbody></table></div>
    </section>
  </main>
  <script>
    const dashboardData = __DASHBOARD_DATA__;
    const candidates = dashboardData.candidates || [];
    const nextPlan = dashboardData.next_trading_plan || {};
    const state = { query: "", route: "all", decision: "all", selected: null, selectedOperation: null, selectedRiskEvent: null };
    const byId = (id) => document.getElementById(id);
    const fmt = (value, digits = 2) => value === "" || value === null || value === undefined || Number.isNaN(Number(value)) ? "-" : Number(value).toFixed(digits);
    const pct = (value) => value === null || value === undefined || value === "" ? "-" : `${Number(value).toFixed(2)}%`;
    const shortDate = (value) => {
      if (!value) return "-";
      const parts = String(value).split("-");
      return parts.length === 3 ? `${Number(parts[1])}/${Number(parts[2])}` : value;
    };
    const addDays = (date, days) => {
      const next = new Date(date);
      next.setDate(next.getDate() + days);
      return next;
    };
    const isoDate = (date) => {
      const year = date.getFullYear();
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    };
    const previousTradingDates = (basis, count) => {
      const result = [];
      let cursor = new Date(`${basis || new Date().toISOString().slice(0,10)}T00:00:00`);
      while (result.length < count) {
        const day = cursor.getDay();
        if (day !== 0 && day !== 6) result.unshift(isoDate(cursor));
        cursor = addDays(cursor, -1);
      }
      return result;
    };
    const labelMap = {
      primary:"優先", secondary:"次要", reject:"排除", long_hold:"長期波段", intraday:"盤中切入觀察", day_trade:"當沖候選", watch:"觀察",
      enter:"可進場", wait:"等待", reduce:"減碼", exit:"出場", hold:"續抱", build:"建倉", add:"加碼",
      wait_pullback:"等回測", avoid:"避開", approved:"通過", blocked:"擋下", none:"無部位", full_position:"已有持倉",
      no_trade:"未操作", watch_only:"只觀察", not_triggered:"未觸發", risk_blocked:"風控擋下",
      insufficient_data:"資料不足", completed:"已完成", normal:"正常", cautious:"保守", risk_off:"停止攻擊",
      "market / ohlcv / chip":"行情 / K線 / 籌碼", "normal / cautious / risk_off":"正常 / 保守 / 停止攻擊",
      "primary / secondary / reject":"優先 / 次要 / 排除", "雙策略分流":"雙策略分流",
      "build / add / hold / reduce / exit":"建倉 / 加碼 / 續抱 / 減碼 / 出場",
      "enter_now / wait_pullback / wait / avoid":"立即進場 / 等回測 / 等待 / 避開",
      "enter / wait / reject / reduce / exit":"可進場 / 等待 / 排除 / 減碼 / 出場",
      aggressive:"積極", primary:"優先", normal:"正常", cautious:"保守", risk_off:"停止攻擊",
      "候選、理由、風控提醒":"候選、理由、風控提醒", "completed / pending":"已完成 / 待追蹤"
    };
    const label = (value) => labelMap[value] || value || "-";
    const tag = (value) => `<span class="tag ${String(value).replaceAll("_","-")}">${label(value)}</span>`;
    const levelOf = (x) => Number(x.score) >= 85 ? "primary" : Number(x.score) >= 55 ? "secondary" : "reject";
    const isHeld = (symbol) => ((nextPlan.account || {}).positions || []).some((p) => String(p.symbol) === String(symbol));
    const routeOf = (x) => {
      if (x.decision === "reject") return "reject";
      if (isHeld(x.symbol) || x.group_assignment === "操作組") return "long_hold";
      if (Object.values(x.triggers || {}).some(Boolean)) return "intraday";
      if (levelOf(x) === "secondary") return "watch";
      return "reject";
    };
    const finalOf = (x) => x.decision === "reject" ? "reject" : (isHeld(x.symbol) ? "wait" : "wait");
    const longDecisionOf = (x) => routeOf(x) === "long_hold" ? (isHeld(x.symbol) ? "hold" : "wait") : "wait";
    const intraDecisionOf = (x) => routeOf(x) === "intraday" ? "wait_pullback" : (routeOf(x) === "reject" ? "avoid" : "wait");
    const riskOf = (x) => finalOf(x) === "reject" ? "blocked" : "approved";
    const enriched = candidates.map((x) => ({...x, candidate_level:levelOf(x), route:routeOf(x), final_decision:finalOf(x), long_swing_decision:longDecisionOf(x), intraday_decision:intraDecisionOf(x), risk_status:riskOf(x)}));
    state.selected = enriched[0] || null;
    const moduleFlow = [
      ["資料讀取","讀取模組","讀取加權指數、日週月K、5K/15K/60K、籌碼與法人資料","market / ohlcv / chip"],
      ["加權指數判斷","大盤模式","判斷今天適合正常操作、保守觀察或停止攻擊","normal / cautious / risk_off"],
      ["股票初篩","候選池建立","排除弱勢、無量與空頭標的","primary / secondary / reject"],
      ["策略路由","多策略分流","判斷適合長期波段、盤中切入、當沖候選、只觀察或排除","多策略分流"],
      ["長期波段判斷","持有與加碼","建倉、加碼、續抱、減碼、出場","build / add / hold / reduce / exit"],
      ["盤中切入觀察","盤中節奏","盤中切入點與追價風險判斷；不是當沖","enter_now / wait_pullback / wait / avoid"],
      ["當沖候選判斷","當日進出","只有股票可當沖且策略允許當沖時才啟用；目前 paper trade 預設不執行","enter_now / wait / avoid"],
      ["決策風控裁判","最後審核","統一審核所有結果，避免追價、重複訊號與過度持倉","enter / wait / reject / reduce / exit"],
      ["輸出報告","報表與網頁","產出 JSON、CSV、Markdown 與 Dashboard","候選、理由、風控提醒"],
      ["後驗追蹤","復盤驗證","追蹤 1日 / 3日 / 5日結果，檢查原判斷是否有效","completed / pending"]
    ];
    const paperRows = (dashboardData.paper_trading && dashboardData.paper_trading.rows) || [];
    const operationEventRows = (dashboardData.operation_events && dashboardData.operation_events.rows) || [];
    const postmarketReview = dashboardData.postmarket_review || {findings:[]};
    const todayRows = paperRows.filter(x => String(x.date) === String(dashboardData.latest_completed_day));
    const todayOperationEventRows = operationEventRows.filter(x => String(x.date) === String(dashboardData.latest_completed_day));
    const accountPositions = ((nextPlan.account || {}).positions || []);
    const positionBySymbol = Object.fromEntries(accountPositions.map(p => [String(p.symbol), p]));
    const todaySymbols = Array.from(new Set(todayRows.map(x => String(x.symbol))));
    const tradedSymbols = new Set(todayRows.map(x => String(x.symbol)));
    const tradeOperationEvents = todayRows.map((x, index) => {
      const side = String(x.side || "").toLowerCase();
      const isRisk = String(x.reason || "").includes("自動風控");
      const remaining = Number(x.position_after || 0);
      const decision = side === "buy" ? "enter" : (remaining <= 0 ? "exit" : "reduce");
      return {
        event_id: `trade-${x.trade_id || index}`,
        time: x.time || "-",
        symbol: String(x.symbol || ""),
        name: x.name || String(x.symbol || ""),
        strategy_type: "long_hold",
        operated: side === "buy" ? "enter" : decision,
        agent_decision: decision,
        risk_result: isRisk || side === "sell" ? "approved" : "approved",
        action: `${side === "buy" ? "買進" : "賣出"} ${x.shares || "-"} 股 @ ${x.price || "-"}`,
        reason: x.reason || "-",
        sop_check: x.sop_check || "-",
        risk_review: isRisk ? "風控執行器依既有持股、日 K 3MA / 8MA 與 3% 停損規則自動補紀錄。" : "依紙上交易紀錄列入今日操作。",
        improvement: isRisk ? "後續要接即時資料與券商 API 時，這條規則要搬到盤中風控，不能只等收盤報表。" : "保留觸發價、K 線型態與成交量，方便隔日檢討。"
      };
    });
    const intradayOperationEvents = todayOperationEventRows.map((x, index) => ({
      event_id: x.event_id || `intraday-${index}`,
      time: x.time || "-",
      symbol: String(x.symbol || ""),
      name: x.name || String(x.symbol || ""),
      strategy_type: x.strategy_type || "watch",
      operated: x.simulated_action && x.simulated_action !== "none" ? x.simulated_action : (x.event_type || "not_triggered"),
      agent_decision: x.agent_decision || "wait",
      risk_result: x.risk_result || "blocked",
      action: x.action || x.simulated_action || "未操作",
      reason: x.reason || "-",
      sop_check: x.sop_check || "-",
      risk_review: x.risk_review || "盤中事件由 operation_events 記錄。",
      improvement: x.improvement || "若為 data_missing，優先修即時資料源；若為 blocked，檢查擋單是否合理。"
    }));
    const candidateOperationEvents = enriched
      .filter((x) => !tradedSymbols.has(String(x.symbol)))
      .map((x, index) => {
        const blocked = x.risk_status === "blocked" || x.final_decision === "reject" || x.decision === "reject";
        const held = isHeld(x.symbol);
        const action = blocked ? "不進場" : (held ? "持有檢查，不加碼" : "等待觸發，不下單");
        const operated = blocked ? "risk_blocked" : (held ? "no_trade" : "not_triggered");
        const agentDecision = blocked ? "reject" : (held ? "hold" : "wait");
        const riskResult = blocked ? "blocked" : "approved";
        return {
          event_id: `decision-${x.symbol}-${index}`,
          time: blocked ? "風控檢查" : "盤中觀察",
          symbol: String(x.symbol || ""),
          name: x.name || String(x.symbol || ""),
          strategy_type: x.route || "watch",
          operated,
          agent_decision: agentDecision,
          risk_result: riskResult,
          action,
          reason: blocked ? (x.risk_note || x.reason || "未通過風控條件。") : (x.entry_trigger || x.reason || "未出現符合 SOP 的切入點。"),
          sop_check: blocked ? `擋下原因：${x.risk_note || x.reason || "風控未通過"}` : `等待條件：${x.entry_trigger || "5K 切入點、量能與 60K MACD 確認"}`,
          risk_review: blocked ? "此筆列為交易日被擋下事件，不是漏記；後續若條件改善才重新評估。" : "此筆有被檢查，但沒有觸發下單條件，所以記為等待或只觀察。",
          improvement: blocked ? "把擋單原因保留到隔日復盤，確認是規則正確擋下，還是資料不足造成誤擋。" : "下次要補更精準的盤中價格、5K 量能與觸發時間，避免只寫籠統等待。"
        };
      });
    const reviewOperations = intradayOperationEvents.length ? intradayOperationEvents : [...tradeOperationEvents, ...candidateOperationEvents];
    if (!reviewOperations.length) {
      reviewOperations.push({
        event_id:"empty-day", time:"收盤後", symbol:"-", name:"今日無操作事件", strategy_type:"watch", operated:"no_trade",
        agent_decision:"wait", risk_result:"approved", action:"未操作",
        reason:"今日沒有成交、候選、持股或擋單事件可記錄。",
        sop_check:"需要確認資料更新是否完整，避免不是沒有操作，而是沒有產生事件。",
        risk_review:"若未來要接自動交易，這種空事件也要視為異常檢查點。",
        improvement:"補上交易日事件來源，讓每日一定有檢查紀錄。"
      });
    }
    const riskOperationRows = reviewOperations.filter(x => x.risk_result === "approved" && (x.agent_decision === "reduce" || x.agent_decision === "exit"));
    const blockedOperationRows = reviewOperations.filter(x => x.risk_result === "blocked");
    const executedOperationRows = reviewOperations.filter(x => ["enter","reduce","exit"].includes(x.agent_decision));
    const riskDetailRows = blockedOperationRows.length ? blockedOperationRows : reviewOperations.filter(x => x.agent_decision === "wait" || x.operated === "not_triggered");
    const reviewLongHold = todaySymbols.length ? todaySymbols.map((symbol) => {
      const related = todayRows.filter(x => String(x.symbol) === symbol);
      const last = related[related.length - 1] || {};
      const remaining = Number(last.position_after || 0);
      return {
        symbol,
        name: last.name || symbol,
        previous_status: "依交易紀錄回推原持股",
        today_status: remaining > 0 ? `剩餘 ${remaining} 股` : "已出清",
        long_swing_decision: remaining > 0 ? "reduce" : "exit",
        reason: related.map(x => x.reason).join("；"),
        risk_note: related.map(x => x.sop_check).join("；")
      };
    }) : accountPositions.map((p) => ({
      symbol:String(p.symbol), name:p.name, previous_status:"既有持股", today_status:`持有 ${p.shares} 股`,
      long_swing_decision:"hold", reason:"今日沒有新增交易紀錄，依帳戶狀態續抱。", risk_note:"隔日仍需檢查 3MA / 8MA / 3% 停損。"
    }));
    const dailyReviewData = {
      market: {
        index_status: "加權指數站回短均，盤面允許正常觀察但不追高",
        operation_mode: "normal",
        allow_new_position: "允許，限符合 5K 觸發與量能確認",
        allow_chase: "不允許",
        reason: "上市與上櫃同步轉強，但候選股仍需等待回測或突破確認，避免用隔日計畫直接當成進場指令。"
      },
      summary: {
        scanned: enriched.length,
        passed: enriched.filter(x=>x.candidate_level!=="reject").length,
        primary: enriched.filter(x=>x.candidate_level==="primary").length,
        secondary: enriched.filter(x=>x.candidate_level==="secondary").length,
        reject: enriched.filter(x=>x.candidate_level==="reject").length,
        long_hold: enriched.filter(x=>x.route==="long_hold").length,
        intraday: enriched.filter(x=>x.route==="intraday").length,
        watch: enriched.filter(x=>x.route==="watch").length
      },
      operations: reviewOperations,
      risk_review: {
        approved_count: executedOperationRows.length,
        blocked_count: blockedOperationRows.length,
        main_block_reason: riskOperationRows.length ? "持股跌破 3MA / 觸發 3% 停損" : "追價風險與 5K 觸發不足",
        blocked_reason: blockedOperationRows.length ? `${blockedOperationRows.length} 檔未通過，詳見下方明細` : (riskOperationRows.length ? "今日有持股風控賣出，詳見交易日操作事件" : "無風控擋單"),
        risk_note: riskOperationRows.length ? "今日風控有實際執行紙上賣出，後續需檢查是否應提早到盤中觸發。" : "今日沒有風控賣出，候選股仍需等明確觸發。"
      },
      risk_events: riskDetailRows,
      long_hold: reviewLongHold,
      intraday: [
        {symbol:"6770", name:"力積電", pattern:"放量後高檔整理", intraday_decision:"wait_pullback", entry_trigger:"5K 回測不破且量縮，轉強量增", simulated_result:"未成交，保留觀察", reason:"符合觀察條件，但沒有直接追價。"},
        {symbol:"2375", name:"凱美", pattern:"突破前整理", intraday_decision:"wait", entry_trigger:"突破區間高點且 60K MACD 確認", simulated_result:"等待", reason:"型態尚未完成，先排進明日盯盤。"},
        {symbol:"6141", name:"柏承", pattern:"回測交會支撐後拉回", intraday_decision:"enter_now", entry_trigger:"09:24 回測週/月 3MA 與日 8MA 交會區後拉回", simulated_result:"買進 50 股", reason:"符合小部位承接條件，但仍需補齊當下 5K 量能與停損價。"}
      ],
      improvements: [
        ...((postmarketReview.findings || []).slice(0,3).map(x => ({title:`盤後漏判：${x.symbol} ${x.name}`, text:`${x.missed_action}。${x.reason} ${x.next_day_feedback}`}))),
        {title:"今日發現問題", text:(postmarketReview.findings || []).length ? "盤後回看發現盤中風控事件沒有即時寫入交易帳本，已改為只記漏判檢討，不再假裝盤中成交。" : "今日沒有盤後漏判 findings；仍需確認盤中事件檔是否正常產生。"},
        {title:"明日調整方向", text:"盤中監控必須即時寫 operation_events；讀不到即時資料也要記 data_missing / blocked，不能安靜跳過。"},
        {title:"需要補資料的地方", text:"需要穩定即時報價與 5K/60K 資料源；沒有資料時只允許觀察或擋單，不允許自動買賣。"}
      ],
      watchlist: [
        {symbol:"3481", name:"群創", category:"long_hold", focus:"剩餘 35 股持有管理", trigger:"守住日 K 8MA；跌破或虧損達 3% 剩餘部位全出"},
        {symbol:"6770", name:"力積電", category:"intraday", focus:"回測後是否轉強", trigger:"5K 回測不破，60K MACD 確認"},
        {symbol:"6141", name:"柏承", category:"watch", focus:"今日已依風控出清，隔日只觀察是否重新站回", trigger:"重新站回日 K 3MA / 8MA 且 5K 量價轉強才重新評估"}
      ],
      next_operations: [
        {symbol:"3481", name:"群創", strategy_type:"long_hold", scenario:"情境 1：剩餘部位防守", trigger:"不跌破日 K 8MA，盤中沒有爆量長黑", capital:"不新增資金，維持剩餘 35 股", action:"續抱觀察；跌破 8MA 或成本風險擴大則全出", risk:"已完成 3MA 降碼，不能再用加碼攤平處理"},
        {symbol:"6770", name:"力積電", strategy_type:"intraday", scenario:"情境 2：回測後轉強", trigger:"5K 回測不破，轉強時量增，60K MACD 確認", capital:"第一筆約 1,000 - 1,500；最多不超過剩餘資金 30%", action:"模擬試單；未觸發不買", risk:"開高爆量黑 K 不追，跌破回測低點取消"},
        {symbol:"6141", name:"柏承", strategy_type:"watch", scenario:"情境 3：出清後重新觀察", trigger:"重新站回日 K 3MA / 8MA，且 5K 切入點與 60K MACD 同步確認", capital:"已出清，隔日不預設投入；若重新觸發再用剩餘資金試算第一筆", action:"等待，不追價；未重新站回不買", risk:"今日已觸發 3% 停損，不允許用攤平方式立刻買回"}
      ]
    };
    state.selectedOperation = dailyReviewData.operations[0] || null;
    function renderHeader() {
      const basisDay = dashboardData.latest_completed_day || dashboardData.generated_at || "-";
      const appliesTo = (nextPlan && nextPlan.applies_to) || "-";
      byId("today-badge").textContent = `基準日 ${basisDay} -> 適用 ${appliesTo}`;
      byId("market-note").textContent = dashboardData.market_note || "";
      byId("candidate-date-note").textContent = `依 ${basisDay} 收盤資料推估 ${appliesTo} 的候選股與操作劇本；不是盤中即時買入清單。`;
      const primary = enriched.filter(x => x.candidate_level === "primary").length;
      const longHold = enriched.filter(x => x.route === "long_hold").length;
      const intraday = enriched.filter(x => x.route === "intraday").length;
      const dayTrade = enriched.filter(x => x.route === "day_trade").length;
      const blocked = enriched.filter(x => x.risk_status === "blocked").length;
      const preview = [["大盤模式",label("normal")],["掃描股票數",enriched.length],["優先候選",primary],["長期波段",longHold],["盤中切入",intraday],["當沖候選",dayTrade],["風控擋下",blocked],["後驗追蹤",enriched.length]];
      byId("preview-grid").innerHTML = preview.map(([a,b]) => `<div class="mini"><span>${a}</span><strong>${b}</strong></div>`).join("");
      const metrics = [["掃描股票數",enriched.length,"收盤後納入研究清單"],["通過初篩",enriched.filter(x=>x.candidate_level!=="reject").length,"優先 / 次要"],["優先 / 次要",`${primary}/${enriched.filter(x=>x.candidate_level==="secondary").length}`,"候選分層"],["長期波段",longHold,"波段持有路由"],["盤中切入",intraday,"盤中切入觀察，不是當沖"],["當沖候選",dayTrade,"需可當沖且策略允許，目前不執行"],["風控擋下",blocked,"風控擋下或排除"]];
      byId("metric-grid").innerHTML = metrics.map(([a,b,c]) => `<div class="metric"><span>${a}</span><strong>${b}</strong><p class="subtitle">${c}</p></div>`).join("");
    }
    function renderMarketIndices() {
      const indices = dashboardData.market_indices || {};
      const formatNumber = (value) => value === "" || value === null || value === undefined || Number.isNaN(Number(value)) ? "-" : Number(value).toLocaleString("zh-TW", {minimumFractionDigits:2, maximumFractionDigits:2});
      const formatVolume = (value) => value === "" || value === null || value === undefined || Number.isNaN(Number(value)) ? "-" : Number(value).toLocaleString("zh-TW", {maximumFractionDigits:1});
      const apply = (prefix, item) => {
        if (!item) return;
        byId(`${prefix}-label`).textContent = item.label || (prefix === "twse" ? "加權指數" : "上櫃指數");
        byId(`${prefix}-date`).textContent = item.date ? `· ${item.date}` : "";
        byId(`${prefix}-index`).textContent = formatNumber(item.value);
        const change = Number(item.change || 0);
        const pctValue = Number(item.pct || 0);
        const direction = change >= 0 ? "▲" : "▼";
        const changeNode = byId(`${prefix}-change`);
        changeNode.textContent = `${direction} ${formatNumber(Math.abs(change))} (${Math.abs(pctValue).toFixed(2)}%)`;
        changeNode.className = `market-change ${change >= 0 ? "pos" : "neg"}`;
        byId(`${prefix}-index`).className = `market-big ${change >= 0 ? "pos" : "neg"}`;
        byId(`${prefix}-volume`).textContent = formatVolume(item.volume);
        byId(`${prefix}-open`).textContent = formatNumber(item.open);
        byId(`${prefix}-high`).textContent = formatNumber(item.high);
        byId(`${prefix}-low`).textContent = formatNumber(item.low);
        byId(`${prefix}-prev`).textContent = formatNumber(item.prev);
      };
      apply("twse", indices.twse);
      apply("otc", indices.otc);
    }
    function renderFlow() {
      byId("flow-grid").innerHTML = moduleFlow.map((m, i) => `<div class="flow-card ${i===3?'route':''} ${i===6?'risk':''}"><small>${m[1]}</small><h3>${m[0]}</h3><p>${m[2]}</p><p>${tag(m[3])}</p></div>`).join("");
    }
    function filteredRows() {
      return enriched.filter(x => {
        const q = state.query.trim().toLowerCase();
        return (!q || `${x.symbol} ${x.name}`.toLowerCase().includes(q)) && (state.route==="all" || x.route===state.route) && (state.decision==="all" || x.final_decision===state.decision);
      }).sort((a,b)=>Number(b.score)-Number(a.score));
    }
    function renderCandidates() {
      byId("candidate-body").innerHTML = filteredRows().map(x => `<tr data-symbol="${x.symbol}"><td><strong>${x.symbol}</strong><br><span class="subtitle">${x.name}</span></td><td>${fmt(x.latest_price)}<br><span class="${Number(x.change_pct)>=0?'pos':'neg'}">${pct(x.change_pct)}</span></td><td>${tag(x.candidate_level)}</td><td>${tag(x.route)}</td><td><strong>${fmt(x.score)}</strong></td><td>${tag(x.final_decision)}</td><td>${tag(x.long_swing_decision)}</td><td>${tag(x.intraday_decision)}</td><td>${tag(x.risk_status)}</td><td>${x.reason}</td></tr>`).join("");
      [...document.querySelectorAll("#candidate-body tr")].forEach(row => row.addEventListener("click", () => { state.selected = enriched.find(x => x.symbol === row.dataset.symbol); renderDetail(); }));
    }
    function renderWeeklyPools() {
      const groups = [
        ["入選名單", "selected", enriched.filter(x => x.group_assignment === "入選名單")],
        ["操作組", "operation", enriched.filter(x => x.group_assignment === "操作組")],
        ["觀察組", "watch", enriched.filter(x => x.group_assignment === "觀察組")],
        ["淘汰清單", "eliminate", enriched.filter(x => x.group_assignment === "淘汰" || x.candidate_level === "reject")]
      ];
      byId("weekly-pool-grid").innerHTML = groups.map(([title, cls, rows]) => `
        <div class="pool-card ${cls}">
          <h3>${title}</h3>
          ${rows.length ? rows.map(x => `<div class="pool-item"><strong>${x.symbol} ${x.name}</strong><br><span class="subtitle">Score ${fmt(x.score)} / ${label(x.route)} / ${x.entry_trigger}</span></div>`).join("") : "<p class='subtitle'>無</p>"}
        </div>`).join("");
    }
    function renderDetail() {
      const x = state.selected; if (!x) return;
      const ma = x.ma || {};
      byId("detail-grid").innerHTML = `
        <div class="card"><h3>${x.symbol} ${x.name}</h3><p>${tag(x.candidate_level)} ${tag(x.route)}</p><p class="subtitle">最新價 ${fmt(x.latest_price)} / 分數 ${fmt(x.score)}</p><p>${x.reason}</p></div>
        <div class="card"><h3>多週期結構</h3><div class="kv-grid">${Object.entries(ma).map(([k,v])=>`<div class="kv"><span>${k}</span><strong>${fmt(v)}</strong></div>`).join("")}</div><p class="subtitle">${x.daily_ma_alignment}<br>${x.weekly_ma_alignment}<br>${x.monthly_ma_alignment}</p></div>
        <div class="card"><h3>系統判斷摘要</h3><p>大盤模式：${label("normal")}</p><p>股票初篩：${label(x.candidate_level)}</p><p>策略路由：${label(x.route)}</p><p>風控裁判：${label(x.risk_status)}</p></div>
        <div class="card"><h3>操作計畫</h3><p>${x.route==="long_hold" ? "建倉 / 加碼 / 續抱 / 減碼 / 出場以日K 3MA、8MA與月K 3MA管理。" : "觀察開盤八法、5K 回撤 3MA、連三黑回測與 60K MACD。"}</p><p class="subtitle">${x.risk_note}</p></div>`;
    }
    function renderNextPlan() {
      const account = nextPlan.account || {};
      byId("next-target-title").textContent = `下個交易日 ${shortDate(nextPlan.applies_to)} 操作目標`;
      byId("next-plan-note").textContent = `更新時間：${nextPlan.updated_at || "-"} / 適用交易日：${nextPlan.applies_to || "-"} / ${nextPlan.cash_allocation_note || ""}`;
      const historyDates = previousTradingDates(nextPlan.basis_day || dashboardData.latest_completed_day || dashboardData.generated_at, 5);
      const tradesByDate = paperRows.reduce((acc, trade) => {
        const date = String(trade.date || "");
        if (!date) return acc;
        (acc[date] ||= []).push(trade);
        return acc;
      }, {});
      byId("operation-history-grid").innerHTML = historyDates.map((date) => {
        const trades = tradesByDate[date] || [];
        const isCurrent = date === String(dashboardData.latest_completed_day);
        const cls = trades.length ? (isCurrent ? "current" : "") : "missing";
        const buyCount = trades.filter(t => String(t.side).toLowerCase() === "buy").length;
        const sellCount = trades.filter(t => String(t.side).toLowerCase() === "sell").length;
        const symbols = [...new Set(trades.map(t => `${t.symbol} ${t.name}`))].join("、");
        const last = trades[trades.length - 1] || {};
        const body = trades.length
          ? `買進 ${buyCount} 筆 / 賣出 ${sellCount} 筆<br>${symbols}<br>收盤後現金 ${fmt(Number(last.cash_after || 0),0)}`
          : "無交易紀錄；視為未操作或未觸發。";
        const title = trades.length ? `操作概述 ${shortDate(date)}` : `無操作 ${shortDate(date)}`;
        return `<div class="history-card ${cls}"><span class="subtitle">${title}</span><strong>${date}</strong><p>${body}</p></div>`;
      }).join("");
      const items = [["原始資金", account.initial_capital],["持有市值", account.position_value],["剩餘資金", account.cash],["未實現", account.unrealized_pnl],["累積獲利", account.total_pnl],["資金使用率", account.capital_usage_pct]];
      byId("account-grid").innerHTML = items.map(([a,b],i)=>`<div class="metric"><span>${a}</span><strong>${i===5?pct(b):fmt(b,0)}</strong></div>`).join("");
      const positions = account.positions || [];
      byId("holding-body").innerHTML = positions.map(p => `<tr><td><strong>${p.symbol}</strong><br>${p.name}</td><td>${p.shares}</td><td>${fmt(p.cost_basis)}</td><td>${fmt(p.latest_price)}</td><td>${fmt(p.market_value,0)}</td><td class="${Number(p.unrealized_pnl)>=0?'pos':'neg'}">${fmt(p.unrealized_pnl,0)}</td><td class="${Number(p.unrealized_pct)>=0?'pos':'neg'}">${pct(p.unrealized_pct)}</td><td>${tag(p.status || "hold")}</td></tr>`).join("");
      const plans = [...(nextPlan.holding_plans || []), ...(nextPlan.symbol_plans || [])];
      const priorityRows = plans.flatMap((plan, planIndex) => {
        const scenarios = plan.scenarios || [];
        if (!scenarios.length) return [];
        const first = scenarios[0];
        const second = scenarios[1] || {};
        const last = scenarios[scenarios.length - 1] || {};
        const type = plan.shares !== undefined ? "持有管理" : "候選觀察";
        return [{
          order: planIndex + 1,
          symbol: plan.symbol,
          name: plan.name,
          type,
          thesis: plan.shares !== undefined ? `${plan.shares} 股，先處理開盤3MA防守` : (plan.entry_status || "等待盤中觸發"),
          trigger: `${first.title}：${first.condition}`,
          action: first.action,
          defense: last.action || second.action || "-"
        }];
      });
      byId("next-action-priority-body").innerHTML = priorityRows.length ? priorityRows.map(row => `<tr><td>${row.order}</td><td><strong>${row.symbol}</strong><br>${row.name}</td><td>${row.type}</td><td>${row.thesis}</td><td>${row.trigger}</td><td>${row.action}</td><td>${row.defense}</td></tr>`).join("") : '<tr><td colspan="7" class="subtitle">目前沒有下個交易日預測劇本。</td></tr>';
      byId("plan-blocks").innerHTML = plans.map(plan => {
        const type = plan.shares !== undefined ? `持有 ${plan.shares} 股 / 成本 ${fmt(plan.cost_basis)}` : `${plan.entry_status || "候選觀察"} / 預估 ${fmt(plan.rough_budget_low,0)} - ${fmt(plan.rough_budget_high,0)}`;
        return `<div class="card" style="margin-top:12px"><h3>${plan.symbol} ${plan.name}</h3><p class="subtitle">${type}</p><div class="grid scenario-grid">${(plan.scenarios||[]).map(s=>`<div class="scenario"><h3>${s.title}</h3><p class="subtitle">${s.condition}</p><p>${s.action}</p></div>`).join("")}</div></div>`;
      }).join("");
      renderTradeRecords();
    }
    function renderTradeRecords() {
      byId("paper-trade-source").textContent = (dashboardData.paper_trading && dashboardData.paper_trading.source_file) || "尚無模擬交易檔";
      byId("trade-record-body").innerHTML = paperRows.length ? paperRows.map(item => {
        const side = String(item.side || "").toLowerCase();
        const sideLabel = side === "buy" ? "買入" : side === "sell" ? "賣出" : item.side;
        return `<tr>
          <td>${item.trade_id || "-"}</td>
          <td>${item.date || "-"}</td>
          <td>${item.time || "-"}</td>
          <td><strong>${item.symbol || "-"}</strong><br>${item.name || ""}</td>
          <td>${tag(side === "buy" ? "enter" : side === "sell" ? "exit" : "wait")} ${sideLabel}</td>
          <td>${fmt(Number(item.price || 0))}</td>
          <td>${item.shares || "-"}</td>
          <td>${fmt(Number(item.gross_amount || 0),0)}</td>
          <td>${fmt(Number(item.cash_after || 0),0)}</td>
          <td>${item.position_after || "-"}</td>
          <td class="${Number(item.realized_pnl || 0) >= 0 ? "pos" : "neg"}">${fmt(Number(item.realized_pnl || 0),0)}</td>
          <td>${item.reason || "-"}</td>
        </tr>`;
      }).join("") : '<tr><td colspan="12" class="subtitle">尚無交易紀錄</td></tr>';
    }
    function renderLongHold() {
      byId("long-hold-body").innerHTML = enriched.filter(x=>x.route==="long_hold").map(x => `<tr><td><strong>${x.symbol}</strong><br>${x.name}</td><td>${tag(x.long_swing_decision)}</td><td>${tag(isHeld(x.symbol)?"full_position":"none")}</td><td>${x.daily_ma_alignment}</td><td>${(x.ma||{})["8MA"] ? fmt((x.ma||{})["8MA"]) : "-"}</td><td>${x.monthly_ma_alignment}</td><td>${x.risk_note}</td><td>${x.reason}</td></tr>`).join("");
    }
    function renderIntraday() {
      byId("intraday-body").innerHTML = enriched.filter(x=>x.route==="intraday" || x.route==="watch").map(x => `<tr><td><strong>${x.symbol}</strong><br>${x.name}</td><td>${tag(x.intraday_decision)}</td><td>${x.entry_trigger}</td><td>${x.triggers && x.triggers["60K MACD轉強"] ? "確認" : "等待"}</td><td>${x.triggers && x.triggers["開盤八法紅紅紅"] ? "紅K轉強" : "等待"}</td><td>${fmt(x.volume_ratio)}</td><td>${x.risk_note}</td></tr>`).join("");
    }
    function renderRisk() {
      const approved = enriched.filter(x=>x.risk_status==="approved");
      const blocked = enriched.filter(x=>x.risk_status==="blocked");
      byId("risk-grid").innerHTML = [["通過名單",approved],["擋下名單",blocked]].map(([title,rows]) => `<div class="card"><h3>${title}</h3>${rows.slice(0,10).map(x=>`<p><strong>${x.symbol} ${x.name}</strong> ${tag(x.risk_status)} <span class="subtitle">${x.risk_note}</span></p>`).join("") || "<p class='subtitle'>無</p>"}</div>`).join("");
    }
    function renderPerformance() {
      const completed = enriched.filter(x=>x.next_1d_return!==null && x.next_1d_return!==undefined).length;
      byId("performance-metrics").innerHTML = [["已完成筆數",completed],["待追蹤筆數",enriched.length-completed],["資料不足警示",enriched.length-completed]].map(([a,b])=>`<div class="metric"><span>${a}</span><strong>${b}</strong></div>`).join("");
      byId("performance-body").innerHTML = enriched.map(x => `<tr><td>${dashboardData.selection.selection_date}</td><td><strong>${x.symbol}</strong><br>${x.name}</td><td>${tag(x.candidate_level)}</td><td>${tag(x.route)}</td><td>${tag(x.final_decision)}</td><td>${fmt(x.latest_price)}</td><td>${pct(x.next_1d_return)}</td><td>${pct(x.next_3d_return)}</td><td>${pct(x.next_5d_return)}</td><td>${x.route==="long_hold" ? "待追蹤" : "-"}</td><td>${x.route==="intraday" ? "待追蹤" : "-"}</td><td>${x.next_1d_return===null || x.next_1d_return===undefined ? tag("insufficient_data") : tag("completed")}</td></tr>`).join("");
    }
    function renderReviewOperationDetail() {
      const x = state.selectedOperation;
      if (!x) return;
      byId("review-operation-detail").innerHTML = `
        <div class="card"><h3>${x.symbol} ${x.name}</h3><p>${tag(x.strategy_type)} ${tag(x.operated)} ${tag(x.agent_decision)}</p><p class="subtitle">${x.time} / 今日動作：${x.action}</p><p>${x.reason}</p></div>
        <div class="card"><h3>SOP 檢查</h3><p>${x.sop_check}</p></div>
        <div class="card"><h3>風控複盤</h3><p>${tag(x.risk_result)}</p><p class="subtitle">${x.risk_review}</p></div>
        <div class="card"><h3>改善空間</h3><p>${x.improvement}</p></div>`;
    }
    function renderDailyReview() {
      const m = dailyReviewData.market;
      byId("review-market").innerHTML = [
        ["加權指數狀態", m.index_status],
        ["operation_mode", tag(m.operation_mode)],
        ["是否允許新倉", m.allow_new_position],
        ["是否允許追價", m.allow_chase],
        ["大盤判斷理由", m.reason]
      ].map(([a,b]) => `<div class="metric"><span>${a}</span><strong>${b}</strong></div>`).join("");
      const s = dailyReviewData.summary;
      byId("review-summary").innerHTML = [
        ["掃描股票數", s.scanned],["通過初篩數", s.passed],["Primary 數量", s.primary],["Secondary 數量", s.secondary],
        ["Reject 數量", s.reject],["Long Hold 路由數", s.long_hold],["Intraday 路由數", s.intraday],["Watch 數量", s.watch]
      ].map(([a,b]) => `<div class="metric"><span>${a}</span><strong>${b}</strong></div>`).join("");
      byId("review-operation-body").innerHTML = dailyReviewData.operations.map(x => `<tr data-event-id="${x.event_id}" class="${state.selectedOperation && state.selectedOperation.event_id === x.event_id ? "selected-row" : ""}"><td>${x.time}</td><td><strong>${x.symbol}</strong></td><td>${x.name}</td><td>${tag(x.strategy_type)}</td><td>${tag(x.operated)}</td><td>${tag(x.agent_decision)}</td><td>${tag(x.risk_result)}</td><td>${x.action}</td><td>${x.reason}</td></tr>`).join("");
      [...document.querySelectorAll("#review-operation-body tr")].forEach(row => row.addEventListener("click", () => {
        state.selectedOperation = dailyReviewData.operations.find(x => x.event_id === row.dataset.eventId);
        renderDailyReview();
      }));
      renderReviewOperationDetail();
      const r = dailyReviewData.risk_review;
      byId("review-risk").innerHTML = [
        ["今日通過交易數", r.approved_count],
        ["今日擋下交易數", r.blocked_count],
        ["主要擋單原因", r.main_block_reason],
        ["blocked_reason", r.blocked_reason],
        ["risk_note", r.risk_note]
      ].map(([a,b]) => `<div class="metric"><span>${a}</span><strong>${b}</strong></div>`).join("");
      renderRiskDetailSelector();
      byId("review-long-hold").innerHTML = dailyReviewData.long_hold.map(x => `<tr><td><strong>${x.symbol}</strong></td><td>${x.name}</td><td>${x.previous_status}</td><td>${x.today_status}</td><td>${tag(x.long_swing_decision)}</td><td>${x.reason}</td><td>${x.risk_note}</td></tr>`).join("");
      byId("review-intraday").innerHTML = dailyReviewData.intraday.map(x => `<tr><td><strong>${x.symbol}</strong></td><td>${x.name}</td><td>${x.pattern}</td><td>${tag(x.intraday_decision)}</td><td>${x.entry_trigger}</td><td>${x.simulated_result}</td><td>${x.reason}</td></tr>`).join("");
      byId("review-improvements").innerHTML = dailyReviewData.improvements.map(x => `<div class="issue-card"><h3>${x.title}</h3><p>${x.text}</p></div>`).join("");
      byId("review-watchlist").innerHTML = dailyReviewData.watchlist.map(x => `<tr><td><strong>${x.symbol}</strong></td><td>${x.name}</td><td>${tag(x.category)}</td><td>${x.focus}</td><td>${x.trigger}</td></tr>`).join("");
      byId("review-next-operation").innerHTML = dailyReviewData.next_operations.map(x => `<tr><td><strong>${x.symbol}</strong></td><td>${x.name}</td><td>${tag(x.strategy_type)}</td><td>${x.scenario}</td><td>${x.trigger}</td><td>${x.capital}</td><td>${x.action}</td><td>${x.risk}</td></tr>`).join("");
    }
    function renderRiskDetailSelector() {
      const events = dailyReviewData.risk_events || [];
      const select = byId("risk-event-select");
      if (!events.length) {
        select.innerHTML = `<option value="">無明細</option>`;
        byId("review-risk-detail").innerHTML = `<div class="card"><h3>無明細</h3><p class="subtitle">今日沒有風控擋單或等待事件。</p></div>`;
        return;
      }
      if (!state.selectedRiskEvent || !events.some(x => x.event_id === state.selectedRiskEvent.event_id)) {
        state.selectedRiskEvent = events[0];
      }
      select.innerHTML = events.map(x => `<option value="${x.event_id}" ${state.selectedRiskEvent && state.selectedRiskEvent.event_id === x.event_id ? "selected" : ""}>${x.symbol} ${x.name} - ${label(x.risk_result)} / ${label(x.operated)}</option>`).join("");
      select.onchange = () => {
        state.selectedRiskEvent = events.find(x => x.event_id === select.value) || events[0];
        renderRiskDetailSelector();
      };
      const x = state.selectedRiskEvent || events[0];
      byId("review-risk-detail").innerHTML = [
        ["股票", `<strong>${x.symbol} ${x.name}</strong><br>${tag(x.strategy_type)} ${tag(x.risk_result)}`],
        ["判斷結果", `${tag(x.agent_decision)} ${tag(x.operated)}<br><span class="subtitle">${x.action}</span>`],
        ["原因", x.reason],
        ["SOP 檢查", x.sop_check],
        ["風控檢討", x.risk_review],
        ["改善方向", x.improvement]
      ].map(([a,b]) => `<div class="card"><h3>${a}</h3><p>${b}</p></div>`).join("");
    }
    function switchPage(page) {
      document.querySelectorAll(".page").forEach((el) => el.classList.toggle("active", el.dataset.page === page));
      document.querySelectorAll(".tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.page === page));
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
    function renderAll(){ renderHeader(); renderMarketIndices(); renderFlow(); renderCandidates(); renderWeeklyPools(); renderDetail(); renderNextPlan(); renderLongHold(); renderIntraday(); renderRisk(); renderPerformance(); renderDailyReview(); }
    byId("search").addEventListener("input", e => { state.query = e.target.value; renderCandidates(); });
    byId("route-filter").addEventListener("change", e => { state.route = e.target.value; renderCandidates(); });
    byId("decision-filter").addEventListener("change", e => { state.decision = e.target.value; renderCandidates(); });
    document.querySelectorAll(".tab-btn[data-page]").forEach((btn) => btn.addEventListener("click", () => switchPage(btn.dataset.page)));
    renderAll();
  </script>
</body>
</html>
"""


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
        "2375": "凱美",
        "2478": "大毅",
        "4916": "事欣科",
        "6141": "柏承",
        "6770": "力積電",
    }

    def candidate_from_weekly(item: dict[str, object], group_label: str) -> dict[str, object]:
        symbol = str(item.get("symbol", ""))
        market_row = market.get(symbol, {})
        scan_row = current_scan.get(symbol, {})
        close = market_row.get("close", item.get("close", ""))
        high = market_row.get("high", item.get("high", close))
        low = market_row.get("low", item.get("low", close))
        volume = market_row.get("volume", item.get("volume", ""))
        change_pct = market_row.get("change_pct", "")
        latest_date = market_row.get("latest_date", "")
        ma3 = scan_row.get("ma3", item.get("ma3", ""))
        ma8 = scan_row.get("ma8", item.get("ma8", ""))
        ma21 = scan_row.get("ma21", item.get("ma21", ""))
        ma55 = scan_row.get("ma55", item.get("ma55", ""))
        ma144 = scan_row.get("ma144", item.get("ma144", ""))
        ma233 = scan_row.get("ma233", item.get("ma233", ""))
        low_volume = is_low_daily_volume(volume)
        effective_group = "淘汰" if low_volume else group_label
        effective_decision = "reject" if low_volume else ("hold" if group_label == "實際操作組" else str(item.get("decision") or "hold"))
        return {
            "symbol": symbol,
            "name": name_map.get(symbol, str(item.get("name", symbol))),
            "latest_price": close,
            "latest_high": high,
            "latest_low": low,
            "key_level": item.get("key_level", scan_row.get("key_level", "")),
            "change_pct": change_pct,
            "score": float(item.get("score") or 0),
            "decision": effective_decision,
            "reason": dynamic_reason(symbol, item | {"volume": volume}, group_label, close, low, ma3, ma8, ma21),
            "market_state": item.get("market_state") or "待確認",
            "pattern_type": display_pattern(item.get("pattern_type")),
            "chip_state": "神秘金字塔週榜偏多；正式籌碼資料待接",
            "entry_trigger": dynamic_entry_trigger_with_volume(symbol, item | {"volume": volume}, group_label, close, low, ma3, ma8),
            "risk_note": dynamic_risk_note_with_volume(symbol, item | {"volume": volume}, close, ma3, ma8),
            "group_assignment": effective_group,
            "index_state": "正常" if not str(latest_date).startswith("n/a") else "待確認",
            "daily_ma_alignment": dynamic_period_alignment(symbol, close, ma3, ma8, ma21)[0],
            "weekly_ma_alignment": dynamic_period_alignment(symbol, close, ma3, ma8, ma21)[1],
            "monthly_ma_alignment": dynamic_period_alignment(symbol, close, ma3, ma8, ma21)[2],
            "shareholder_score": "-",
            "institution_bias": "待接法人/投信資料",
            "next_1d_return": None,
            "next_3d_return": None,
            "next_5d_return": None,
            "latest_date": latest_date,
            "volume": volume,
            "volume_lots": round(volume_lots(volume), 2),
            "volume_gate": "blocked_under_500_lots" if low_volume else "pass",
            "volume_ratio": item.get("volume_ratio", ""),
            "ma": {
                "3MA": ma3,
                "8MA": ma8,
                "21MA": ma21,
                "55MA": ma55,
                "144MA": ma144,
                "233MA": ma233,
            },
            "patterns": dynamic_patterns(item, close, ma3, ma8, ma21),
            "triggers": dynamic_triggers(symbol, close, low, ma3, ma8, change_pct, item.get("volume_ratio")),
        }

    weekly_operation = [
        candidate_from_weekly(
            item,
            "操作組" if str(item.get("decision")) == "hold" else "入選名單",
        )
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
    paper_trading = load_latest_paper_trades()
    postmarket_review = build_postmarket_risk_review(paper_trading, str(latest_day))
    operation_events = load_operation_events(str(latest_day))
    account = build_account_state(paper_trading, market)
    promote_held_candidates(candidates, account)
    next_trading_plan = build_next_trading_plan(candidates, account, str(latest_day))
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
        "paper_trading": paper_trading,
        "operation_events": operation_events,
        "postmarket_review": postmarket_review,
        "next_trading_plan": next_trading_plan,
        "market_indices": build_market_indices(),
    }
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "next_trading_plan_latest.json").write_text(
        json.dumps(next_trading_plan, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    basis_day = str(next_trading_plan.get("basis_day") or latest_day)
    (reports_dir / f"next_trading_plan_{basis_day}.json").write_text(
        json.dumps(next_trading_plan, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    history: list[dict[str, object]] = []
    for history_path in sorted(reports_dir.glob("next_trading_plan_*.json")):
        if history_path.name == "next_trading_plan_latest.json":
            continue
        try:
            history.append(json.loads(history_path.read_text(encoding="utf-8-sig")))
        except (OSError, json.JSONDecodeError):
            continue
    payload["next_trading_history"] = history[-5:]
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
    .account-grid { grid-template-columns:repeat(6,1fr); margin:10px 0 14px; }
    .plan-grid { grid-template-columns:repeat(3,1fr); }
    .scenario-card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }
    .scenario-card h4 { margin:0 0 8px; font-size:14px; }
    .plan-symbol { margin-top:14px; }
    .pos { color:var(--green); font-weight:700; } .neg { color:var(--red); font-weight:700; }
    @media (max-width:1100px) { .overview,.detail-grid,.pool-grid,.account-grid,.plan-grid { grid-template-columns:1fr; } table { display:block; overflow-x:auto; } }
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
        <div class="card pool-card operation"><h3>操作組</h3><p class="muted">持有部位與可操作標的會自動留在這裡；已持有標的不會再重複列入新進場鎖定股。</p><div id="operation-pool"></div></div>
        <div class="card pool-card watch"><h3>觀察組</h3><div id="watch-pool"></div></div>
        <div class="card pool-card eliminate"><h3>淘汰清單</h3><p class="muted">刪除或淘汰標的不特別展示；若未來要看歷史，可查 reports。</p><div id="eliminate-pool"></div></div>
      </div>
    </section>

    <section>
      <h2>模擬交易紀錄</h2>
      <p class="muted">來源：<span id="paper-source">-</span></p>
      <table><thead><tr><th>交易ID</th><th>日期</th><th>股票</th><th>方向</th><th>價格</th><th>股數</th><th>金額</th><th>剩餘資金</th><th>部位</th><th>已實現</th><th>未實現</th><th>原因</th></tr></thead><tbody id="paper-trade-body"></tbody></table>
    </section>

    <section>
      <h2>下個交易日操作</h2>
      <p class="muted" id="next-plan-note">-</p>
      <h3>鎖定股</h3>
      <table><thead><tr><th>分組</th><th>股票</th><th>價格</th><th>Score</th><th>型態</th><th>量比</th><th>狀態</th></tr></thead><tbody id="locked-stock-body"></tbody></table>
      <h3 style="margin-top:14px">帳戶狀態</h3>
      <div class="grid account-grid" id="account-status"></div>
      <h3>持有部位</h3>
      <table><thead><tr><th>股票</th><th>股數</th><th>成本</th><th>現價</th><th>市值</th><th>未實現</th><th>報酬率</th><th>狀態</th></tr></thead><tbody id="holding-body"></tbody></table>
      <div id="next-symbol-plans"></div>
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
    const paperTrades = (dashboardData.paper_trading && dashboardData.paper_trading.rows) || [];
    const nextPlan = dashboardData.next_trading_plan || {};
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
    function renderPaperTrading() {
      byId("paper-source").textContent = (dashboardData.paper_trading && dashboardData.paper_trading.source_file) || "尚無模擬交易檔";
      byId("paper-trade-body").innerHTML = paperTrades.length ? paperTrades.map((item) => `
        <tr>
          <td>${item.trade_id || "-"}</td>
          <td>${item.date || "-"}<br><span class="muted">${item.time || ""}</span></td>
          <td><strong>${item.symbol || "-"}</strong><br><span class="muted">${item.name || ""}</span></td>
          <td><span class="tag ${item.side === "buy" ? "hold" : "reject"}">${item.side || "-"}</span></td>
          <td>${fmt(item.price)}</td>
          <td>${fmt(item.shares, 0)}</td>
          <td>${fmt(item.gross_amount)}</td>
          <td>${fmt(item.cash_after)}</td>
          <td>${fmt(item.position_after, 0)}</td>
          <td>${fmt(item.realized_pnl)}</td>
          <td>${fmt(item.unrealized_pnl)}</td>
          <td>${item.reason || item.notes || "-"}</td>
        </tr>`).join("") : '<tr><td colspan="12" class="muted">尚無模擬交易紀錄</td></tr>';
    }
    function renderAccountStatus() {
      const account = nextPlan.account || {};
      const items = [
        ["原始資金", fmt(account.initial_capital, 0)],
        ["持有部位市值", fmt(account.position_value, 0)],
        ["剩餘資金", fmt(account.cash, 0)],
        ["未實現損益", fmt(account.unrealized_pnl, 0)],
        ["累積獲利", fmt(account.total_pnl, 0)],
        ["資金使用率", pct(account.capital_usage_pct)]
      ];
      byId("account-status").innerHTML = items.map(([label, value]) => `<div class="card"><div class="metric-label">${label}</div><div class="metric-value">${value}</div></div>`).join("");
    }
    function renderNextTradingPlan() {
      const account = nextPlan.account || {};
      const positions = account.positions || [];
      const locked = nextPlan.locked_stocks || [];
      byId("next-plan-note").textContent = `更新時間：${nextPlan.updated_at || "-"} / 適用交易日：${nextPlan.applies_to || "-"} / 資料基準日：${nextPlan.basis_day || "-"} / ${nextPlan.cash_allocation_note || ""}`;
      byId("locked-stock-body").innerHTML = locked.length ? locked.map((item) => `
        <tr><td>${item.group || "-"}</td><td><strong>${item.symbol}</strong><br><span class="muted">${item.name}</span></td><td>${fmt(item.latest_price)}</td><td>${fmt(item.score)}</td><td>${item.pattern_type || "-"}</td><td>${fmt(item.volume_ratio)}</td><td>${item.status || "-"}</td></tr>
      `).join("") : '<tr><td colspan="7" class="muted">目前沒有新進場鎖定股；持有標的請看下方持有部位。</td></tr>';
      renderAccountStatus();
      byId("holding-body").innerHTML = positions.length ? positions.map((item) => `
        <tr><td><strong>${item.symbol}</strong><br><span class="muted">${item.name}</span></td><td>${item.shares}</td><td>${fmt(item.cost_basis)}</td><td>${fmt(item.latest_price)}</td><td>${fmt(item.market_value, 0)}</td><td class="${Number(item.unrealized_pnl) >= 0 ? "pos" : "neg"}">${fmt(item.unrealized_pnl, 0)}</td><td class="${Number(item.unrealized_pct) >= 0 ? "pos" : "neg"}">${pct(item.unrealized_pct)}</td><td>${item.status}</td></tr>
      `).join("") : '<tr><td colspan="8" class="muted">目前無持有部位</td></tr>';
      const holdingPlans = (nextPlan.holding_plans || []).map(renderPlanBlock).join("");
      const symbolPlans = (nextPlan.symbol_plans || []).map(renderPlanBlock).join("");
      byId("next-symbol-plans").innerHTML = `${holdingPlans}${symbolPlans}` || '<p class="muted">目前沒有下個交易日操作劇本。</p>';
    }
    function renderPlanBlock(plan) {
      const scenarios = plan.scenarios || [];
      return `
        <div class="plan-symbol">
          <h3>${plan.symbol} ${plan.name}</h3>
          <table><thead><tr><th>項目</th><th>數值</th></tr></thead><tbody>
            <tr><td>現價 / 成本</td><td>${fmt(plan.latest_price || plan.cost_basis)} / ${plan.cost_basis !== undefined ? fmt(plan.cost_basis) : "-"}</td></tr>
            <tr><td>突破確認價</td><td>${plan.trigger_price !== undefined ? fmt(plan.trigger_price) : "既有持股管理"}</td></tr>
            <tr><td>預估投入</td><td>${plan.rough_budget_low !== undefined ? `${fmt(plan.rough_budget_low, 0)} - ${fmt(plan.rough_budget_high, 0)}` : "既有持股管理"}</td></tr>
            <tr><td>預估股數</td><td>${plan.rough_shares_low !== undefined ? `${plan.rough_shares_low} - ${plan.rough_shares_high} 股，實際以突破成交價重算` : "既有持股管理"}</td></tr>
            <tr><td>狀態</td><td>${plan.entry_status || `${plan.shares || 0} 股`}</td></tr>
            <tr><td>停損 / 支撐</td><td>${plan.stop_price !== undefined ? `${fmt(plan.stop_price)} / ${plan.support_range}` : "跌破 3MA 先降碼，跌破 8MA 全出"}</td></tr>
          </tbody></table>
          <div class="grid plan-grid" style="margin-top:10px">
            ${scenarios.map((scenario) => `<div class="scenario-card"><h4>${scenario.title}</h4><p><b>條件：</b>${scenario.condition}</p><p><b>操作：</b>${scenario.action}</p></div>`).join("")}
          </div>
        </div>
      `;
    }
    function renderTracking() {
      byId("tracking-body").innerHTML = candidates.map((item) => `<tr><td>${dashboardData.selection.selection_date}</td><td><strong>${item.symbol}</strong><br><span class="muted">${item.name}</span></td><td>${item.group_assignment}</td><td>${fmt(item.latest_price)}</td><td>${pct(item.next_1d_return)}</td><td>${pct(item.next_3d_return)}</td><td>${pct(item.next_5d_return)}</td><td class="muted">等待後續日K驗證</td></tr>`).join("");
    }
    function renderAll() { renderMetrics(); renderCandidateTable(); renderDetail(); renderPools(); renderPaperTrading(); renderNextTradingPlan(); renderTracking(); }
    byId("search").addEventListener("input", (event) => { state.query = event.target.value; renderCandidateTable(); });
    byId("decision-filter").addEventListener("change", (event) => { state.decision = event.target.value; renderCandidateTable(); });
    byId("group-filter").addEventListener("change", (event) => { state.group = event.target.value; renderCandidateTable(); });
    renderAll();
  </script>
</body>
</html>
"""
    html_text = build_research_dashboard_template()
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
