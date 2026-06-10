from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .candidate_scanner import build_candidate
from .ai_agent import RuleConstrainedAgent
from .data_loader import load_ohlcv_folder


@dataclass
class SimPosition:
    symbol: str
    shares: int
    average_price: float


@dataclass
class SimulationState:
    cash: float
    positions: dict[str, SimPosition] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)


def _trade_dates(ohlcv_map: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for df in ohlcv_map.values():
        if df.empty:
            continue
        series = pd.to_datetime(df["timestamp"]).dt.normalize()
        for value in series[(series >= start) & (series <= end)]:
            dates.add(pd.Timestamp(value))
    return sorted(dates)


def _latest_price_on_or_before(df: pd.DataFrame, date: pd.Timestamp) -> float | None:
    eligible = df[pd.to_datetime(df["timestamp"]).dt.normalize() <= date]
    if eligible.empty:
        return None
    return float(eligible.iloc[-1]["close"])


def _market_value(state: SimulationState, ohlcv_map: dict[str, pd.DataFrame], date: pd.Timestamp) -> float:
    value = 0.0
    for symbol, position in state.positions.items():
        price = _latest_price_on_or_before(ohlcv_map[symbol], date)
        if price is None:
            continue
        value += position.shares * price
    return value


def _max_drawdown(equity_curve: list[dict[str, Any]]) -> float:
    peak = 0.0
    max_dd = 0.0
    for row in equity_curve:
        equity = float(row["total_equity"])
        peak = max(peak, equity)
        if peak:
            max_dd = min(max_dd, equity / peak - 1)
    return round(max_dd * 100, 2)


def _decision_for_day(symbol: str, df: pd.DataFrame, rules: dict[str, Any], date: pd.Timestamp) -> dict[str, Any] | None:
    history = df[pd.to_datetime(df["timestamp"]).dt.normalize() <= date].copy()
    if len(history) < 25:
        return None
    candidate = build_candidate(symbol, history, rules, chip=None)
    decision = RuleConstrainedAgent(rules).evaluate(candidate)
    return asdict(decision)


def _default_weekly_scanner(
    symbol: str,
    history: pd.DataFrame,
    rules: dict[str, Any],
    scan_date: pd.Timestamp,
) -> dict[str, Any] | None:
    del scan_date
    if len(history) < 25:
        return None
    candidate = build_candidate(symbol, history, rules, chip=None)
    return asdict(RuleConstrainedAgent(rules).evaluate(candidate))


def _sundays(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    first = start + pd.Timedelta(days=(6 - start.weekday()) % 7)
    result: list[pd.Timestamp] = []
    current = first.normalize()
    while current <= end:
        result.append(current)
        current += pd.Timedelta(days=7)
    return result


def _next_trade_date_after(
    ohlcv_map: dict[str, pd.DataFrame],
    symbol: str,
    scan_date: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.Timestamp | None:
    df = ohlcv_map[symbol]
    dates = pd.to_datetime(df["timestamp"]).dt.normalize()
    eligible = sorted(set(dates[(dates > scan_date) & (dates <= end)]))
    return pd.Timestamp(eligible[0]) if eligible else None


def run_historical_simulation(
    *,
    ohlcv_map: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    start: str,
    end: str,
    initial_capital: float = 10_000.0,
) -> dict[str, Any]:
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    state = SimulationState(cash=float(initial_capital))
    agent = RuleConstrainedAgent(rules)
    del agent  # Keeps the dependency explicit; daily decisions are produced in _decision_for_day.

    for date in _trade_dates(ohlcv_map, start_ts, end_ts):
        day_decisions: list[dict[str, Any]] = []
        for symbol, df in sorted(ohlcv_map.items()):
            decision = _decision_for_day(symbol, df, rules, date)
            if decision is not None:
                day_decisions.append(decision)

        day_decisions.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)

        for decision in day_decisions:
            symbol = str(decision["symbol"])
            if decision["decision"] != "accept":
                continue
            if symbol in state.positions:
                continue
            price = _latest_price_on_or_before(ohlcv_map[symbol], date)
            if price is None or price <= 0:
                continue
            budget = state.cash * float(rules.get("risk", {}).get("first_entry_fraction", 0.3333))
            shares = int(budget // price)
            if shares <= 0:
                continue
            cost = shares * price
            state.cash -= cost
            state.positions[symbol] = SimPosition(symbol=symbol, shares=shares, average_price=price)
            state.trades.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "symbol": symbol,
                    "side": "buy",
                    "price": round(price, 2),
                    "shares": shares,
                    "amount": round(cost, 2),
                    "cash_after": round(state.cash, 2),
                    "reason": decision.get("reason", ""),
                    "score": decision.get("score"),
                    "tier": decision.get("tier"),
                }
            )

        market_value = _market_value(state, ohlcv_map, date)
        total_equity = state.cash + market_value
        state.equity_curve.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "cash": round(state.cash, 2),
                "position_value": round(market_value, 2),
                "total_equity": round(total_equity, 2),
                "open_positions": len(state.positions),
            }
        )

    final_equity = state.equity_curve[-1]["total_equity"] if state.equity_curve else initial_capital
    unrealized = float(final_equity) - state.cash - sum(
        position.shares * position.average_price for position in state.positions.values()
    )
    summary = {
        "start": start,
        "end": end,
        "initial_capital": round(float(initial_capital), 2),
        "final_equity": round(float(final_equity), 2),
        "total_return_pct": round((float(final_equity) / float(initial_capital) - 1) * 100, 2)
        if initial_capital
        else 0.0,
        "cash": round(state.cash, 2),
        "open_positions": {symbol: asdict(position) for symbol, position in state.positions.items()},
        "trade_count": len(state.trades),
        "realized_pnl": 0.0,
        "unrealized_pnl": round(unrealized, 2),
        "max_drawdown_pct": _max_drawdown(state.equity_curve),
        "limitations": [
            "daily-level simulation only",
            "index data not applied unless added later",
            "5K/15K/60K/VWAP intraday execution not available",
            "formal chip and institution data not applied",
        ],
    }
    return {"summary": summary, "trades": state.trades, "equity_curve": state.equity_curve}


