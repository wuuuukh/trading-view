from __future__ import annotations

import pandas as pd

from .candidate_scanner import build_candidate
from .ai_agent import RuleConstrainedAgent
from .chip_loader import ChipScore
from .indicators import enrich_indicators


def compare_baseline_vs_agent(symbol: str, df: pd.DataFrame, rules: dict, chip: ChipScore | None = None) -> dict:
    """研究用比較：baseline 只看突破；agent 加入 SOP、均線、型態、量價與籌碼。"""
    enriched = enrich_indicators(df, rules)
    if len(enriched) < 25:
        return {"symbol": symbol, "baseline_signal": False, "agent_decision": "reject", "reason": "資料不足"}
    latest = enriched.iloc[-1]
    prior_high = enriched.iloc[-21:-1]["high"].max()
    baseline_signal = bool(latest["close"] > prior_high and latest.get("volume_ratio", 0) >= 1.2)
    candidate = build_candidate(symbol, df, rules, chip)
    decision = RuleConstrainedAgent(rules).evaluate(candidate)
    return {
        "symbol": symbol,
        "baseline_signal": baseline_signal,
        "agent_decision": decision.decision,
        "agent_score": decision.score,
        "agent_tier": decision.tier,
        "reason": decision.reason,
    }

