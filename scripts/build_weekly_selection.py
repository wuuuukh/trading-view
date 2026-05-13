from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SYMBOL_NAMES = {
    "3037": "欣興",
    "4958": "臻鼎-KY",
    "6205": "詮欣",
    "8046": "南電",
    "2313": "華通",
}


def load_scan(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def group_item(item: dict[str, Any]) -> str:
    details = item.get("details", {})
    chip = details.get("chip")
    if item.get("decision") == "accept" and chip is not None:
        return "operation_group"
    if item.get("decision") == "hold":
        return "observation_group"
    return "rejected"


def action_for(item: dict[str, Any], group: str) -> str:
    if group == "operation_group":
        return "等待5K切入點與60K MACD確認後，才允許現價切入。"
    if group == "observation_group":
        return "列觀察組，不追高；補齊籌碼或切入確認前不進實際操作組。"
    return "本週不列入選股池；等待型態、量能、均線與籌碼重新轉強。"


def build_weekly_selection(
    scan_rows: list[dict[str, Any]],
    selection_date: str,
    source_week: str,
    target_week: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in scan_rows:
        group = group_item(item)
        details = item.get("details", {})
        latest = details.get("latest", {})
        pattern = details.get("pattern", {})
        rows.append(
            {
                "symbol": item["symbol"],
                "name": SYMBOL_NAMES.get(str(item["symbol"]), str(item["symbol"])),
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
                "action": action_for(item, group),
                "reason": item.get("reason", ""),
            }
        )

    return {
        "selection_date": selection_date,
        "source_week": source_week,
        "target_week": target_week,
        "method": "每週日用上一週完整日K資料產生下週選股池，不使用下週未來資料。",
        "groups": {
            "operation_group": [row for row in rows if row["group"] == "operation_group"],
            "observation_group": [row for row in rows if row["group"] == "observation_group"],
            "rejected": [row for row in rows if row["group"] == "rejected"],
        },
        "rows": rows,
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
        f"- source_week: {selection['source_week']}",
        f"- target_week: {selection['target_week']}",
        f"- method: {selection['method']}",
        "",
    ]
    labels = {
        "operation_group": "實際操作組",
        "observation_group": "觀察組",
        "rejected": "暫停/淘汰",
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
                f"{row['pattern_type'] or '無型態'} | {row['action']}"
            )
        lines.append("")
    (out_dir / "weekly_selection.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    scan_path = ROOT / "reports" / "weekly_2026-05-10" / "scan.json"
    selection = build_weekly_selection(
        load_scan(scan_path),
        selection_date="2026-05-10",
        source_week="2026-05-04 to 2026-05-08",
        target_week="2026-05-11 to 2026-05-15",
    )
    write_outputs(selection, ROOT / "reports")
    write_outputs(selection, ROOT / "docs" / "reports")
    write_outputs(selection, ROOT / "site" / "reports")
    print("updated weekly selection reports")


if __name__ == "__main__":
    main()
