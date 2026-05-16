from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
URL = "https://twsthr.info/StockHoldersTopWeek.aspx?Show=1"


def previous_symbols() -> list[str]:
    path = ROOT / "reports" / "weekly_selection.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(symbol) for symbol in data.get("source_symbols", [])]


def fetch_html() -> str:
    request = urllib.request.Request(
        URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_top_rows(text: str, limit: int = 5) -> tuple[str, list[dict[str, str]]]:
    close_match = re.search(r"收盤價日期:(\d{4}/\d{2}/\d{2})", text)
    close_date = close_match.group(1).replace("/", "-") if close_match else ""
    rows: list[dict[str, str]] = []
    for row_match in re.finditer(r"<tr[^>]*>.*?</tr>", text, re.S):
        row_html = row_match.group(0)
        stock_match = re.search(r"StockHolders\.aspx\?STOCK=(\d{4}).*?>([^<]*?)</a>", row_html, re.S)
        if not stock_match:
            continue
        row_text = clean_text(row_html)
        rank_match = re.match(r"(\d+)\s+", row_text)
        symbol = stock_match.group(1)
        raw_name = clean_text(stock_match.group(2))
        name = raw_name.replace(symbol, "", 1).strip() or raw_name
        rows.append(
            {
                "rank": str(rank_match.group(1) if rank_match else len(rows) + 1),
                "symbol": symbol,
                "name": name,
                "row_text": row_text,
            }
        )
        if len(rows) >= limit:
            break
    if len(rows) < limit:
        raise RuntimeError(f"Only parsed {len(rows)} TWSTHR rows from weekly ranking.")
    return close_date, rows


def main() -> None:
    close_date, current_top5 = parse_top_rows(fetch_html())
    previous_top5 = previous_symbols()
    symbols_to_track = list(dict.fromkeys([row["symbol"] for row in current_top5] + previous_top5))
    payload = {
        "fetched_at": date.today().isoformat(),
        "source_url": URL,
        "source_close_date": close_date,
        "current_top5": current_top5,
        "previous_top5": previous_top5,
        "symbols_to_track": symbols_to_track,
    }
    out_path = ROOT / "config" / "weekly_symbols.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(" ".join(symbols_to_track))


if __name__ == "__main__":
    main()
