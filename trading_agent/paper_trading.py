from __future__ import annotations

from .position_manager import PositionState, apply_entry


def generate_paper_orders(decisions: list[dict], rules: dict) -> list[dict]:
    """產生研究用 paper orders；不連券商、不送真實委託。"""
    orders: list[dict] = []
    for item in decisions:
        if item["decision"] != "accept":
            continue
        latest = item["details"]["latest"]
        position = apply_entry(PositionState(symbol=item["symbol"]), float(latest["close"]), rules)
        orders.append({
            "symbol": item["symbol"],
            "side": "paper_buy",
            "fraction": round(position.target_fraction, 4),
            "price": latest["close"],
            "reason": "突破成立先進 1/3 作為試單；此為 paper trading，不是真實下單",
        })
    return orders

