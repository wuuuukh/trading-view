from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ..ai_agent import RuleConstrainedAgent
from ..candidate_scanner import build_candidate
from ..chip_loader import ChipScore
from ..models import AgentResult


def _stock_rank(decision: dict[str, Any]) -> str:
    if decision["decision"] == "reject":
        return "reject"
    if decision["tier"] == "primary_review":
        return "primary"
    if decision["tier"] == "secondary_watchlist":
        return "secondary"
    return "reject"


class CandidateScannerAgent:
    """Wraps the original stock agent as the conservative candidate scanner."""

    def __init__(self, rules: dict[str, Any]):
        self.rules = rules
        self.legacy_agent = RuleConstrainedAgent(rules)

    def evaluate(self, symbol: str, df, chip: ChipScore | None = None) -> AgentResult:
        candidate = build_candidate(symbol, df, self.rules, chip)
        legacy = asdict(self.legacy_agent.evaluate(candidate))
        rank = _stock_rank(legacy)
        action = "reject" if rank == "reject" else rank
        return AgentResult(
            agent_name="candidate_scanner",
            symbol=symbol,
            action=action,
            confidence=float(legacy.get("score", 0.0)),
            reason=legacy.get("reason", ""),
            details={
                "candidate_rank": rank,
                "legacy_decision": legacy.get("decision"),
                "legacy_tier": legacy.get("tier"),
                "legacy": legacy,
            },
        )
