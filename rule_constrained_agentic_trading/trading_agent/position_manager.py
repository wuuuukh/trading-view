from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionState:
    symbol: str
    target_fraction: float = 0.0
    entry_count: int = 0
    average_price: float = 0.0


def next_entry_fraction(position: PositionState, rules: dict) -> float:
    """分批進場：突破試單、回踩不破加碼、再創新高加最後一筆。"""
    risk = rules.get("risk", {})
    steps = [
        float(risk.get("first_entry_fraction", 0.3333)),
        float(risk.get("second_entry_fraction", 0.3333)),
        float(risk.get("third_entry_fraction", 0.3334)),
    ]
    if position.entry_count >= len(steps):
        return 0.0
    return steps[position.entry_count]


def apply_entry(position: PositionState, price: float, rules: dict) -> PositionState:
    fraction = next_entry_fraction(position, rules)
    if fraction <= 0:
        return position
    new_target = position.target_fraction + fraction
    if position.target_fraction == 0:
        avg = price
    else:
        avg = (position.average_price * position.target_fraction + price * fraction) / new_target
    position.target_fraction = min(1.0, new_target)
    position.entry_count += 1
    position.average_price = avg
    return position

