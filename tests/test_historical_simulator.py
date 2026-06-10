from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from trading_agent.historical_simulator import (
    run_historical_simulation,
    run_weekly_sunday_replay,
    write_historical_simulation_reports,
)


def make_daily_ohlcv(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2025-12-01", periods=rows, freq="B")
    close = [40 + i * 0.4 for i in range(rows)]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": [price + 0.8 for price in close],
            "low": [price - 0.8 for price in close],
            "close": close,
            "volume": [800_000] * rows,
        }
    )


class HistoricalSimulatorTest(unittest.TestCase):
    def test_simulation_uses_requested_capital_and_period(self) -> None:
        result = run_historical_simulation(
            ohlcv_map={"2330": make_daily_ohlcv()},
            rules={
                "scanner": {
                    "min_daily_volume_shares": 500_000,
                    "min_volume_ratio_breakout": 1.2,
                    "primary_min_score": 75,
                    "secondary_min_score": 55,
                },
                "agent_weights": {
                    "trend_structure": 25,
                    "moving_average_alignment": 25,
                    "pattern_quality": 20,
                    "volume_price": 15,
                    "chip": 15,
                },
                "risk": {"first_entry_fraction": 0.3333},
            },
            start="2026-01-01",
            end="2026-01-31",
            initial_capital=10_000,
        )

        self.assertEqual(result["summary"]["initial_capital"], 10_000)
        self.assertEqual(result["summary"]["start"], "2026-01-01")
        self.assertEqual(result["summary"]["end"], "2026-01-31")
        self.assertGreater(len(result["equity_curve"]), 0)
        self.assertIn("trade_count", result["summary"])

    def test_report_writer_creates_independent_outputs(self) -> None:
        result = {
            "summary": {
                "start": "2026-01-01",
                "end": "2026-05-31",
                "initial_capital": 10_000,
                "final_equity": 10_100,
                "total_return_pct": 1.0,
                "trade_count": 1,
                "max_drawdown_pct": -0.5,
                "limitations": ["daily-level simulation only"],
            },
            "trades": [
                {"date": "2026-01-05", "symbol": "2330", "side": "buy", "price": 100, "shares": 10, "amount": 1000}
            ],
            "equity_curve": [
                {"date": "2026-01-05", "cash": 9000, "position_value": 1000, "total_equity": 10000, "open_positions": 1}
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = write_historical_simulation_reports(result, Path(tmpdir) / "historical_simulation_test")

            self.assertTrue(Path(paths["json"]).exists())
            self.assertTrue(Path(paths["csv"]).exists())
            self.assertTrue(Path(paths["md"]).exists())

    def test_weekly_sunday_replay_uses_only_past_data(self) -> None:
        seen_cutoffs: list[pd.Timestamp] = []

        def scanner(symbol, history, rules, scan_date):
            seen_cutoffs.append(pd.to_datetime(history["timestamp"]).max().normalize())
            self.assertLessEqual(seen_cutoffs[-1], pd.Timestamp(scan_date).normalize())
            return {
                "symbol": symbol,
                "decision": "accept",
                "score": 88,
                "tier": "primary_review",
                "reason": "test scanner",
            }

        result = run_weekly_sunday_replay(
            ohlcv_map={"2330": make_daily_ohlcv(180)},
            rules={"risk": {"first_entry_fraction": 0.5}},
            start="2026-01-04",
            end="2026-01-18",
            initial_capital=10_000,
            scanner=scanner,
        )

        self.assertEqual([row["scan_date"] for row in result["weekly_scans"]], ["2026-01-04", "2026-01-11", "2026-01-18"])
        self.assertGreater(len(result["trades"]), 0)
        self.assertTrue(all(pd.Timestamp(trade["date"]) > pd.Timestamp("2026-01-04") for trade in result["trades"]))


if __name__ == "__main__":
    unittest.main()