def run_weekly_sunday_replay(
    *,
    ohlcv_map: dict[str, pd.DataFrame],
    rules: dict[str, Any],
    start: str,
    end: str,
    initial_capital: float = 10_000.0,
    scanner: Any | None = None,
) -> dict[str, Any]:
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    scan_fn = scanner or _default_weekly_scanner
    state = SimulationState(cash=float(initial_capital))
    weekly_scans: list[dict[str, Any]] = []

    for scan_date in _sundays(start_ts, end_ts):
        day_decisions: list[dict[str, Any]] = []
        for symbol, df in sorted(ohlcv_map.items()):
            history = df[pd.to_datetime(df["timestamp"]).dt.normalize() <= scan_date].copy()
            if history.empty:
                continue
            decision = scan_fn(symbol, history, rules, scan_date)
            if decision is not None:
                day_decisions.append(decision)

        day_decisions.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        weekly_scans.append(
            {
                "scan_date": scan_date.strftime("%Y-%m-%d"),
                "candidate_count": len(day_decisions),
                "accept_count": sum(1 for item in day_decisions if item.get("decision") == "accept"),
                "hold_count": sum(1 for item in day_decisions if item.get("decision") == "hold"),
                "reject_count": sum(1 for item in day_decisions if item.get("decision") == "reject"),
                "top_candidates": [
                    {
                        "symbol": str(item.get("symbol")),
                        "decision": item.get("decision"),
                        "tier": item.get("tier"),
                        "score": item.get("score"),
                        "reason": item.get("reason", ""),
                    }
                    for item in day_decisions[:10]
                ],
            }
        )

        for decision in day_decisions:
            symbol = str(decision["symbol"])
            if decision.get("decision") != "accept" or symbol in state.positions:
                continue
            trade_date = _next_trade_date_after(ohlcv_map, symbol, scan_date, end_ts)
            if trade_date is None:
                continue
            price = _latest_price_on_or_before(ohlcv_map[symbol], trade_date)
            if price is None or price <= 0:
                continue
            budget = state.cash * float(rules.get("risk", {}).get("first_entry_fraction", 0.3333))
            shares = int(budget // price)
            if shares <= 0:
                continue
            cost = shares * price
            state.cash -= cost
            state.positions[symbol] = SimPosition(symbol=symbol, shares=shares, average_price=price)
            state.trades.append(
                {
                    "date": trade_date.strftime("%Y-%m-%d"),
                    "scan_date": scan_date.strftime("%Y-%m-%d"),
                    "symbol": symbol,
                    "side": "buy",
                    "price": round(price, 2),
                    "shares": shares,
                    "amount": round(cost, 2),
                    "cash_after": round(state.cash, 2),
                    "reason": decision.get("reason", ""),
                    "score": decision.get("score"),
                    "tier": decision.get("tier"),
                }
            )

    for date in _trade_dates(ohlcv_map, start_ts, end_ts):
        market_value = _market_value(state, ohlcv_map, date)
        total_equity = state.cash + market_value
        state.equity_curve.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "cash": round(state.cash, 2),
                "position_value": round(market_value, 2),
                "total_equity": round(total_equity, 2),
                "open_positions": len(state.positions),
            }
        )

    final_equity = state.equity_curve[-1]["total_equity"] if state.equity_curve else initial_capital
    unrealized = float(final_equity) - state.cash - sum(
        position.shares * position.average_price for position in state.positions.values()
    )
    summary = {
        "mode": "weekly_sunday_replay",
        "start": start,
        "end": end,
        "initial_capital": round(float(initial_capital), 2),
        "final_equity": round(float(final_equity), 2),
        "total_return_pct": round((float(final_equity) / float(initial_capital) - 1) * 100, 2)
        if initial_capital
        else 0.0,
        "cash": round(state.cash, 2),
        "open_positions": {symbol: asdict(position) for symbol, position in state.positions.items()},
        "trade_count": len(state.trades),
        "scan_count": len(weekly_scans),
        "realized_pnl": 0.0,
        "unrealized_pnl": round(unrealized, 2),
        "max_drawdown_pct": _max_drawdown(state.equity_curve),
        "limitations": [
            "weekly Sunday replay; each scan uses only data on or before that Sunday",
            "daily-level simulation only",
            "buy execution uses the next available trading day's close",
            "sell/rotation execution is not added because current rules do not define a complete historical exit engine",
            "5K/15K/60K/VWAP intraday execution not available",
            "formal chip and institution data not applied",
        ],
    }
    return {
        "summary": summary,
        "weekly_scans": weekly_scans,
        "trades": state.trades,
        "equity_curve": state.equity_curve,
    }


