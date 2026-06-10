from __future__ import annotations

from typing import Any

from ..models import AgentResult, result_dict


class StrategyRouterAgent:
    """Routes a candidate to long_hold, intraday, watch, or reject.

    Strategy-specific rules are intentionally left configurable. Without explicit
    rules, this agent keeps non-rejected candidates on watch.
    """

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = rules or {}

    def evaluate(
        self,
        symbol: str,
        candidate_result: AgentResult | dict[str, Any],
        index_result: dict[str, Any],
        *,
        has_position: bool = False,
        has_intraday_data: bool = False,
    ) -> AgentResult:
        candidate = result_dict(candidate_result)
        rank = candidate.get("details", {}).get("candidate_rank", candidate.get("action"))
        symbol_routes = self.rules.get("strategy_router", {}).get("symbol_routes", {})

        if rank == "reject":
            route = "reject"
            reason = "candidate scanner rejected this symbol"
        elif symbol in symbol_routes:
            route = str(symbol_routes[symbol])
            reason = "route selected by explicit strategy_router.symbol_routes rule"
        elif has_position:
            route = "long_hold"
            reason = "existing position is routed to long/swing management"
        elif has_intraday_data and self.rules.get("strategy_router", {}).get("allow_intraday_default", False):
            route = "intraday"
            reason = "intraday route allowed by explicit default rule"
        else:
            route = "watch"
            reason = "strategy rules are not filled yet, so candidate stays on watch"

        if index_result.get("operation_mode") == "risk_off" and route in {"long_hold", "intraday"}:
            route = "watch"
            reason = "index agent is risk_off, so active route is downgraded to watch"

        return AgentResult(
            agent_name="strategy_router",
            symbol=symbol,
            action=route,
            confidence=float(candidate.get("confidence", 0.0)),
            reason=reason,
            details={
                "route": route,
                "candidate_rank": rank,
                "has_position": has_position,
                "has_intraday_data": has_intraday_data,
            },
        )
