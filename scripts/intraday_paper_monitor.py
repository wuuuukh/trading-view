from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from update_tracking_report import (
    PAPER_INITIAL_CAPITAL,
    ROOT,
    SYMBOL_NAMES,
    build_account_state,
    load_latest_paper_trades,
    read_csv_rows,
    to_float,
    to_int,
)


EVENT_FIELDS = [
    "event_id",
    "date",
    "time",
    "symbol",
    "name",
    "event_type",
    "strategy_type",
    "price",
    "agent_decision",
    "risk_result",
    "simulated_action",
    "shares",
    "action",
    "reason",
    "sop_check",
    "risk_review",
    "improvement",
    "source",
]

TRADE_FIELDS = [
    "trade_id",
    "date",
    "time",
    "symbol",
    "name",
    "side",
    "price",
    "shares",
    "gross_amount",
    "fee_tax",
    "cash_after",
    "position_after",
    "reason",
    "sop_check",
    "hold_days",
    "realized_pnl",
    "unrealized_pnl",
    "notes",
]


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def latest_daily_row(symbol: str) -> dict[str, float | str] | None:
    path = ROOT / "data" / "ohlcv" / f"{symbol}.csv"
    if not path.exists():
        return None
    rows = read_csv_rows(path)
    if not rows:
        return None
    closes = [to_float(row.get("close"), 0.0) or 0.0 for row in rows]
    latest = rows[-1]

    def avg(count: int) -> float | None:
        values = closes[-count:]
        if len(values) < count or any(value <= 0 for value in values):
            return None
        return sum(values) / count

    return {
        "date": str(latest.get("timestamp", "")),
        "close": to_float(latest.get("close"), 0.0) or 0.0,
        "ma3": avg(3) or 0.0,
        "ma8": avg(8) or 0.0,
    }


def load_quotes(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    return {str(row.get("symbol", "")): row for row in read_csv_rows(path) if row.get("symbol")}


def append_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: str(row.get(name, "")) for name in fieldnames})


def next_trade_id(rows: list[dict[str, object]]) -> int:
    max_id = 0
    for row in rows:
        value = str(row.get("trade_id", "")).upper()
        if value.startswith("T"):
            try:
                max_id = max(max_id, int(value[1:]))
            except ValueError:
                pass
    return max_id + 1


def trade_exists(rows: list[dict[str, object]], day: str, symbol: str, action_key: str) -> bool:
    marker = f"intraday_action={action_key}"
    return any(
        str(row.get("date")) == day
        and str(row.get("symbol")) == symbol
        and marker in str(row.get("notes", ""))
        for row in rows
    )


