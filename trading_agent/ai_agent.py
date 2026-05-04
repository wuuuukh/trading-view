from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AgentDecision:
    symbol: str
    decision: str
    score: float
    tier: str
    reason: str
    market_state: str
    pattern_type: str | None
    risk_note: str
    details: dict[str, Any]


class RuleConstrainedAgent:
    """只執行 SOP 規則的 Agent，不自由發明策略、不黑箱下單。"""

    def __init__(self, rules: dict):
        self.rules = rules

    def evaluate(self, candidate: dict) -> AgentDecision:
        weights = self.rules.get("agent_weights", {})
        trend = candidate["trend"]["trend_score"]
        ma = candidate["trend"]["ma_score"]
        pattern = candidate["pattern"]["score"]
        volume = min(float(candidate["latest"].get("volume_ratio", 0)) / 1.5 * 100, 100)
        chip = candidate["chip_score"]

        score = (
            trend * weights.get("trend_structure", 25)
            + ma * weights.get("moving_average_alignment", 25)
            + pattern * weights.get("pattern_quality", 20)
            + volume * weights.get("volume_price", 15)
            + chip * weights.get("chip", 15)
        ) / max(sum(weights.values()), 1)

        no_structure = candidate["pattern"]["pattern_type"] is None
        weak_market = candidate["trend"]["market_state"] == "weak_or_unclear"
        no_volume = float(candidate["latest"].get("volume_ratio", 0)) < self.rules.get("scanner", {}).get("min_volume_ratio_breakout", 1.2)

        if no_structure or weak_market:
            decision = "reject"
        elif score >= self.rules.get("scanner", {}).get("primary_min_score", 75):
            decision = "accept"
        else:
            decision = "hold"

        if decision == "accept" and chip <= 0:
            tier = "secondary_watchlist"
            decision = "hold"
        elif score >= self.rules.get("scanner", {}).get("primary_min_score", 75) and chip > 0:
            tier = "primary_review"
        elif score >= self.rules.get("scanner", {}).get("secondary_min_score", 55):
            tier = "secondary_watchlist"
        else:
            tier = "lower_priority"

        reasons = [
            candidate["trend"]["reason"],
            candidate["pattern"]["reason"],
            candidate["chip_reason"],
        ]
        if no_structure:
            reasons.append("沒有結構，不做")
        if no_volume:
            reasons.append("沒有足夠成交量，不列最高優先")
        if weak_market:
            reasons.append("弱勢或趨勢不清，不做強勢股以外標的")

        risk_note = "突破型初始停損 3%；收盤跌破日K 3MA 先出 1/2，跌破日K 8MA 全出；加碼只在走強時進行。"
        return AgentDecision(
            symbol=candidate["symbol"],
            decision=decision,
            score=round(score, 2),
            tier=tier,
            reason="；".join(reasons),
            market_state=candidate["trend"]["market_state"],
            pattern_type=candidate["pattern"]["pattern_type"],
            risk_note=risk_note,
            details=candidate,
        )


def decision_to_dict(decision: AgentDecision) -> dict:
    return asdict(decision)

