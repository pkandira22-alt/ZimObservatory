import unittest
from datetime import datetime, timezone

from prescriptive_orientation import evaluate_orientation


class PrescriptiveOrientationTests(unittest.TestCase):
    def test_selects_each_orientation_for_its_extreme_input_profile(self):
        cases = (
            (
                {
                    "regime_durability_index": 0,
                    "realized_praxis_yield": 100,
                    "parallel_fx_premium": 100,
                    "coercive_load": 0,
                },
                "decentralized_mutual_aid",
            ),
            (
                {
                    "regime_durability_index": 100,
                    "realized_praxis_yield": 100,
                    "parallel_fx_premium": 0,
                    "coercive_load": 0,
                },
                "structural_negotiation",
            ),
            (
                {
                    "regime_durability_index": 0,
                    "realized_praxis_yield": 0,
                    "parallel_fx_premium": 100,
                    "coercive_load": 100,
                },
                "defensive_consolidation",
            ),
        )
        for inputs, expected in cases:
            with self.subTest(expected=expected):
                result = evaluate_orientation({"orientationInputs": inputs})
                self.assertEqual(result["status"], "evaluated")
                self.assertEqual(result["selectedOrientation"], expected)
                self.assertEqual(result["orientationIndex"], result["scores"][expected])

    def test_abstains_when_inputs_are_missing_or_incomplete(self):
        missing = evaluate_orientation({})
        incomplete = evaluate_orientation({
            "orientationInputs": {"regime_durability_index": 20}
        })

        self.assertEqual(missing["status"], "awaiting_inputs")
        self.assertEqual(len(missing["missingInputs"]), 4)
        self.assertEqual(incomplete["missingInputs"], [
            "realized_praxis_yield",
            "parallel_fx_premium",
            "coercive_load",
        ])
        self.assertNotIn("selectedOrientation", incomplete)

    def test_ties_follow_the_documented_orientation_order(self):
        result = evaluate_orientation({
            "orientationInputs": {
                "regime_durability_index": 50,
                "realized_praxis_yield": 50,
                "parallel_fx_premium": 50,
                "coercive_load": 50,
            }
        })

        self.assertEqual(set(result["scores"].values()), {50.0})
        self.assertEqual(result["selectedOrientation"], "decentralized_mutual_aid")

    def test_rejects_non_numeric_boolean_non_finite_and_out_of_range_values(self):
        base = {
            "regime_durability_index": 20,
            "realized_praxis_yield": 50,
            "parallel_fx_premium": 50,
            "coercive_load": 20,
        }
        for bad_value in ("high", True, float("nan"), float("inf"), -1, 101):
            with self.subTest(value=bad_value):
                inputs = {**base, "coercive_load": bad_value}
                result = evaluate_orientation({"orientationInputs": inputs})
                self.assertEqual(result["status"], "invalid_inputs")
                self.assertEqual(result["invalidInputs"], ["coercive_load"])
                self.assertNotIn("selectedOrientation", result)

    def test_timestamp_is_normalized_to_utc(self):
        result = evaluate_orientation({}, datetime(2026, 11, 10, tzinfo=timezone.utc))
        self.assertEqual(result["evaluatedAt"], "2026-11-10T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
