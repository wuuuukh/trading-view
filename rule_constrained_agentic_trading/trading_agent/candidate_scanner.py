from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from .ai_agent import RuleConstrainedAgent, decision_to_dict
from .chip_loader import ChipScore
from .indicators import enrich_indicators
from .pattern_detector import detect_patterns
from .trend_structure import classify_market_state


def build_candidate(symbol: str, df: pd.DataFrame, rules: dict, chip: ChipScore | None) -> dict:
    enriched = enrich_indicators(df, rules)
    latest = enriched.iloc[-1].to_dict()
    trend = classify_market_state(enriched)
    pattern = detect_patterns(enriched, rules)
    chip_score = chip.large_holder_accumulation_score if chip else 0.0
    chip_reason = chip.reason if chip else "沒有籌碼資料，僅能列入技術觀察，不列最高優先"
    return {
        "symbol": symbol,
        "latest": latest,
        "trend": trend,
        "pattern": pattern,
        "chip_score": chip_score,
        "chip_reason": chip_reason,
        "chip": asdict(chip) if chip else None,
    }


def scan_candidates(ohlcv_map: dict[str, pd.DataFrame], chip_scores: dict[str, ChipScore], rules: dict) -> list[dict]:
    """執行 candidate scanning，再交由規則約束 Agent 評分分層。"""
    agent = RuleConstrainedAgent(rules)
    decisions: list[dict] = []
    for symbol, df in ohlcv_map.items():
        if df.empty:
            continue
        candidate = build_candidate(symbol, df, rules, chip_scores.get(str(symbol)))
        decisions.append(decision_to_dict(agent.evaluate(candidate)))
    return sorted(decisions, key=lambda item: item["score"], reverse=True)

