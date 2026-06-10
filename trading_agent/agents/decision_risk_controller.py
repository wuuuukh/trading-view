from __future__ import annotations

from typing import Any

from ..models import AgentResult, result_dict


class DecisionRiskController:
    """Final gate. Only this controller emits final_action."""

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = rules or {}

    def evaluate(
        self,
        symbol: str,
        *,
        index_result: dict[str, Any],
        candidate_result: AgentResult | dict[str, Any],
        route_result: AgentResult | dict[str, Any],
        long_swing_result: AgentResult | dict[str, Any],
        intraday_result: AgentResult | dict[str, Any],
        position: dict[str, Any] | None = None,
    ) -> AgentResult:
        candidate = result_dict(candidate_result)
        route = result_dict(route_result)
        long_swing = result_dict(long_swing_result)
        intraday = result_dict(intraday_result)
        has_position = bool(position)

        if index_result.get("operation_mode") == "risk_off":
            action = "reduce" if has_position else "wait"
            reason = "index agent is risk_off"
        elif candidate.get("action") == "reject":
            action = "reject"
            reason = "candidate scanner rejected this symbol"
        elif route.get("action") == "reject":
            action = "reject"
            reason = "strategy router rejected this symbol"
        elif route.get("action") == "watch":
            action = "wait"
            reason = "strategy router put this symbol on watch"
        elif route.get("action") == "long_hold":
            action = long_swing.get("action", "wait")
            reason = f"long/swing result: {long_swing.get('reason', '')}"
        elif route.get("action") == "intraday":
            intraday_action = intraday.get("action")
            action = "enter" if intraday_action == "enter_now" else "wait"
            reason = f"intraday result: {intraday.get('reason', '')}"
        else:
            action = "wait"
            reason = "no executable route is available"

        if not has_position and action in {"reduce", "exit"}:
            action = "wait"
            reason = "no position exists, so reduce/exit is downgraded to wait"

        return AgentResult(
            agent_name="decision_risk_controller",
            symbol=symbol,
            action=action,
            confidence=70.0,
            reason=reason,
            details={
                "final_action": action,
                "has_position": has_position,
                "route": route.get("action"),
                "index_operation_mode": index_result.get("operation_mode"),
            },
        )
