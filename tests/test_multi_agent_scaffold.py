from __future__ import annotations

import unittest

import pandas as pd

from trading_agent.agents.decision_risk_controller import DecisionRiskController
from trading_agent.agents.index_agent import evaluate_index_market
from trading_agent.agents.strategy_router_agent import StrategyRouterAgent
from trading_agent.models import AgentResult


def make_ohlcv(rows: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="B")
    close = [100 + i * 0.2 for i in range(rows)]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": [x + 1 for x in close],
            "low": [x - 1 for x in close],
            "close": close,
            "volume": [1000] * rows,
        }
    )


class MultiAgentScaffoldTest(unittest.TestCase):
    def test_index_agent_turns_large_drop_into_risk_off(self) -> None:
        result = evaluate_index_market(
            make_ohlcv(),
            {"market_filter": {"index_drop_conservative_pct": 0.03}},
            daily_change_pct=-3.1,
        )

        self.assertEqual(result.operation_mode, "risk_off")
        self.assertFalse(result.allow_new_position)
        self.assertFalse(result.allow_chasing)

    def test_router_keeps_candidates_on_watch_until_rules_are_filled(self) -> None:
        candidate = AgentResult(
            agent_name="candidate_scanner",
            symbol="6141",
            action="secondary",
            confidence=70,
            reason="test",
            details={"candidate_rank": "secondary"},
        )
        route = StrategyRouterAgent({}).evaluate(
            "6141",
            candidate,
            {"operation_mode": "normal"},
            has_position=False,
            has_intraday_data=True,
        )

        self.assertEqual(route.action, "watch")

    def test_decision_controller_blocks_rejected_candidates(self) -> None:
        candidate = AgentResult("candidate_scanner", "6141", "reject", 0, "test")
        route = AgentResult("strategy_router", "6141", "reject", 0, "test")
        skip = AgentResult("long_swing_agent", "6141", "skip", 0, "test")
        final = DecisionRiskController({}).evaluate(
            "6141",
            index_result={"operation_mode": "normal"},
            candidate_result=candidate,
            route_result=route,
            long_swing_result=skip,
            intraday_result=skip,
        )

        self.assertEqual(final.action, "reject")


if __name__ == "__main__":
    unittest.main()
