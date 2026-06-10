from __future__ import annotations

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TWSE_STOCK_DAY = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_DAILY_QUOTES = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
TPEX_DAILY_TRADE = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
TDCC_SHAREHOLDERS = "https://opendata.tdcc.com.tw/getOD.ashx"


def fetch_json(url: str, params: dict[str, str], timeout: int = 40) -> dict | list:
    request = Request(
        f"{url}?{urlencode(params)}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; trading-agent-official-replay/1.0)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8-sig", errors="replace").strip()
    if body.startswith("<"):
        raise ValueError("official endpoint returned HTML instead of JSON")
    return json.loads(body) if body else {}


def parse_number(value: object) -> float:
    text = str(value).replace(",", "").replace("--", "").replace("X", "").strip()
    if not text:
        return 0.0
    return float(text)


def parse_roc_date(value: str) -> str:
    parts = value.strip().split("/")
    if len(parts) == 3:
        return f"{int(parts[0]) + 1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    if len(value) == 7:
        return f"{int(value[:3]) + 1911:04d}-{int(value[3:5]):02d}-{int(value[5:7]):02d}"
    if len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    raise ValueError(f"unsupported ROC date: {value}")


def daterange(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def month_starts(start: date, end: date) -> list[date]:
    current = date(start.year, start.month, 1)
    months: list[date] = []
    while current <= end:
        months.append(current)
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)
    return months


def is_common_stock_code(code: str) -> bool:
    return len(code) == 4 and code.isdigit()


def fetch_twse_month(symbol: str, month: date) -> list[dict[str, object]]:
    payload = fetch_json(
        TWSE_STOCK_DAY,
        {"response": "json", "date": month.strftime("%Y%m%d"), "stockNo": symbol},
    )
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []
    rows: list[dict[str, object]] = []
    for item in payload.get("data", []):
        rows.append(
            {
                "timestamp": parse_roc_date(str(item[0])),
                "open": parse_number(item[3]),
                "high": parse_number(item[4]),
                "low": parse_number(item[5]),
                "close": parse_number(item[6]),
                "volume": int(parse_number(item[1])),
            }
        )
    return rows


def fetch_tpex_daily_quotes(day: date) -> list[dict[str, object]]:
    payload = fetch_json(
        TPEX_DAILY_QUOTES,
        {"date": day.strftime("%Y/%m/%d"), "response": "json"},
    )
    if not isinstance(payload, dict) or payload.get("stat") == "參數輸入錯誤":
        return []
    table = (payload.get("tables") or [{}])[0]
    rows: list[dict[str, object]] = []
    for item in table.get("data", []):
        symbol = str(item[0]).strip()
        if not is_common_stock_code(symbol):
            continue
        try:
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": day.isoformat(),
                    "open": parse_number(item[4]),
                    "high": parse_number(item[5]),
                    "low": parse_number(item[6]),
                    "close": parse_number(item[2]),
                    "volume": int(parse_number(item[8])),
                }
            )
        except (IndexError, ValueError):
            continue
    return rows


def fetch_tpex_institution_day(day: date) -> list[dict[str, object]]:
    payload = fetch_json(
        TPEX_DAILY_TRADE,
        {"date": day.strftime("%Y/%m/%d"), "type": "Daily", "response": "json"},
    )
    if not isinstance(payload, dict):
        return []
    table = (payload.get("tables") or [{}])[0]
    rows: list[dict[str, object]] = []
    for item in table.get("data", []):
        symbol = str(item[0]).strip()
        if not is_common_stock_code(symbol):
            continue
        try:
            rows.append(
                {
                    "date": day.isoformat(),
                    "symbol": symbol,
                    "foreign_net": int(parse_number(item[10])),
                    "investment_trust_net": int(parse_number(item[13])),
                    "dealer_net": int(parse_number(item[22])),
                    "total_institutional_net": int(parse_number(item[-1])),
                    "source": "TPEX",
                }
            )
        except (IndexError, ValueError):
            continue
    return rows


def fetch_twse_institution_day(day: date) -> list[dict[str, object]]:
    payload = fetch_json(
        TWSE_T86,
        {"date": day.strftime("%Y%m%d"), "selectType": "ALLBUT0999", "response": "json"},
        timeout=60,
    )
    if not isinstance(payload, dict) or payload.get("stat") != "OK":
        return []
    rows: list[dict[str, object]] = []
    for item in payload.get("data", []):
        symbol = str(item[0]).strip()
        if not is_common_stock_code(symbol):
            continue
        try:
            rows.append(
                {
                    "date": day.isoformat(),
                    "symbol": symbol,
                    "foreign_net": int(parse_number(item[4])),
                    "investment_trust_net": int(parse_number(item[10])),
                    "dealer_net": int(parse_number(item[16])),
                    "total_institutional_net": int(parse_number(item[-1])),
                    "source": "TWSE",
                }
            )
        except (IndexError, ValueError):
            continue
    return rows


def read_symbols(paths: list[str]) -> list[str]:
    symbols: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            symbols.extend(p.stem for p in path.glob("*.csv") if is_common_stock_code(p.stem))
        elif path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                token = line.strip().split(",")[0]
                if is_common_stock_code(token):
                    symbols.append(token)
    return list(dict.fromkeys(symbols))


