from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..data_loader import load_ohlcv_csv
from ..indicators import enrich_indicators

INDEX_MA_WINDOWS = [3, 8, 21, 55, 144, 233]


@dataclass(frozen=True)
class IndexAgentDecision:
    agent_name: str
    market_bias: str
    operation_mode: str
    index_score: int
    ma_state: dict[str, str]
    risk_flag: bool
    allow_new_position: bool
    allow_chasing: bool
    position_adjustment: str
    reason: str


def _rules_with_index_ma(rules: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(rules or {})
    merged["moving_averages"] = INDEX_MA_WINDOWS
    return merged


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    indexed = df.set_index("timestamp").sort_index()
    out = indexed.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna().reset_index()


def _latest_valid(df: pd.DataFrame | None, rules: dict[str, Any]) -> pd.Series | None:
    if df is None or df.empty:
        return None
    enriched = enrich_indicators(df, rules)
    required = [f"ma{window}" for window in INDEX_MA_WINDOWS]
    valid = enriched.dropna(subset=required, how="any")
    if valid.empty:
        return None
    return valid.iloc[-1]


def _ma_state(row: pd.Series | None) -> str:
    if row is None:
        return "neutral"
    close = float(row["close"])
    ma3 = float(row["ma3"])
    ma8 = float(row["ma8"])
    ma21 = float(row["ma21"])
    ma55 = float(row["ma55"])
    ma144 = float(row["ma144"])
    ma233 = float(row["ma233"])
    if close >= ma3 and ma3 > ma8 > ma21 and ma21 > ma55 and ma55 > ma144 > ma233:
        return "bullish"
    if close < ma8 or ma3 <= ma8:
        return "weak"
    return "neutral"


def _state_score(state: str) -> int:
    return {"bullish": 100, "neutral": 55, "weak": 20}.get(state, 40)


def _daily_change_pct(daily: pd.DataFrame, explicit_change_pct: float | None = None) -> float:
    if explicit_change_pct is not None:
        value = float(explicit_change_pct)
        return value / 100 if abs(value) > 1 else value
    if len(daily) < 2:
        return 0.0
    prev_close = float(daily.iloc[-2]["close"])
    latest_close = float(daily.iloc[-1]["close"])
    if prev_close == 0:
        return 0.0
    return latest_close / prev_close - 1


class IndexAgent:
    """Market gate. It never chooses individual stocks or final entries."""

    def __init__(self, rules: dict[str, Any] | None = None):
        self.rules = _rules_with_index_ma(rules)

    def evaluate(
        self,
        daily: pd.DataFrame,
        *,
        weekly: pd.DataFrame | None = None,
        monthly: pd.DataFrame | None = None,
        k60: pd.DataFrame | None = None,
        intraday: pd.DataFrame | None = None,
        daily_change_pct: float | None = None,
    ) -> IndexAgentDecision:
        if daily.empty:
            raise ValueError("daily index OHLCV is required")

        weekly = weekly if weekly is not None else _resample_ohlcv(daily, "W-FRI")
        monthly = monthly if monthly is not None else _resample_ohlcv(daily, "ME")

        daily_row = _latest_valid(daily, self.rules)
        weekly_row = _latest_valid(weekly, self.rules)
        monthly_row = _latest_valid(monthly, self.rules)
        k60_row = _latest_valid(k60, self.rules)
        intraday_row = _latest_valid(intraday, self.rules)

        daily_state = _ma_state(daily_row)
        weekly_state = _ma_state(weekly_row)
        monthly_state = _ma_state(monthly_row)
        k60_state = _ma_state(k60_row)
        intraday_state = _ma_state(intraday_row)

        change_pct = _daily_change_pct(daily, daily_change_pct)
        drop_limit = float(self.rules.get("market_filter", {}).get("index_drop_conservative_pct", 0.03))
        drop_over_limit = change_pct <= -drop_limit

        close_below_daily_8ma = False
        daily_3_8_weak = daily_state == "weak"
        if daily_row is not None:
            close_below_daily_8ma = float(daily_row["close"]) < float(daily_row["ma8"])
            daily_3_8_weak = float(daily_row["ma3"]) <= float(daily_row["ma8"])

        multi_timeframe_bullish = daily_state == weekly_state == monthly_state == "bullish"
        score = round(
            _state_score(daily_state) * 0.30
            + _state_score(weekly_state) * 0.25
            + _state_score(monthly_state) * 0.25
            + max(_state_score(k60_state), _state_score(intraday_state)) * 0.10
            + 100 * 0.10
        )
        score = int(max(0, min(score, 100)))

        risk_reasons: list[str] = []
        if drop_over_limit:
            score = min(score, 25)
            risk_reasons.append(f"index drop {change_pct * 100:.2f}% reached risk limit")
        if close_below_daily_8ma:
            score = min(score, 55)
            risk_reasons.append("index closed below daily 8MA")
        if daily_3_8_weak:
            score = min(score, 55)
            risk_reasons.append("daily 3MA is not above 8MA")

        if drop_over_limit:
            market_bias = "risk_off"
            operation_mode = "risk_off"
            allow_new_position = False
            allow_chasing = False
            position_adjustment = "no_new_position"
        elif close_below_daily_8ma or daily_3_8_weak:
            market_bias = "weak" if score < 55 else "neutral"
            operation_mode = "cautious"
            allow_new_position = True
            allow_chasing = False
            position_adjustment = "reduce"
        elif multi_timeframe_bullish and score >= 85:
            market_bias = "bullish"
            operation_mode = "aggressive"
            allow_new_position = True
            allow_chasing = True
            position_adjustment = "normal"
        elif score >= 70:
            market_bias = "bullish" if daily_state == "bullish" else "neutral"
            operation_mode = "normal"
            allow_new_position = True
            allow_chasing = daily_state == "bullish"
            position_adjustment = "normal"
        else:
            market_bias = "neutral" if score >= 55 else "weak"
            operation_mode = "cautious"
            allow_new_position = True
            allow_chasing = False
            position_adjustment = "reduce"

        if risk_reasons:
            reason = "; ".join(risk_reasons)
        elif multi_timeframe_bullish:
            reason = "daily, weekly, and monthly index structure are aligned"
        else:
            reason = "market is usable but not fully aligned"

        return IndexAgentDecision(
            agent_name="index_agent",
            market_bias=market_bias,
            operation_mode=operation_mode,
            index_score=score,
            ma_state={"daily": daily_state, "weekly": weekly_state, "monthly": monthly_state},
            risk_flag=bool(risk_reasons),
            allow_new_position=allow_new_position,
            allow_chasing=allow_chasing,
            position_adjustment=position_adjustment,
            reason=reason,
        )


def evaluate_index_market(
    daily: pd.DataFrame,
    rules: dict[str, Any] | None = None,
    *,
    weekly: pd.DataFrame | None = None,
    monthly: pd.DataFrame | None = None,
    k60: pd.DataFrame | None = None,
    intraday: pd.DataFrame | None = None,
    daily_change_pct: float | None = None,
) -> IndexAgentDecision:
    return IndexAgent(rules).evaluate(
        daily,
        weekly=weekly,
        monthly=monthly,
        k60=k60,
        intraday=intraday,
        daily_change_pct=daily_change_pct,
    )


def evaluate_index_market_from_csv(
    daily_path: str | Path,
    rules: dict[str, Any] | None = None,
    *,
    weekly_path: str | Path | None = None,
    monthly_path: str | Path | None = None,
    k60_path: str | Path | None = None,
    intraday_path: str | Path | None = None,
    daily_change_pct: float | None = None,
) -> dict[str, Any]:
    daily = load_ohlcv_csv(daily_path)
    weekly = load_ohlcv_csv(weekly_path) if weekly_path else None
    monthly = load_ohlcv_csv(monthly_path) if monthly_path else None
    k60 = load_ohlcv_csv(k60_path) if k60_path else None
    intraday = load_ohlcv_csv(intraday_path) if intraday_path else None
    return asdict(
        evaluate_index_market(
            daily,
            rules,
            weekly=weekly,
            monthly=monthly,
            k60=k60,
            intraday=intraday,
            daily_change_pct=daily_change_pct,
        )
    )
