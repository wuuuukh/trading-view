from __future__ import annotations

from typing import Any

from ..models import AgentResult, result_dict


class IntradayAgent:
    """Checks intraday entry timing after routing.

    Until the user fills intraday rules, this agent never emits enter_now.
    """

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = rules or {}

    def evaluate(
        self,
        symbol: str,
        route_result: AgentResult | dict[str, Any],
        *,
        intraday_df=None,
        k15_df=None,
        k60_df=None,
        index_result: dict[str, Any] | None = None,
    ) -> AgentResult:
        route = result_dict(route_result).get("action")
        operation_mode = (index_result or {}).get("operation_mode", "unknown")

        if route != "intraday":
            return AgentResult(
                agent_name="intraday_agent",
                symbol=symbol,
                action="skip",
                confidence=0.0,
                reason="route is not intraday",
                details={"route": route, "operation_mode": operation_mode},
            )
        if operation_mode == "risk_off":
            return AgentResult(
                agent_name="intraday_agent",
                symbol=symbol,
                action="avoid",
                confidence=90.0,
                reason="index agent is risk_off",
                details={"route": route, "operation_mode": operation_mode},
            )
        if intraday_df is None or getattr(intraday_df, "empty", True):
            return AgentResult(
                agent_name="intraday_agent",
                symbol=symbol,
                action="wait",
                confidence=10.0,
                reason="intraday data is missing",
                details={"route": route, "operation_mode": operation_mode, "missing_data": ["5K"]},
            )

        return AgentResult(
            agent_name="intraday_agent",
            symbol=symbol,
            action="wait",
            confidence=50.0,
            reason="intraday rules are not filled yet",
            details={
                "route": route,
                "operation_mode": operation_mode,
                "rows_5k": len(intraday_df),
                "rows_15k": 0 if k15_df is None else len(k15_df),
                "rows_60k": 0 if k60_df is None else len(k60_df),
            },
        )
