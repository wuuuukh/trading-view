from __future__ import annotations

from typing import Any

from ..indicators import enrich_indicators
from ..models import AgentResult, result_dict
from ..risk_manager import evaluate_exit_rules


class LongSwingAgent:
    """Manages long-hold or swing candidates after routing."""

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = rules or {}

    def evaluate(
        self,
        symbol: str,
        daily_df,
        route_result: AgentResult | dict[str, Any],
        *,
        position: dict[str, Any] | None = None,
    ) -> AgentResult:
        route = result_dict(route_result).get("action")
        if route != "long_hold":
            return AgentResult(
                agent_name="long_swing_agent",
                symbol=symbol,
                action="skip",
                confidence=0.0,
                reason="route is not long_hold",
                details={"route": route},
            )

        if daily_df.empty:
            return AgentResult(
                agent_name="long_swing_agent",
                symbol=symbol,
                action="wait",
                confidence=0.0,
                reason="daily data is missing",
                details={"route": route},
            )

        enriched = enrich_indicators(daily_df, self.rules)
        latest = enriched.iloc[-1]
        has_position = bool(position)
        if has_position:
            entry_price = float(position.get("entry_price", latest["close"]))
            risk = evaluate_exit_rules(latest, entry_price, self.rules, long_term=True)
            mapped = {"exit_all": "exit", "reduce": "reduce", "hold": "hold"}.get(risk["action"], "hold")
            return AgentResult(
                agent_name="long_swing_agent",
                symbol=symbol,
                action=mapped,
                confidence=70.0,
                reason=str(risk.get("reason", "position risk check completed")),
                details={"route": route, "risk": risk, "position": position},
            )

        return AgentResult(
            agent_name="long_swing_agent",
            symbol=symbol,
            action="wait",
            confidence=50.0,
            reason="long_hold route exists, but build/add rules are not filled yet",
            details={"route": route, "latest_close": float(latest["close"])},
        )
