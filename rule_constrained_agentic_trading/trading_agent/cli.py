from __future__ import annotations

import argparse
from pathlib import Path

from .backtest import compare_baseline_vs_agent
from .candidate_scanner import scan_candidates
from .chip_loader import load_shareholder_csv, score_shareholders
from .config import load_rules
from .data_loader import load_ohlcv_folder
from .paper_trading import generate_paper_orders
from .reporter import write_reports


def load_chip_scores(chip_path: str | None, rules: dict):
    if not chip_path:
        return {}
    return score_shareholders(load_shareholder_csv(chip_path), rules)


def cmd_scan(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    ohlcv = load_ohlcv_folder(args.ohlcv)
    chips = load_chip_scores(args.chip, rules)
    decisions = scan_candidates(ohlcv, chips, rules)
    paths = write_reports(decisions, args.out, "scan")
    print(f"scan 完成: {paths}")


def cmd_backtest(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    ohlcv = load_ohlcv_folder(args.ohlcv)
    chips = load_chip_scores(args.chip, rules)
    rows = [compare_baseline_vs_agent(symbol, df, rules, chips.get(symbol)) for symbol, df in ohlcv.items()]
    paths = write_reports([{"symbol": r["symbol"], "decision": r["agent_decision"], "score": r.get("agent_score", 0), "tier": r.get("agent_tier", "n/a"), "reason": r["reason"], "market_state": "n/a", "pattern_type": "n/a", "risk_note": "baseline vs agent 研究比較", "details": r} for r in rows], args.out, "backtest_compare")
    print(f"backtest compare 完成: {paths}")


def cmd_paper(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    ohlcv = load_ohlcv_folder(args.ohlcv)
    chips = load_chip_scores(args.chip, rules)
    decisions = scan_candidates(ohlcv, chips, rules)
    orders = generate_paper_orders(decisions, rules)
    paths = write_reports(decisions, args.out, "paper_scan")
    orders_path = Path(args.out) / "paper_orders.json"
    orders_path.write_text(__import__("json").dumps(orders, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"paper trading 研究輸出完成: {paths}, orders={orders_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rule-constrained AI Agent Trading System")
    parser.add_argument("--rules", default="config/rules.yaml")
    sub = parser.add_subparsers(required=True)
    for name, fn in [("scan", cmd_scan), ("backtest", cmd_backtest), ("paper", cmd_paper)]:
        p = sub.add_parser(name)
        p.add_argument("--ohlcv", required=True)
        p.add_argument("--chip")
        p.add_argument("--out", default="reports")
        p.set_defaults(func=fn)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

