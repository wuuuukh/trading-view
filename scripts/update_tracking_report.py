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
                "ma3": round(float(latest.get("ma3", 0)), 2),
                "ma8": round(float(latest.get("ma8", 0)), 2),
                "ma21": round(float(latest.get("ma21", 0)), 2),
                "key_level": pattern.get("key_level", ""),
                "tracking_action": classify_action(item),
            }
        )
    return rows


def classify_action(item: dict) -> str:
    decision = item.get("decision")
    score = float(item.get("score", 0))
    pattern_type = item.get("pattern_type")
    if decision == "hold" and score >= 85 and pattern_type:
        return "優先追蹤，等待突破後不跌破 3MA/8MA"
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


def write_markdown(rows: list[dict[str, object]]) -> Path:
    path = ROOT / "reports" / "tracking_summary.md"
    latest_day = rows[0]["data_latest_completed_day"] if rows else "n/a"
    lines = [
        "# Trading Tracking Summary",
        "",
        f"- run_date: {date.today().isoformat()}",
        f"- latest_completed_day: {latest_day}",
        "- note: 2026-05-05 full daily candle was not available from the data source at update time.",
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


def write_html(rows: list[dict[str, object]]) -> Path:
    path = ROOT / "trading-record.html"
    index_path = ROOT / "index.html"
    latest_day = rows[0]["data_latest_completed_day"] if rows else "n/a"
    hold_rows = [row for row in rows if row["decision"] == "hold"]
    reject_rows = [row for row in rows if row["decision"] != "hold"]
    table_rows = "\n".join(render_row(idx, row) for idx, row in enumerate(rows, 1))
    original_candidates = "\n".join(
        [
            render_original_candidate("1", "4958", "臻鼎-KY", "Primary review", "4/30 漲停創高，投信 4 月買超 16,574 張，AI + 載板 + 光通訊。"),
            render_original_candidate("2", "8046", "南電", "Primary review", "4/30 漲停創高，投信連 4 月買超，4 月買超 15,239 張。"),
            render_original_candidate("3", "3037", "欣興", "Primary review", "4/30 漲停創高，投信 4 月買超 29,940 張，PCB/載板主線。"),
            render_original_candidate("4", "2313", "華通", "Primary review", "4/30 投信買超第 1，外資也買超 10,304 張，收漲 6.3%。"),
            render_original_candidate("5", "6205", "詮欣", "Secondary watchlist", "使用者提供：大股東持有張數持續增加，籌碼加分；技術面仍需開盤後確認。"),
        ]
    )
    html_text = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="60">
  <title>AI Agent Trading System Report</title>
  <style>
    :root {{
      --bg: #f5f6f4;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #646a73;
      --line: #d9ddd7;
      --accent: #116c5f;
      --warn: #8a5a00;
      --danger: #a43b32;
      --ok: #1f6f43;
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
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 28px 34px 20px;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px 24px 42px;
    }}
    h1 {{ margin: 0 0 6px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 20px; letter-spacing: 0; }}
    p {{ margin: 6px 0; }}
    .muted {{ color: var(--muted); }}
    .notice {{
      margin-top: 14px;
      padding: 12px 14px;
      border-left: 4px solid var(--warn);
      background: #fff8e8;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .metric {{ font-size: 26px; font-weight: 700; }}
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
      .summary {{ grid-template-columns: 1fr 1fr; }}
      .grid {{ grid-template-columns: 1fr; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>AI Agent Trading System Report</h1>
    <p class="muted">更新日：{date.today().isoformat()}；最新完整日線：{html.escape(str(latest_day))}</p>
    <div class="notice">2026-05-05 的完整日 K 尚未由資料源發布，本次模型使用最新可取得的 2026-05-04 完整日線。若盤中追蹤，請把 2026-05-05 視為即時觀察，不當作正式收盤訊號。</div>
  </header>
  <main>
    <section class="summary">
      <div class="card"><div class="muted">追蹤候選</div><div class="metric">{len(hold_rows)}</div></div>
      <div class="card"><div class="muted">剔除/等待</div><div class="metric">{len(reject_rows)}</div></div>
      <div class="card"><div class="muted">資料檔</div><div class="metric">{len(rows)}</div></div>
      <div class="card"><div class="muted">自選股</div><div class="metric">{sum(1 for row in rows if row.get("custom_watchlist"))}</div></div>
    </section>
    <section>
      <h2>原始系統定位</h2>
      <div class="grid">
        <div class="card">
          <strong>用途</strong>
          <p>這是一套圍繞個人交易 SOP、操作思維、均線系統、型態邏輯與籌碼面選股規則所設計的 rule-constrained AI Agent Trading 系統。</p>
        </div>
        <div class="card">
          <strong>限制</strong>
          <p>系統用途是研究型、自動化輔助型交易系統，不接真實券商 API、不做真實下單、不做 webhook。</p>
        </div>
        <div class="card">
          <strong>輸出</strong>
          <p>保留 JSON / CSV / Markdown / HTML 報告，供每日追蹤與回顧，不取代人工決策。</p>
        </div>
      </div>
    </section>
    <section>
      <h2>原始交易 SOP</h2>
      <div class="grid">
        <div class="card">
          <strong>只做強勢</strong>
          <ul>
            <li>只做強勢股，不做弱勢股。</li>
            <li>只做順勢，不抄底，不摸頂。</li>
            <li>先看結構，再看均線，再看量價，最後才是進場。</li>
          </ul>
        </div>
        <div class="card">
          <strong>技術規則</strong>
          <ul>
            <li>固定均線：3、8、21、55、144、233。</li>
            <li>型態先支援 W 型、突破型、N 字型。</li>
            <li>沒有結構，不做；沒有量，不做；沒有趨勢，不做；沒有規則，不做。</li>
          </ul>
        </div>
        <div class="card">
          <strong>籌碼規則</strong>
          <ul>
            <li>加入大股東每週持股張數變化。</li>
            <li>籌碼門檻：400 / 600 / 800 / 1000 張。</li>
            <li>前 30 名大股東持股同步增加則額外加分。</li>
            <li>籌碼面是加分與排序條件，不單獨取代技術結構。</li>
          </ul>
        </div>
      </div>
    </section>
    <section>
      <h2>2026/04/27-2026/05/03 原始候選名單</h2>
      <table>
        <thead>
          <tr><th>排名</th><th>代號</th><th>名稱</th><th>分層</th><th>原始理由</th></tr>
        </thead>
        <tbody>
          {original_candidates}
        </tbody>
      </table>
      <p class="muted">原先移出前 5 的股票：2330 台積電、2317 鴻海、3231 緯創、2454 聯發科。理由是短線資料中部分標的有轉弱或法人調節跡象；依 SOP，短線不追弱、不猜反彈。</p>
    </section>
    <section>
      <h2>2026/05/04 開盤後執行規則</h2>
      <div class="grid">
        <div class="card">
          <strong>可升級或試單</strong>
          <ul>
            <li>放量突破區間高點、前高或頸線。</li>
            <li>回踩 8MA、頸線或關鍵支撐不破。</li>
            <li>回檔時量縮，轉強時量增。</li>
            <li>3MA &gt; 8MA &gt; 21MA 為短線偏強。</li>
            <li>21MA &gt; 55MA 為中期偏多。</li>
          </ul>
        </div>
        <div class="card">
          <strong>不做條件</strong>
          <ul>
            <li>未突破前不進場。</li>
            <li>沒有量不做。</li>
            <li>走弱不加碼。</li>
            <li>跌破日 K 3MA 先出 1/2。</li>
            <li>跌破日 K 8MA 全出。</li>
            <li>突破型虧損達 3% 立即出場。</li>
          </ul>
        </div>
        <div class="card">
          <strong>下次讀檔方式</strong>
          <ul>
            <li><code>2026-05-03_trading_agent_session.md</code></li>
            <li><code>config/rules.yaml</code></li>
            <li><code>config/next_week_watchlist.yaml</code></li>
            <li><code>reports/tracking_log.csv</code></li>
          </ul>
        </div>
      </div>
    </section>
    <section>
      <h2>2026/05/05 新增追蹤資料</h2>
      <table>
        <thead>
          <tr>
            <th>排名</th><th>代號</th><th>名稱</th><th>自選股</th><th>決策</th><th>分數</th><th>收盤</th><th>漲跌幅</th><th>量比</th><th>型態</th><th>動作</th>
          </tr>
        </thead>
        <tbody>
          {table_rows}
        </tbody>
      </table>
    </section>
    <section>
      <h2>交易結論</h2>
      <p>優先追蹤：3037 欣興、4958 臻鼎-KY、6205 詮欣。三檔皆為強多排列且模型分數 85，策略上仍是等待突破或回測後不跌破 3MA/8MA，不追高。</p>
      <p>暫不納入：8046 南電、2313 華通。8046 趨勢強但量能與結構不足；2313 短線結構較弱，維持低優先。</p>
      <p class="muted">風控規則：突破型初始停損 3%；收盤跌破日 K 3MA 先出 1/2，跌破日 K 8MA 全出；加碼只在走強時進行。</p>
    </section>
    <section>
      <h2>輸出檔案</h2>
      <p><code>reports/tracking_log.csv</code> 保存每次追蹤紀錄；<code>reports/tracking_summary.md</code> 保存本次摘要；掃描原始輸出在 <code>reports/scan.json</code> 與 <code>reports/scan.csv</code>。</p>
    </section>
  </main>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8-sig")
    index_path.write_text(html_text, encoding="utf-8-sig")
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
    print("updated trading-record.html")


if __name__ == "__main__":
    main()