def build_trade_row(
    trade_no: int,
    day: str,
    time_text: str,
    symbol: str,
    side: str,
    price: float,
    shares: int,
    cash_after: float,
    position_after: int,
    realized_pnl: float,
    reason: str,
    sop_check: str,
    action_key: str,
) -> dict[str, object]:
    return {
        "trade_id": f"T{trade_no:03d}",
        "date": day,
        "time": time_text,
        "symbol": symbol,
        "name": SYMBOL_NAMES.get(symbol, symbol),
        "side": side,
        "price": f"{price:.2f}",
        "shares": shares,
        "gross_amount": f"{price * shares:.2f}",
        "fee_tax": "0.00",
        "cash_after": f"{cash_after:.2f}",
        "position_after": position_after,
        "reason": reason,
        "sop_check": sop_check,
        "hold_days": "",
        "realized_pnl": f"{realized_pnl:.2f}",
        "unrealized_pnl": "0.00",
        "notes": f"intraday paper monitor; intraday_action={action_key}; source=operation_events",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run intraday paper-trading monitor once.")
    parser.add_argument("--quotes", default=str(ROOT / "data" / "intraday" / "latest_quotes.csv"))
    parser.add_argument("--execute-paper", action="store_true", help="Write simulated trades when rules trigger.")
    parser.add_argument("--now", default="")
    args = parser.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else datetime.now()
    day = now.date().isoformat()
    time_text = now.strftime("%H:%M")
    plan = load_json(ROOT / "reports" / "next_trading_plan_latest.json")
    paper = load_latest_paper_trades()
    market = {}
    account = build_account_state(paper, market)
    positions = {str(p["symbol"]): p for p in account.get("positions", [])}
    quote_path = Path(args.quotes)
    quotes = load_quotes(quote_path)

    watch_symbols: dict[str, str] = {}
    for p in plan.get("holding_plans", []):
        watch_symbols[str(p.get("symbol"))] = "long_hold"
    for p in plan.get("symbol_plans", []):
        watch_symbols[str(p.get("symbol"))] = "intraday"
    for symbol in positions:
        watch_symbols.setdefault(symbol, "long_hold")

    events: list[dict[str, object]] = []
    new_trades: list[dict[str, object]] = []
    paper_rows = list(paper.get("rows", []))
    trade_no = next_trade_id(paper_rows)
    cash = float(account.get("cash", PAPER_INITIAL_CAPITAL))
    realized_pnl = float(account.get("realized_pnl", 0.0))

    for symbol, strategy_type in sorted(watch_symbols.items()):
        quote = quotes.get(symbol)
        event_base = {
            "event_id": f"{day}-{time_text}-{symbol}",
            "date": day,
            "time": time_text,
            "symbol": symbol,
            "name": SYMBOL_NAMES.get(symbol, symbol),
            "strategy_type": strategy_type,
            "source": str(quote_path),
        }
        if not quote:
            events.append(
                event_base
                | {
                    "event_type": "data_missing",
                    "price": "",
                    "agent_decision": "wait",
                    "risk_result": "blocked",
                    "simulated_action": "none",
                    "shares": 0,
                    "action": "不操作",
                    "reason": "盤中即時報價缺失，禁止自動買賣。",
                    "sop_check": "資料缺失必須明確記錄為 blocked，不能視為沒有訊號。",
                    "risk_review": "這是盤中監控資料源問題，不是策略沒有觸發。",
                    "improvement": "修正即時報價來源；報價正常前只允許觀察。",
                }
            )
            continue

        price = to_float(quote.get("price"), 0.0) or 0.0
        if price <= 0:
            events.append(
                event_base
                | {
                    "event_type": "bad_quote",
                    "price": quote.get("price", ""),
                    "agent_decision": "wait",
                    "risk_result": "blocked",
                    "simulated_action": "none",
                    "shares": 0,
                    "action": "不操作",
                    "reason": "盤中報價不是有效正數。",
                    "sop_check": "價格資料異常時不得交易。",
                    "risk_review": "報價格式或資料源需檢查。",
                    "improvement": "修正 quote 欄位 price。",
                }
            )
            continue

        position = positions.get(symbol)
        daily = latest_daily_row(symbol)
        ma3 = float((daily or {}).get("ma3") or 0.0)
        ma8 = float((daily or {}).get("ma8") or 0.0)
        action_key = "wait"
        decision = "wait"
        action = "等待"
        risk_result = "approved"
        shares = 0
        reason = "尚未觸發盤中買賣條件。"
        sop_check = f"price {price:.2f}; daily 3MA {ma3:.2f}; daily 8MA {ma8:.2f}"

        if position and int(position.get("shares", 0)) > 0:
            current_shares = int(position["shares"])
            cost = float(position.get("cost_basis") or 0.0)
            stop = cost * 0.97
            if ma8 and (price < ma8 or price <= stop):
                decision = "exit"
                action_key = "intraday_exit"
                shares = current_shares
                action = f"賣出 {shares} 股"
                reason = "盤中跌破日K 8MA 或觸發 3% 停損，紙上交易全出。"
            elif ma3 and price < ma3:
                decision = "reduce"
                action_key = "intraday_reduce_3ma"
                shares = max(1, current_shares // 2)
                action = f"賣出 {shares} 股"
                reason = "盤中跌破日K 3MA，紙上交易先出 1/2。"
        else:
            risk_result = "blocked"
            reason = "目前缺少 5K / 60K 即時確認資料，候選股不得自動買進。"
            sop_check = "進場需要 5K 切入點與 60K MACD；資料未接上時只能 blocked。"

        if args.execute_paper and shares > 0 and decision in {"reduce", "exit"} and not trade_exists(paper_rows, day, symbol, action_key):
            position_after = max(0, int((position or {}).get("shares", 0)) - shares)
            cost = float((position or {}).get("cost_basis") or price)
            realized_pnl += (price - cost) * shares
            cash += price * shares
            trade = build_trade_row(
                trade_no,
                day,
                time_text,
                symbol,
                "sell",
                price,
                shares,
                cash,
                position_after,
                realized_pnl,
                reason,
                sop_check,
                action_key,
            )
            new_trades.append(trade)
            paper_rows.append(trade)
            trade_no += 1
            simulated_action = "sell"
        else:
            simulated_action = "none" if shares == 0 else ("duplicate_skipped" if trade_exists(paper_rows, day, symbol, action_key) else "paper_disabled")

        events.append(
            event_base
            | {
                "event_type": "intraday_check",
                "price": f"{price:.2f}",
                "agent_decision": decision,
                "risk_result": risk_result,
                "simulated_action": simulated_action,
                "shares": shares,
                "action": action,
                "reason": reason,
                "sop_check": sop_check,
                "risk_review": "盤中監控即時事件，優先於盤後復盤。",
                "improvement": "若此事件未成交，檢查是否因資料缺失、重複交易保護或未啟用 paper execution。",
            }
        )

    event_path = ROOT / "reports" / f"operation_events_{day}.csv"
    append_csv(event_path, EVENT_FIELDS, events)

    if new_trades:
        source = str(paper.get("source_file") or f"paper_trade_{day}.csv")
        trade_path = ROOT / "reports" / source
        append_csv(trade_path, TRADE_FIELDS, new_trades)

    print(f"wrote {len(events)} operation events to {event_path}")
    print(f"wrote {len(new_trades)} paper trades")


if __name__ == "__main__":
    main()
