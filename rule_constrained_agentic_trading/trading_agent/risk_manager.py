from __future__ import annotations

import pandas as pd

from .trend_structure import closed_below_ma


def evaluate_exit_rules(row: pd.Series, entry_price: float, rules: dict, long_term: bool = False) -> dict:
    """依 SOP 產生停損/減碼訊號；不因情緒移動停損。"""
    stop_pct = float(rules.get("risk", {}).get("breakout_stop_loss_pct", 0.03))
    loss_hit = float(row["close"]) <= entry_price * (1 - stop_pct)
    below_3 = closed_below_ma(row, "ma3")
    below_8 = closed_below_ma(row, "ma8")
    below_month_3 = long_term and closed_below_ma(row, "ma3")

    if loss_hit:
        return {"action": "exit_all", "fraction": 1.0, "reason": "突破型虧損達 3%，立即出場"}
    if below_month_3:
        return {"action": "exit_all", "fraction": 1.0, "reason": "長線持有跌破月K 3MA，全出"}
    if below_8:
        return {"action": "exit_all", "fraction": 1.0, "reason": "收盤跌破日K 8MA，全出"}
    if below_3:
        return {"action": "reduce", "fraction": 0.5, "reason": "收盤跌破日K 3MA，先出 1/2"}
    return {"action": "hold", "fraction": 0.0, "reason": "趨勢未破核心防線，續抱"}

