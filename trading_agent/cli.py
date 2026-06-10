from __future__ import annotations

import argparse
import json
from pathlib import Path

from .backtest import compare_baseline_vs_agent
from .candidate_scanner import scan_candidates
from .chip_loader import load_shareholder_csv, score_shareholders
from .config import load_rules
from .data_loader import load_ohlcv_csv, load_ohlcv_folder
from .historical_simulator import (
    run_historical_simulation_from_folder,
    run_weekly_sunday_replay_from_folder,
    write_historical_simulation_reports,
)
from .index_agent import evaluate_index_market_from_csv
from .orchestrator import evaluate_multi_agent_pipeline
from .paper_trading import generate_paper_orders
from .projection import build_next_week_projection, load_watchlist, write_projection_reports
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


def cmd_project(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    watchlist = load_watchlist(args.watchlist)
    projection = build_next_week_projection(watchlist, rules, args.capital)
    paths = write_projection_reports(projection, args.out, "next_week_projection")
    print(f"next week projection 完成: {paths}")


def cmd_index(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    decision = evaluate_index_market_from_csv(
        args.daily,
        rules,
        weekly_path=args.weekly,
        monthly_path=args.monthly,
        k60_path=args.k60,
        intraday_path=args.intraday,
        daily_change_pct=args.change_pct,
    )
    payload = json.dumps(decision, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(f"index agent output: {out_path}")
    else:
        print(payload)


def cmd_multiagent(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    index_daily = load_ohlcv_csv(args.index_daily)
    stocks = load_ohlcv_folder(args.ohlcv)
    chips = load_chip_scores(args.chip, rules)
    result = evaluate_multi_agent_pipeline(
        index_daily=index_daily,
        stock_daily_map=stocks,
        rules=rules,
        chip_scores=chips,
        daily_change_pct=args.change_pct,
    )
    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")
    print(f"multi-agent output: {out_path}")


def cmd_simulate(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    result = run_historical_simulation_from_folder(
        ohlcv_folder=args.ohlcv,
        rules=rules,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
    )
    out_prefix = args.out or f"reports/historical_simulation_{args.start}_to_{args.end}"
    paths = write_historical_simulation_reports(result, out_prefix)
    print(f"historical simulation output: {paths}")


def cmd_simulate_weekly(args: argparse.Namespace) -> None:
    rules = load_rules(args.rules)
    result = run_weekly_sunday_replay_from_folder(
        ohlcv_folder=args.ohlcv,
        rules=rules,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
    )
    out_prefix = args.out or f"reports/weekly_sunday_replay_{args.start}_to_{args.end}"
    paths = write_historical_simulation_reports(result, out_prefix)
    print(f"weekly Sunday replay output: {paths}")


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
    p = sub.add_parser("project")
    p.add_argument("--watchlist", default="config/next_week_watchlist.yaml")
    p.add_argument("--capital", type=float, default=None)
    p.add_argument("--out", default="reports")
    p.set_defaults(func=cmd_project)
    p = sub.add_parser("index")
    p.add_argument("--daily", required=True)
    p.add_argument("--weekly")
    p.add_argument("--monthly")
    p.add_argument("--k60")
    p.add_argument("--intraday")
    p.add_argument("--change-pct", type=float, default=None, help="Daily index change, accepts -3.2 or -0.032")
    p.add_argument("--out")
    p.set_defaults(func=cmd_index)
    p = sub.add_parser("multiagent")
    p.add_argument("--index-daily", required=True)
    p.add_argument("--ohlcv", required=True)
    p.add_argument("--chip")
    p.add_argument("--change-pct", type=float, default=None, help="Daily index change, accepts -3.2 or -0.032")
    p.add_argument("--out", default="reports/multi_agent_latest.json")
    p.set_defaults(func=cmd_multiagent)
    p = sub.add_parser("simulate")
    p.add_argument("--ohlcv", default="data/ohlcv")
    p.add_argument("--start", default="2026-01-01")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--out")
    p.set_defaults(func=cmd_simulate)
    p = sub.add_parser("simulate-weekly")
    p.add_argument("--ohlcv", default="data/ohlcv")
    p.add_argument("--start", default="2026-01-04")
    p.add_argument("--end", default="2026-05-31")
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--out")
    p.set_defaults(func=cmd_simulate_weekly)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
