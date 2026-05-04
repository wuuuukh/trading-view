from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """載入單一 OHLCV CSV，欄位統一為 timestamp/open/high/low/close/volume。"""
    df = pd.read_csv(path)
    missing = set(REQUIRED_OHLCV_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"OHLCV 欄位不足: {sorted(missing)} in {path}")
    df = df[REQUIRED_OHLCV_COLUMNS].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna().sort_values("timestamp").reset_index(drop=True)


def load_ohlcv_folder(folder: str | Path) -> dict[str, pd.DataFrame]:
    """從資料夾載入多檔股票資料；檔名不含副檔名視為 symbol。"""
    result: dict[str, pd.DataFrame] = {}
    for path in sorted(Path(folder).glob("*.csv")):
        result[path.stem] = load_ohlcv_csv(path)
    return result

