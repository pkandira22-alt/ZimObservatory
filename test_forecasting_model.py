import urllib.error
import unittest
from unittest.mock import Mock, patch

from forecasting_model import (
    _forecast_gold_target,
    _rolling_backtest,
    build_forecast_report,
    fetch_gold_monthly_series,
    fetch_zimstat_monthly_inflation,
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

    @patch("forecasting_model._request_json")
    def test_gold_fetch_retries_second_chart_host_after_rate_limit(self, request_json):
        rate_limited = urllib.error.HTTPError(
            "https://query1.finance.yahoo.com", 429, "Too Many Requests", {}, None
        )
        request_json.side_effect = [
            rate_limited,
            {
                "chart": {
                    "result": [{
                        "timestamp": [1761955200],
                        "indicators": {"quote": [{"close": [4000.0]}]},
                    }]
                }
            },
        ]

        observations = fetch_gold_monthly_series()

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0][1], 4000.0)
        self.assertIn("query2.finance.yahoo.com", request_json.call_args.args[0])
        rate_limited.close()

    @patch("forecasting_model._request_bytes", return_value=b"workbook")
    @patch("forecasting_model.xlrd.open_workbook")
    def test_zimstat_workbook_reader_extracts_dated_monthly_all_items_rates(
        self, open_workbook, _request_bytes
    ):
        values = {
            (2, 14): "All Items",
            (2, 15): "Inflation Rate (%) Monthly",
            (3, 0): 2026,
            (3, 1): "September",
            (3, 15): 0.12,
            (4, 1): "October",
            (4, 15): 0.15,
        }
        sheet = Mock(nrows=5, ncols=16)
        sheet.cell_value.side_effect = lambda row, col: values.get((row, col), "")
        workbook = Mock()
        workbook.sheet_by_name.return_value = sheet
        open_workbook.return_value = workbook

        observations, source_url = fetch_zimstat_monthly_inflation()

        self.assertEqual(observations, [("2026-09", 0.12), ("2026-10", 0.15)])
        self.assertIn("CPI_Weighted_", source_url)

    @patch("forecasting_model.fetch_gold_monthly_series")
    @patch("forecasting_model.fetch_world_bank_series")
    @patch("forecasting_model.fetch_zimstat_monthly_inflation")
    def test_report_includes_all_requested_targets_and_abstains_without_data(
        self, fetch_zimstat, fetch_world_bank, fetch_gold
    ):
        fetch_world_bank.side_effect = [
            ([(year, float(year - 1960)) for year in range(1961, 2026)], "2026-10-08"),
        ]
        fetch_zimstat.return_value = (
            [
                (f"{2024 + (3 + index) // 12:04d}-{(3 + index) % 12 + 1:02d}", index / 10)
                for index in range(31)
            ],
            "https://www.zimstat.co.zw/CPI_Weighted_10_2026.xls",
        )
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
        self.assertEqual(targets["inflation"]["observedThrough"], "2026-10")
        self.assertEqual(targets["inflation"]["unit"], "% monthly")
        self.assertEqual(targets["inflation"]["status"], "validated_candidate")
        self.assertEqual(targets["protests"]["status"], "unavailable")
        self.assertEqual(targets["phi"]["status"], "unavailable")
        self.assertEqual(targets["other"]["status"], "not_requested")


if __name__ == "__main__":
    unittest.main()
