from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_CHIP_COLUMNS = ["symbol", "week", "holder_rank", "shares"]


@dataclass(frozen=True)
class ChipScore:
    symbol: str
    frequency: str
    latest_week: str | None
    weekly_share_change: float
    threshold_hit: int | None
    top30_increased: bool
    shareholder_score: float
    large_holder_accumulation_score: float
    reason: str


def load_shareholder_csv(path: str | Path) -> pd.DataFrame:
    """載入大股東持股資料；shares 預期為張數，頻率為 weekly。"""
    df = pd.read_csv(path)
    missing = set(REQUIRED_CHIP_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"籌碼欄位不足: {sorted(missing)} in {path}")
    df = df[REQUIRED_CHIP_COLUMNS].copy()
    df["symbol"] = df["symbol"].astype(str)
    df["holder_rank"] = pd.to_numeric(df["holder_rank"], errors="coerce")
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
    return df.dropna().sort_values(["symbol", "week", "holder_rank"]).reset_index(drop=True)


def score_shareholders(df: pd.DataFrame, rules: dict) -> dict[str, ChipScore]:
    """計算每週大股東持股變化、門檻分級與前 30 名同步增加加分。"""
    chip_rules = rules.get("chip_filter", {})
    thresholds = {int(k): float(v) for k, v in chip_rules.get("thresholds", {}).items()}
    top_n = int(chip_rules.get("top_n_holders", 30))
    bonus = float(chip_rules.get("top30_increase_bonus", 0))
    penalty = float(chip_rules.get("weakening_penalty", 0))
    max_score = float(chip_rules.get("max_score", 100))
    frequency = str(chip_rules.get("frequency", "weekly"))

    scores: dict[str, ChipScore] = {}
    for symbol, part in df.groupby("symbol"):
        weekly = part.groupby("week", as_index=False)["shares"].sum().sort_values("week")
        if len(weekly) < 2:
            scores[symbol] = ChipScore(symbol, frequency, None, 0, None, False, 0, 0, "籌碼資料不足，無法計算週變化")
            continue

        latest = weekly.iloc[-1]
        previous = weekly.iloc[-2]
        change = float(latest["shares"] - previous["shares"])
        hit = max([level for level in thresholds if change >= level], default=None)
        base_score = thresholds.get(hit, 0.0) if hit is not None else 0.0

        latest_week = latest["week"]
        previous_week = previous["week"]
        latest_top = part[(part["week"] == latest_week) & (part["holder_rank"] <= top_n)]["shares"].sum()
        previous_top = part[(part["week"] == previous_week) & (part["holder_rank"] <= top_n)]["shares"].sum()
        top30_increased = bool(latest_top > previous_top)

        score = base_score + (bonus if top30_increased else 0)
        if change < 0:
            score += penalty
        score = max(0.0, min(max_score, score))

        reason_parts = [f"大股東週變化 {change:.0f} 張"]
        if hit is not None:
            reason_parts.append(f"達 {hit} 張門檻")
        if top30_increased:
            reason_parts.append(f"前 {top_n} 名大股東同步增加")
        if change < 0:
            reason_parts.append("籌碼轉弱，降低候選等級")

        scores[symbol] = ChipScore(
            symbol=symbol,
            frequency=frequency,
            latest_week=str(latest_week),
            weekly_share_change=change,
            threshold_hit=hit,
            top30_increased=top30_increased,
            shareholder_score=score,
            large_holder_accumulation_score=score,
            reason="；".join(reason_parts),
        )
    return scores

