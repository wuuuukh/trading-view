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
    symbols = [str(symbol) for symbol in data.get("source_symbols", [])]
    for item in data.get("groups", {}).get("observation_group", []):
        symbol = str(item.get("symbol", "")).strip()
        if symbol:
            symbols.append(symbol)
    return list(dict.fromkeys(symbols))


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


def parse_numbers(row_text: str, symbol: str, name: str) -> list[float]:
    prefix = row_text.split(f"{symbol}{name}", 1)[-1].strip()
    return [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", prefix)]


def parse_top_rows(text: str, rank_limit: int = 10) -> tuple[str, list[dict[str, object]]]:
    close_match = re.search(r"收盤價日期:(\d{4}/\d{2}/\d{2})", text)
    close_date = close_match.group(1).replace("/", "-") if close_match else ""
    rows: list[dict[str, object]] = []
    for row_match in re.finditer(r"<tr[^>]*>.*?</tr>", text, re.S):
        row_html = row_match.group(0)
        stock_match = re.search(r"StockHolders\.aspx\?STOCK=(\d{4}).*?>([^<]*?)</a>", row_html, re.S)
        if not stock_match:
            continue
        row_text = clean_text(row_html)
        rank_match = re.match(r"(\d+)\s+", row_text)
        rank = int(rank_match.group(1) if rank_match else len(rows) + 1)
        if rank > rank_limit:
            break
        symbol = stock_match.group(1)
        raw_name = clean_text(stock_match.group(2))
        name = raw_name.replace(symbol, "", 1).strip() or raw_name
        numbers = parse_numbers(row_text, symbol, name)
        weekly_changes = numbers[:6]
        latest_two_positive = len(weekly_changes) >= 6 and weekly_changes[-1] > 0 and weekly_changes[-2] > 0
        total_change = numbers[7] if len(numbers) > 7 else None
        if not latest_two_positive:
            continue
        rows.append(
            {
                "rank": rank,
                "symbol": symbol,
                "name": name,
                "weekly_changes": weekly_changes,
                "latest_two_changes": weekly_changes[-2:],
                "total_change": total_change,
                "row_text": row_text,
            }
        )
    if not rows:
        raise RuntimeError("No TWSTHR rows matched: rank <= 10 and latest two weekly changes > 0.")
    return close_date, rows


def main() -> None:
    close_date, current_selection = parse_top_rows(fetch_html())
    previous_selection = previous_symbols()
    symbols_to_track = list(dict.fromkeys([str(row["symbol"]) for row in current_selection] + previous_selection))
    payload = {
        "fetched_at": date.today().isoformat(),
        "source_url": URL,
        "source_close_date": close_date,
        "selection_rule": "rank <= 10 by six-week total change and latest two weekly changes both positive",
        "current_top5": current_selection,
        "previous_top5": previous_selection,
        "symbols_to_track": symbols_to_track,
    }
    out_path = ROOT / "config" / "weekly_symbols.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(" ".join(symbols_to_track))


if __name__ == "__main__":
    main()
