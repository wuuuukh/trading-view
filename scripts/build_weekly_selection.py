from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SYMBOL_NAMES = {
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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_weekly_symbols() -> dict[str, Any]:
    path = ROOT / "config" / "weekly_symbols.json"
    if not path.exists():
        raise FileNotFoundError("config/weekly_symbols.json not found. Run scripts/fetch_twsthr_top_week.py first.")
    return load_json(path)


def week_range_from_close(close_date: str) -> tuple[str, str]:
    close = datetime.strptime(close_date, "%Y-%m-%d").date()
    source_start = close - timedelta(days=4)
    target_start = close + timedelta(days=3)
    target_end = target_start + timedelta(days=4)
    return f"{source_start.isoformat()} to {close.isoformat()}", f"{target_start.isoformat()} to {target_end.isoformat()}"


def group_item(symbol: str, current_symbols: set[str], previous_symbols: set[str]) -> str:
    if symbol in current_symbols:
        return "operation_group"
    if symbol in previous_symbols:
        return "observation_group"
    return "rejected"


def action_for(symbol: str, group: str) -> str:
    if group == "operation_group":
        return "本週符合神秘金字塔條件：六週總增減排名前十，且最近兩週增減皆為正值；先列入選名單，仍需等待操作組規則、5K切入點與60K MACD確認。"
    if group == "observation_group":
        return "上週操作組本週掉出神秘金字塔前五，先降到觀察組保留一週；若結構未轉強或籌碼鬆動，下週淘汰。"
    return "本週不列入選股池。"


def build_weekly_selection(
    scan_rows: list[dict[str, Any]],
    weekly_symbols: dict[str, Any],
) -> dict[str, Any]:
    current_top5 = weekly_symbols["current_top5"]
    current_symbols = {str(row["symbol"]) for row in current_top5}
    previous_symbols = set(str(symbol) for symbol in weekly_symbols.get("previous_top5", [])) - current_symbols
    tracked_symbols = current_symbols | previous_symbols
    scan_by_symbol = {str(item["symbol"]): item for item in scan_rows}

    rows: list[dict[str, Any]] = []
    for symbol in weekly_symbols.get("symbols_to_track", []):
        symbol = str(symbol)
        item = scan_by_symbol.get(symbol)
        if not item:
            continue
        group = group_item(symbol, current_symbols, previous_symbols)
        details = item.get("details", {})
        latest = details.get("latest", {})
        pattern = details.get("pattern", {})
        source_row = next((row for row in current_top5 if str(row["symbol"]) == symbol), None)
        rows.append(
            {
                "symbol": symbol,
                "name": (source_row or {}).get("name") or SYMBOL_NAMES.get(symbol, symbol),
                "group": group,
                "decision": item.get("decision"),
                "score": item.get("score"),
                "tier": item.get("tier"),
                "market_state": item.get("market_state"),
                "pattern_type": item.get("pattern_type") or "",
                "close": latest.get("close", ""),
                "volume_ratio": round(float(latest.get("volume_ratio", 0)), 2),
                "ma3": round(float(latest.get("ma3", 0)), 2),
                "ma8": round(float(latest.get("ma8", 0)), 2),
                "ma21": round(float(latest.get("ma21", 0)), 2),
                "key_level": pattern.get("key_level", ""),
                "chip_status": "籌碼未確認" if details.get("chip") is None else "籌碼偏多",
                "twsthr_rank": (source_row or {}).get("rank", ""),
                "twsthr_latest_two_changes": (source_row or {}).get("latest_two_changes", []),
                "twsthr_total_change": (source_row or {}).get("total_change", ""),
                "action": action_for(symbol, group),
                "reason": item.get("reason", ""),
            }
        )

    source_week, target_week = week_range_from_close(weekly_symbols["source_close_date"])
    return {
        "selection_date": date.today().isoformat(),
        "source_week": source_week,
        "target_week": target_week,
        "source": "神秘金字塔股權類股排行週榜條件篩選",
        "source_close_date": weekly_symbols["source_close_date"],
        "source_symbols": [row["symbol"] for row in current_top5],
        "previous_symbols": weekly_symbols.get("previous_top5", []),
        "method": "每週日先抓神秘金字塔週排行，保留六週總增減排名前十且最近兩週增減皆為正值者，再用上一週完整日K套SOP產生下週選股池；掉出條件的上週操作股先降觀察組一週。",
        "groups": {
            "operation_group": [row for row in rows if row["group"] == "operation_group"],
            "trading_group": [],
            "observation_group": [row for row in rows if row["group"] == "observation_group"],
        },
        "rows": [row for row in rows if row["symbol"] in tracked_symbols],
    }


def write_outputs(selection: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "weekly_selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rows = selection["rows"]
    with (out_dir / "weekly_selection.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Weekly Selection",
        "",
        f"- selection_date: {selection['selection_date']}",
        f"- source_close_date: {selection['source_close_date']}",
        f"- source_week: {selection['source_week']}",
        f"- target_week: {selection['target_week']}",
        f"- method: {selection['method']}",
        "",
    ]
    labels = {
        "operation_group": "入選名單",
        "trading_group": "操作組",
        "observation_group": "觀察組",
    }
    for group_key, label in labels.items():
        lines.extend([f"## {label}", ""])
        items = selection["groups"][group_key]
        if not items:
            lines.extend(["- 無", ""])
            continue
        for row in items:
            lines.append(
                f"- {row['symbol']} {row['name']} | score {row['score']} | "
                f"{row['pattern_type'] or '待確認'} | rank {row.get('twsthr_rank') or '-'} | "
                f"近兩週 {row.get('twsthr_latest_two_changes') or '-'} | 總增減 {row.get('twsthr_total_change') or '-'} | {row['action']}"
            )
        lines.append("")
    (out_dir / "weekly_selection.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    scan_path = ROOT / "reports" / "scan.json"
    selection = build_weekly_selection(load_json(scan_path), load_weekly_symbols())
    write_outputs(selection, ROOT / "reports")
    write_outputs(selection, ROOT / "docs" / "reports")
    write_outputs(selection, ROOT / "site" / "reports")
    print("updated weekly selection reports")


if __name__ == "__main__":
    main()
