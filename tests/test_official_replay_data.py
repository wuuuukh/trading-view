from __future__ import annotations

import unittest

from scripts.update_official_replay_data import is_common_stock_code, parse_number, parse_roc_date


class OfficialReplayDataTest(unittest.TestCase):
    def test_parse_number_handles_commas_and_empty_values(self) -> None:
        self.assertEqual(parse_number("1,234,567"), 1234567)
        self.assertEqual(parse_number("--"), 0)
        self.assertEqual(parse_number(""), 0)

    def test_parse_roc_date_handles_common_official_formats(self) -> None:
        self.assertEqual(parse_roc_date("115/01/05"), "2026-01-05")
        self.assertEqual(parse_roc_date("1150105"), "2026-01-05")
        self.assertEqual(parse_roc_date("20260105"), "2026-01-05")

    def test_common_stock_code_excludes_etf_and_bond_like_codes(self) -> None:
        self.assertTrue(is_common_stock_code("2330"))
        self.assertFalse(is_common_stock_code("006201"))
        self.assertFalse(is_common_stock_code("00679B"))

    def test_tdcc_date_format_is_normalized(self) -> None:
        self.assertEqual(parse_roc_date("20260529"), "2026-05-29")


if __name__ == "__main__":
    unittest.main()
