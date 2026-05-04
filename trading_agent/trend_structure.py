from __future__ import annotations

import pandas as pd


def moving_average_alignment(row: pd.Series) -> dict:
    """判斷短中長均線多頭排列，維持個人均線系統，不改用通用 5/10/20。"""
    short_strong = row.get("ma3", 0) > row.get("ma8", 0) > row.get("ma21", 0)
    mid_bull = row.get("ma21", 0) > row.get("ma55", 0)
    long_bull = row.get("ma55", 0) > row.get("ma144", 0) > row.get("ma233", 0)
    return {
        "short_strong": bool(short_strong),
        "mid_bull": bool(mid_bull),
        "long_bull": bool(long_bull),
        "ma_score": int(short_strong) * 35 + int(mid_bull) * 35 + int(long_bull) * 30,
    }


def classify_market_state(df: pd.DataFrame) -> dict:
    """依收盤價與均線結構判斷市場狀態，避免弱勢股進入最高優先級。"""
    if len(df) == 0:
        return {"market_state": "unknown", "trend_score": 0, "reason": "無資料"}
    row = df.iloc[-1]
    align = moving_average_alignment(row)
    above_21 = row["close"] > row.get("ma21", float("inf"))
    above_55 = row["close"] > row.get("ma55", float("inf"))
    above_144 = row["close"] > row.get("ma144", float("inf"))
    score = align["ma_score"] * 0.7 + int(above_21) * 10 + int(above_55) * 10 + int(above_144) * 10
    if score >= 75:
        state = "strong_uptrend"
    elif score >= 55:
        state = "constructive"
    elif score >= 35:
        state = "watch_only"
    else:
        state = "weak_or_unclear"
    return {"market_state": state, "trend_score": round(score, 2), "reason": f"均線分數 {align['ma_score']}，價格相對主要均線檢查完成", **align}


def body_low(row: pd.Series) -> float:
    """上升趨勢線使用實體低點，不看下影線。"""
    return float(min(row["open"], row["close"]))


def body_high(row: pd.Series) -> float:
    """下降趨勢線使用實體高點，不看上影線。"""
    return float(max(row["open"], row["close"]))


def closed_below_ma(row: pd.Series, ma_name: str) -> bool:
    """盤中跌破不算，僅用收盤確認。"""
    return bool(row["close"] < row.get(ma_name, float("-inf")))

