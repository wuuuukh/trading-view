from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from .agents import (
    CandidateScannerAgent,
    DecisionRiskController,
    IndexAgent,
    IntradayAgent,
    LongSwingAgent,
    StrategyRouterAgent,
)
from .chip_loader import ChipScore
from .models import PipelineResult


def evaluate_multi_agent_pipeline(
    *,
    index_daily: pd.DataFrame,
    stock_daily_map: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    chip_scores: dict[str, ChipScore] | None = None,
    positions: dict[str, dict[str, Any]] | None = None,
    index_weekly: pd.DataFrame | None = None,
    index_monthly: pd.DataFrame | None = None,
    index_k60: pd.DataFrame | None = None,
    index_intraday: pd.DataFrame | None = None,
    intraday_map: dict[str, pd.DataFrame] | None = None,
    k15_map: dict[str, pd.DataFrame] | None = None,
    k60_map: dict[str, pd.DataFrame] | None = None,
    daily_change_pct: float | None = None,
) -> PipelineResult:
    chip_scores = chip_scores or {}
    positions = positions or {}
    intraday_map = intraday_map or {}
    k15_map = k15_map or {}
    k60_map = k60_map or {}

    index_decision = IndexAgent(rules).evaluate(
        index_daily,
        weekly=index_weekly,
        monthly=index_monthly,
        k60=index_k60,
        intraday=index_intraday,
        daily_change_pct=daily_change_pct,
    )
    index_result = asdict(index_decision)

    scanner = CandidateScannerAgent(rules)
    router = StrategyRouterAgent(rules)
    long_swing = LongSwingAgent(rules)
    intraday = IntradayAgent(rules)
    controller = DecisionRiskController(rules)

    symbol_results: list[dict[str, Any]] = []
    for symbol, daily_df in sorted(stock_daily_map.items()):
        if daily_df.empty:
            continue
        position = positions.get(str(symbol))
        candidate_result = scanner.evaluate(str(symbol), daily_df, chip_scores.get(str(symbol)))
        route_result = router.evaluate(
            str(symbol),
            candidate_result,
            index_result,
            has_position=bool(position),
            has_intraday_data=str(symbol) in intraday_map,
        )
        long_swing_result = long_swing.evaluate(str(symbol), daily_df, route_result, position=position)
        intraday_result = intraday.evaluate(
            str(symbol),
            route_result,
            intraday_df=intraday_map.get(str(symbol)),
            k15_df=k15_map.get(str(symbol)),
            k60_df=k60_map.get(str(symbol)),
            index_result=index_result,
        )
        final_result = controller.evaluate(
            str(symbol),
            index_result=index_result,
            candidate_result=candidate_result,
            route_result=route_result,
            long_swing_result=long_swing_result,
            intraday_result=intraday_result,
            position=position,
        )

        symbol_results.append(
            {
                "symbol": str(symbol),
                "candidate_scanner": candidate_result.to_dict(),
                "strategy_router": route_result.to_dict(),
                "long_swing_agent": long_swing_result.to_dict(),
                "intraday_agent": intraday_result.to_dict(),
                "decision_risk_controller": final_result.to_dict(),
            }
        )

    return PipelineResult(index=index_result, symbols=symbol_results)