def write_ohlcv_files(rows_by_symbol: dict[str, dict[str, dict[str, object]]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields = ["timestamp", "open", "high", "low", "close", "volume"]
    for symbol, by_date in sorted(rows_by_symbol.items()):
        path = out_dir / f"{symbol}.csv"
        merged: dict[str, dict[str, object]] = {}
        if path.exists():
            with path.open("r", newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    merged[str(row["timestamp"])] = row
        merged.update(by_date)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for key in sorted(merged):
                row = merged[key]
                writer.writerow({field: row[field] for field in fields})


def write_institution(rows: list[dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["date", "symbol", "foreign_net", "investment_trust_net", "dealer_net", "total_institutional_net", "source"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda item: (str(item["date"]), str(item["symbol"]), str(item["source"]))))


def fetch_tdcc_shareholders() -> list[dict[str, object]]:
    request = Request(
        f"{TDCC_SHAREHOLDERS}?{urlencode({'id': '1-5'})}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; trading-agent-official-replay/1.0)",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=90) as response:
        text = response.read().decode("utf-8-sig", errors="replace")
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(text.splitlines())
    for item in reader:
        symbol = str(item.get("證券代號", "")).strip()
        if not is_common_stock_code(symbol):
            continue
        rows.append(
            {
                "date": parse_roc_date(str(item.get("資料日期", "")).strip()),
                "symbol": symbol,
                "holder_level": str(item.get("持股分級", "")).strip(),
                "holders": int(parse_number(item.get("人數", 0))),
                "shares": int(parse_number(item.get("股數", 0))),
                "ratio": parse_number(item.get("占集保庫存數比例%", 0)),
                "source": "TDCC",
            }
        )
    return rows


def write_shareholders(rows: list[dict[str, object]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["date", "symbol", "holder_level", "holders", "shares", "ratio", "source"]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda item: (str(item["date"]), str(item["symbol"]), str(item["holder_level"]))))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official replay data from TWSE/TPEX public endpoints.")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-05-31")
    parser.add_argument("--out", default="data/official_replay")
    parser.add_argument("--twse-symbol-source", action="append", default=["data/ohlcv"])
    parser.add_argument("--skip-twse", action="store_true")
    parser.add_argument("--skip-tpex", action="store_true")
    parser.add_argument("--skip-institution", action="store_true")
    parser.add_argument("--skip-twse-institution", action="store_true")
    parser.add_argument("--skip-tpex-institution", action="store_true")
    parser.add_argument("--skip-tdcc", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    out = Path(args.out)
    ohlcv_rows: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    institution_rows: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []

    if not args.skip_twse:
        symbols = read_symbols(args.twse_symbol_source)
        for symbol in symbols:
            for month in month_starts(start, end):
                try:
                    for row in fetch_twse_month(symbol, month):
                        if args.start <= str(row["timestamp"]) <= args.end:
                            ohlcv_rows[symbol][str(row["timestamp"])] = row
                except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                    failures.append({"source": "TWSE_STOCK_DAY", "date": month.isoformat(), "symbol": symbol, "error": str(exc)})
                time.sleep(args.sleep)

    if not args.skip_tpex:
        for day in daterange(start, end):
            try:
                for row in fetch_tpex_daily_quotes(day):
                    symbol = str(row.pop("symbol"))
                    ohlcv_rows[symbol][str(row["timestamp"])] = row
            except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                failures.append({"source": "TPEX_DAILY_QUOTES", "date": day.isoformat(), "symbol": "", "error": str(exc)})
            time.sleep(args.sleep)

    if not args.skip_institution:
        for day in daterange(start, end):
            sources = []
            if not args.skip_twse_institution:
                sources.append(("TWSE_T86", fetch_twse_institution_day))
            if not args.skip_tpex_institution:
                sources.append(("TPEX_DAILY_TRADE", fetch_tpex_institution_day))
            for source, fn in sources:
                try:
                    institution_rows.extend(fn(day))
                except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                    failures.append({"source": source, "date": day.isoformat(), "symbol": "", "error": str(exc)})
                time.sleep(args.sleep)

    shareholder_rows: list[dict[str, object]] = []
    if not args.skip_tdcc:
        try:
            shareholder_rows = fetch_tdcc_shareholders()
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            failures.append({"source": "TDCC_SHAREHOLDERS", "date": "", "symbol": "", "error": str(exc)})

    write_ohlcv_files(ohlcv_rows, out / "ohlcv")
    write_institution(institution_rows, out / "institution" / "institution_daily.csv")
    write_shareholders(shareholder_rows, out / "shareholders" / "tdcc_shareholders.csv")
    (out / "metadata").mkdir(parents=True, exist_ok=True)
    (out / "metadata" / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "start": args.start,
                "end": args.end,
                "ohlcv_symbols": len(ohlcv_rows),
                "institution_rows": len(institution_rows),
                "shareholder_rows": len(shareholder_rows),
                "failures": len(failures),
                "out": str(out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