def write_historical_simulation_reports(result: dict[str, Any], out_prefix: str | Path) -> dict[str, str]:
    prefix = Path(out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    md_path = prefix.with_suffix(".md")

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["date", "cash", "position_value", "total_equity", "open_positions"],
        )
        writer.writeheader()
        writer.writerows(result["equity_curve"])

    summary = result["summary"]
    lines = [
        "# Historical Simulation",
        "",
        f"- period: {summary['start']} to {summary['end']}",
        f"- initial_capital: {summary['initial_capital']}",
        f"- final_equity: {summary['final_equity']}",
        f"- total_return_pct: {summary['total_return_pct']}%",
        f"- trade_count: {summary['trade_count']}",
        f"- scan_count: {summary.get('scan_count', 0)}",
        f"- max_drawdown_pct: {summary['max_drawdown_pct']}%",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in summary["limitations"])
    lines.extend(["", "## Trades", ""])
    if result["trades"]:
        lines.append("| date | symbol | side | price | shares | amount |")
        lines.append("|---|---:|---|---:|---:|---:|")
        for trade in result["trades"]:
            lines.append(
                f"| {trade['date']} | {trade['symbol']} | {trade['side']} | "
                f"{trade['price']} | {trade['shares']} | {trade['amount']} |"
            )
    else:
        lines.append("No trades were generated by the current conservative rules.")
    if result.get("weekly_scans"):
        lines.extend(["", "## Weekly Sunday Scans", ""])
        lines.append("| scan_date | candidates | accept | hold | reject | top_candidate |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for scan in result["weekly_scans"]:
            top = scan.get("top_candidates") or []
            top_text = ""
            if top:
                first = top[0]
                top_text = f"{first.get('symbol')} / {first.get('decision')} / {first.get('score')}"
            lines.append(
                f"| {scan['scan_date']} | {scan['candidate_count']} | {scan['accept_count']} | "
                f"{scan['hold_count']} | {scan['reject_count']} | {top_text} |"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"json": str(json_path), "csv": str(csv_path), "md": str(md_path)}


def run_historical_simulation_from_folder(
    *,
    ohlcv_folder: str | Path,
    rules: dict[str, Any],
    start: str,
    end: str,
    initial_capital: float = 10_000.0,
) -> dict[str, Any]:
    return run_historical_simulation(
        ohlcv_map=load_ohlcv_folder(ohlcv_folder),
        rules=rules,
        start=start,
        end=end,
        initial_capital=initial_capital,
    )


def run_weekly_sunday_replay_from_folder(
    *,
    ohlcv_folder: str | Path,
    rules: dict[str, Any],
    start: str,
    end: str,
    initial_capital: float = 10_000.0,
) -> dict[str, Any]:
    return run_weekly_sunday_replay(
        ohlcv_map=load_ohlcv_folder(ohlcv_folder),
        rules=rules,
        start=start,
        end=end,
        initial_capital=initial_capital,
    )
