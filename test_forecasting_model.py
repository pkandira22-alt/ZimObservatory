import unittest
from unittest.mock import patch

from forecasting_model import (
    _forecast_gold_target,
    _rolling_backtest,
    build_forecast_report,
)


class RollingBacktestTests(unittest.TestCase):
    def test_selects_a_candidate_that_beats_persistence(self):
        values = [float(index) for index in range(80)]
        result = _rolling_backtest(
            values,
            ("last_value", "mean_5", "drift_5"),
            horizon=1,
            min_train=15,
            holdout_count=10,
        )
        self.assertEqual(result["status"], "skill_over_naive")
        self.assertEqual(result["selectedMethod"], "drift_5")
        self.assertGreater(result["skillVsNaive"], 0)
        self.assertFalse(result["holdoutOriginsOverlap"])

    def test_refuses_to_score_insufficient_history(self):
        result = _rolling_backtest(
            [1.0, 2.0, 3.0],
            ("last_value", "mean_5"),
            horizon=1,
            min_train=15,
            holdout_count=10,
        )
        self.assertEqual(result["status"], "insufficient_history")

    @patch("forecasting_model.fetch_gold_monthly_series")
    def test_overlapping_gold_holdout_is_labeled_provisional(self, fetch_series):
        fetch_series.return_value = [
            (f"{2015 + index // 12:04d}-{(index % 12) + 1:02d}", float(index))
            for index in range(100)
        ]
        result = _forecast_gold_target()
        self.assertEqual(result["status"], "provisional_candidate")
        self.assertEqual(result["forecast"]["method"], "drift_12")
        self.assertTrue(result["backtest"]["holdoutOriginsOverlap"])
        self.assertIn("provisional", result["reason"])

    @patch("forecasting_model.fetch_gold_monthly_series")
    @patch("forecasting_model.fetch_world_bank_series")
    def test_report_includes_all_requested_targets_and_abstains_without_data(
        self, fetch_world_bank, fetch_gold
    ):
        fetch_world_bank.side_effect = [
            ([(year, float(year - 1960)) for year in range(1961, 2026)], "2026-10-08"),
            ([(year, float(year)) for year in range(2010, 2023)], "2026-10-08"),
        ]
        fetch_gold.return_value = [
            (f"{2015 + index // 12:04d}-{(index % 12) + 1:02d}", float(index))
            for index in range(100)
        ]

        report = build_forecast_report()
        targets = {target["id"]: target for target in report["targets"]}

        self.assertEqual(
            set(targets),
            {"gdp", "inflation", "gold", "protests", "phi", "other"},
        )
        self.assertEqual(targets["inflation"]["status"], "stale_data")
        self.assertEqual(targets["protests"]["status"], "unavailable")
        self.assertEqual(targets["phi"]["status"], "unavailable")
        self.assertEqual(targets["other"]["status"], "not_requested")


if __name__ == "__main__":
    unittest.main()
