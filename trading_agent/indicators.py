from __future__ import annotations

import pandas as pd


def add_moving_averages(df: pd.DataFrame, windows: list[int]) -> pd.DataFrame:
    """依照 SOP 固定計算 3/8/21/55/144/233 均線。"""
    out = df.copy()
    for window in windows:
        out[f"ma{window}"] = out["close"].rolling(window=window, min_periods=window).mean()
    return out


def add_volume_features(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """計算成交量均量與量比；成交量只作規則確認，不取代結構。"""
    out = df.copy()
    out["volume_ma"] = out["volume"].rolling(window=window, min_periods=1).mean()
    out["volume_ratio"] = out["volume"] / out["volume_ma"].replace(0, pd.NA)
    return out


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    """MACD 僅作輔助動能觀察，不作主導進出場條件。"""
    out = df.copy()
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    return out


def enrich_indicators(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    windows = [int(x) for x in rules.get("moving_averages", [3, 8, 21, 55, 144, 233])]
    return add_macd(add_volume_features(add_moving_averages(df, windows)))

