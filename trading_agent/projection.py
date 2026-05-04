from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def load_watchlist(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def estimate_win_rate(score: float, tier: str) -> float:
    """Research-only probability estimate from agent score; not a statistical backtest."""
    base = 0.48 + max(min(score, 90), 50) / 1000
    tier_bonus = 0.025 if tier == "primary_review" else 0.0
    return round(min(max(base + tier_bonus, 0.45), 0.68), 3)


def estimate_target_return(score: float, tier: str) -> float:
    if tier == "primary_review":
        return round(0.025 + max(score - 70, 0) * 0.001, 3)
    return round(0.018 + max(score - 60, 0) * 0.0008, 3)


def build_next_week_projection(watchlist: dict[str, Any], rules: dict, capital: float | None = None) -> dict[str, Any]:
    items = watchlist.get("items", [])
    total_capital = float(capital if capital is not None else watchlist.get("capital", 1_000_000))
    stop_loss_pct = float(rules.get("risk", {}).get("breakout_stop_loss_pct", 0.03))
    first_entry_fraction = float(rules.get("risk", {}).get("first_entry_fraction", 0.3333))
    allocation = str(watchlist.get("allocation", "score_weighted"))
    score_sum = sum(float(item.get("score", 0)) for item in items)

    rows: list[dict[str, Any]] = []
    for item in items:
        score = float(item.get("score", 0))
        tier = str(item.get("tier", "secondary_watchlist"))
        if allocation == "score_weighted" and score_sum > 0:
            full_capital = total_capital * score / score_sum
        else:
            full_capital = total_capital / max(len(items), 1)
        win_rate = estimate_win_rate(score, tier)
        target_return = estimate_target_return(score, tier)
        first_entry_capital = full_capital * first_entry_fraction
        max_loss = first_entry_capital * stop_loss_pct
        upside_profit = first_entry_capital * target_return
        expected_profit = win_rate * upside_profit - (1 - win_rate) * max_loss

        rows.append({
            "symbol": item.get("symbol"),
            "name": item.get("name", ""),
            "tier": tier,
            "score": score,
            "allocation_weight_pct": round(full_capital / total_capital * 100, 2),
            "estimated_win_rate": win_rate,
            "full_slot_capital": round(full_capital, 0),
            "first_entry_capital": round(first_entry_capital, 0),
            "target_return_pct": round(target_return * 100, 2),
            "stop_loss_pct": round(stop_loss_pct * 100, 2),
            "upside_profit": round(upside_profit, 0),
            "max_stop_loss": round(max_loss, 0),
            "expected_profit": round(expected_profit, 0),
            "thesis": item.get("thesis", ""),
            "rule": "只在放量突破或回踩 8MA/頸線不破時試單；未突破不進場。",
        })

    deployed_capital = sum(float(row["first_entry_capital"]) for row in rows)
    expected_profit_total = sum(float(row["expected_profit"]) for row in rows)
    max_stop_loss_total = sum(float(row["max_stop_loss"]) for row in rows)
    upside_profit_total = sum(float(row["upside_profit"]) for row in rows)
    avg_win_rate = sum(float(row["estimated_win_rate"]) for row in rows) / max(len(rows), 1)

    return {
        "week": watchlist.get("week", "next_week"),
        "capital": round(total_capital, 0),
        "method": f"{allocation}_first_entry_research_projection",
        "assumptions": {
            "allocation": "依 agent score 配重完整額度；下週仍只先用 1/3 試單。",
            "win_rate": "由 agent score 與分層轉換為研究用機率，尚未用真實歷史回測校準。",
            "profit": "上行情境用分數推估 2% 到 4% 區間；下行情境使用突破型 3% 停損。",
            "execution": "沒有開盤確認、沒有量、沒有突破，就不進場，實際投入可能低於試算值。",
        },
        "summary": {
            "estimated_average_win_rate": round(avg_win_rate, 3),
            "deployed_capital_if_all_trigger": round(deployed_capital, 0),
            "cash_reserved": round(total_capital - deployed_capital, 0),
            "upside_profit_if_all_win": round(upside_profit_total, 0),
            "max_stop_loss_if_all_fail": round(max_stop_loss_total, 0),
            "expected_profit": round(expected_profit_total, 0),
            "expected_return_on_total_capital_pct": round(expected_profit_total / total_capital * 100, 2),
        },
        "rows": rows,
    }


def write_projection_reports(projection: dict[str, Any], out_dir: str | Path, prefix: str = "next_week_projection") -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{prefix}.json"
    csv_path = out / f"{prefix}.csv"
    md_path = out / f"{prefix}.md"

    json_path.write_text(json.dumps(projection, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(projection["rows"]).to_csv(csv_path, index=False, encoding="utf-8-sig")

    summary = projection["summary"]
    lines = [
        "# Next Week Capital Projection",
        "",
        f"- week: {projection['week']}",
        f"- capital: {projection['capital']:,.0f}",
        f"- estimated_average_win_rate: {summary['estimated_average_win_rate']:.1%}",
        f"- deployed_capital_if_all_trigger: {summary['deployed_capital_if_all_trigger']:,.0f}",
        f"- cash_reserved: {summary['cash_reserved']:,.0f}",
        f"- upside_profit_if_all_win: {summary['upside_profit_if_all_win']:,.0f}",
        f"- max_stop_loss_if_all_fail: {summary['max_stop_loss_if_all_fail']:,.0f}",
        f"- expected_profit: {summary['expected_profit']:,.0f}",
        f"- expected_return_on_total_capital_pct: {summary['expected_return_on_total_capital_pct']:.2f}%",
        "",
        "此為研究用情境試算，不是真實勝率回測，也不是投資建議。",
        "",
    ]
    for row in projection["rows"]:
        lines.extend([
            f"## {row['symbol']} {row['name']}",
            f"- score: {row['score']:.0f}",
            f"- tier: {row['tier']}",
            f"- allocation_weight_pct: {row['allocation_weight_pct']:.2f}%",
            f"- estimated_win_rate: {row['estimated_win_rate']:.1%}",
            f"- full_slot_capital: {row['full_slot_capital']:,.0f}",
            f"- first_entry_capital: {row['first_entry_capital']:,.0f}",
            f"- upside_profit: {row['upside_profit']:,.0f}",
            f"- max_stop_loss: {row['max_stop_loss']:,.0f}",
            f"- expected_profit: {row['expected_profit']:,.0f}",
            f"- rule: {row['rule']}",
            "",
        ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}
