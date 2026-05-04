from __future__ import annotations

import pandas as pd


def detect_breakout(df: pd.DataFrame, rules: dict) -> dict:
    scanner = rules.get("scanner", {})
    window = int(scanner.get("breakout_window", 20))
    min_volume_ratio = float(scanner.get("min_volume_ratio_breakout", 1.2))
    if len(df) < window + 1:
        return {"matched": False, "pattern_type": None, "score": 0, "key_level": None, "reason": "突破型資料不足"}
    recent = df.iloc[-window - 1 : -1]
    row = df.iloc[-1]
    range_high = float(recent["high"].max())
    above_all_ma = all(row["close"] > row.get(f"ma{x}", float("inf")) for x in [3, 8, 21, 55])
    volume_ok = row.get("volume_ratio", 0) >= min_volume_ratio
    matched = bool(row["close"] > range_high and above_all_ma and volume_ok)
    score = int(row["close"] > range_high) * 40 + int(above_all_ma) * 35 + int(volume_ok) * 25
    return {"matched": matched, "pattern_type": "breakout" if matched else None, "score": score, "key_level": range_high, "reason": f"區間高點 {range_high:.2f}，量比 {row.get('volume_ratio', 0):.2f}"}


def detect_w_pattern(df: pd.DataFrame, rules: dict) -> dict:
    """W 型態初版：兩段低點接近，突破中間反彈頸線後才有效。"""
    if len(df) < 35:
        return {"matched": False, "pattern_type": None, "score": 0, "key_level": None, "reason": "W 型態資料不足"}
    part = df.iloc[-35:]
    lows = part.nsmallest(2, "low").sort_index()
    if len(lows) < 2:
        return {"matched": False, "pattern_type": None, "score": 0, "key_level": None, "reason": "找不到雙底"}
    first_idx, second_idx = lows.index[0], lows.index[1]
    if second_idx <= first_idx:
        return {"matched": False, "pattern_type": None, "score": 0, "key_level": None, "reason": "第二底順序不成立"}
    neckline = float(df.loc[first_idx:second_idx, "high"].max())
    second_low_ok = float(df.loc[second_idx, "low"]) >= float(df.loc[first_idx, "low"]) * 0.97
    breakout = float(df.iloc[-1]["close"]) > neckline
    volume_ok = float(df.iloc[-1].get("volume_ratio", 0)) >= float(rules.get("scanner", {}).get("min_volume_ratio_breakout", 1.2))
    matched = bool(second_low_ok and breakout and volume_ok)
    score = int(second_low_ok) * 30 + int(breakout) * 45 + int(volume_ok) * 25
    return {"matched": matched, "pattern_type": "w_pattern" if matched else None, "score": score, "key_level": neckline, "reason": f"頸線 {neckline:.2f}，第二底不破/假跌破檢查 {second_low_ok}"}


def detect_n_pattern(df: pd.DataFrame, rules: dict) -> dict:
    """N 字型態初版：先上漲、量縮回檔不破支撐、再突破前高。"""
    if len(df) < 45:
        return {"matched": False, "pattern_type": None, "score": 0, "key_level": None, "reason": "N 字型態資料不足"}
    pre = df.iloc[-45:-20]
    pullback = df.iloc[-20:-5]
    attack = df.iloc[-5:]
    prior_rise = pre["close"].iloc[-1] > pre["close"].iloc[0] * 1.08
    support = float(pre["close"].iloc[-1])
    pullback_holds = float(pullback["close"].min()) >= support * 0.92
    volume_contracts = float(pullback["volume"].mean()) < float(pre["volume"].mean())
    key_level = float(max(pre["high"].max(), pullback["high"].max()))
    breakout_again = float(attack.iloc[-1]["close"]) > key_level
    matched = bool(prior_rise and pullback_holds and volume_contracts and breakout_again)
    score = int(prior_rise) * 25 + int(pullback_holds) * 25 + int(volume_contracts) * 20 + int(breakout_again) * 30
    return {"matched": matched, "pattern_type": "n_pattern" if matched else None, "score": score, "key_level": key_level, "reason": f"N 字關鍵位 {key_level:.2f}，量縮回檔 {volume_contracts}"}


def detect_patterns(df: pd.DataFrame, rules: dict) -> dict:
    patterns = [detect_w_pattern(df, rules), detect_breakout(df, rules), detect_n_pattern(df, rules)]
    # 避免把 best 本體塞回 all_patterns，否則輸出 dict/JSON 時會形成自我引用。
    best = dict(max(patterns, key=lambda item: item["score"]))
    best["all_patterns"] = [dict(item) for item in patterns]
    return best
