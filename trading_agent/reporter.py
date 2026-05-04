from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def write_reports(decisions: list[dict], out_dir: str | Path, prefix: str = "scan") -> dict[str, Path]:
    """輸出 JSON / CSV / Markdown，確保每個 decision 都能人工閱讀。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{prefix}.json"
    csv_path = out / f"{prefix}.csv"
    md_path = out / f"{prefix}.md"

    json_path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    flat = [
        {
            "symbol": d["symbol"],
            "decision": d["decision"],
            "score": d["score"],
            "tier": d["tier"],
            "market_state": d["market_state"],
            "pattern_type": d["pattern_type"],
            "reason": d["reason"],
            "risk_note": d["risk_note"],
        }
        for d in decisions
    ]
    pd.DataFrame(flat).to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines = ["# Candidate Scan Report", ""]
    for d in decisions:
        lines.extend([
            f"## {d['symbol']} - {d['decision']} ({d['score']})",
            f"- tier: {d['tier']}",
            f"- market_state: {d['market_state']}",
            f"- pattern_type: {d['pattern_type']}",
            f"- reason: {d['reason']}",
            f"- risk_note: {d['risk_note']}",
            "",
        ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}

