from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TWSE_STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.TW"


def month_starts(end: date, months: int) -> list[date]:
    year = end.year
    month = end.month
    result: list[date] = []
    for _ in range(months):
        result.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(result))


def fetch_json(url: str, params: dict[str, str]) -> dict:
    query = urlencode(params)
    request = Request(
        f"{url}?{query}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; trading-agent-data-updater/1.0)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def parse_roc_date(value: str) -> str:
    roc_year, month, day = value.split("/")
    return f"{int(roc_year) + 1911:04d}-{int(month):02d}-{int(day):02d}"


def parse_number(value: str) -> float:
    cleaned = value.replace(",", "").replace("--", "").strip()
    return float(cleaned) if cleaned else 0.0


def fetch_twse_month(symbol: str, month: date) -> list[dict[str, object]]:
    payload = fetch_json(
        TWSE_STOCK_DAY,
        {"response": "json", "date": month.strftime("%Y%m%d"), "stockNo": symbol},
    )
    if payload.get("stat") != "OK":
        return []

    rows: list[dict[str, object]] = []
    for item in payload.get("data", []):
        rows.append(
            {
                "timestamp": parse_roc_date(item[0]),
                "open": parse_number(item[3]),
                "high": parse_number(item[4]),
                "low": parse_number(item[5]),
                "close": parse_number(item[6]),
                "volume": int(parse_number(item[1])),
            }
        )
    return rows


def fetch_yahoo(symbol: str, months: int) -> list[dict[str, object]]:
    payload = fetch_json(
        YAHOO_CHART.format(symbol=symbol),
        {"range": f"{months}mo", "interval": "1d"},
    )
    result = (payload.get("chart", {}).get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    meta = result.get("meta", {})
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]

    rows: list[dict[str, object]] = []
    for idx, ts in enumerate(timestamps):
        close = quote.get("close", [])[idx]
        if close is None and idx == len(timestamps) - 1:
            close = meta.get("regularMarketPrice")
        values = {
            "open": quote.get("open", [])[idx],
            "high": quote.get("high", [])[idx],
            "low": quote.get("low", [])[idx],
            "close": close,
            "volume": quote.get("volume", [])[idx],
        }
        if any(value is None for value in values.values()):
            continue
        rows.append(
            {
                "timestamp": datetime.fromtimestamp(int(ts)).date().isoformat(),
                "open": round(float(values["open"]), 2),
                "high": round(float(values["high"]), 2),
                "low": round(float(values["low"]), 2),
                "close": round(float(values["close"]), 2),
                "volume": int(values["volume"]),
            }
        )
    return rows


def update_symbol(symbol: str, out_dir: Path, months: int, end: date) -> int:
    by_date: dict[str, dict[str, object]] = {}
    path = out_dir / f"{symbol}.csv"
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("timestamp"):
                    by_date[str(row["timestamp"])] = {
                        "timestamp": row["timestamp"],
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": int(float(row["volume"])),
                    }

    for month in month_starts(end, months):
        try:
            for row in fetch_twse_month(symbol, month):
                by_date[str(row["timestamp"])] = row
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"{symbol}: skip {month:%Y-%m} ({exc})")
        time.sleep(0.25)

    if not by_date or max(by_date) < end.isoformat():
        for row in fetch_yahoo(symbol, months):
            if str(row["timestamp"]) <= end.isoformat():
                by_date[str(row["timestamp"])] = row

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [by_date[key] for key in sorted(by_date)]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Update OHLCV CSV files from TWSE public data.")
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--out", default="data/ohlcv")
    parser.add_argument("--end", default=date.today().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    end = date.fromisoformat(args.end)
    out_dir = Path(args.out)
    for symbol in args.symbols:
        count = update_symbol(symbol, out_dir, args.months, end)
        print(f"{symbol}: wrote {count} rows")


if __name__ == "__main__":
    main()
