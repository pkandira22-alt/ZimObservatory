#!/usr/bin/env python3
"""Unit tests for rebalanced depth_telemetry_pipeline.py."""

import json
import os
import tempfile
import unittest

from depth_telemetry_pipeline import (
    _regime_bucket,
    _sample_std,
    _smooth_step,
    attach_explanations,
    build_extractive_records,
    build_governance_records,
    build_macro_fiscal_records,
    build_spatial_livelihood_records,
    run_depth_pipeline,
    update_stochastic_layer,
)


class DepthTelemetryPipelineTests(unittest.TestCase):
    def test_math_helpers_and_regime_buckets(self):
        self.assertEqual(_sample_std([10.0]), 0.0)
        self.assertAlmostEqual(_sample_std([10.0, 20.0, 30.0]), 10.0, places=4)
        self.assertAlmostEqual(_smooth_step([], 50.0, alpha=0.2), 50.0, places=4)
        self.assertAlmostEqual(_smooth_step([50.0], 70.0, alpha=0.2), 54.0, places=4)
        self.assertEqual(_regime_bucket(None, None), "Unclassified / Stale")
        self.assertEqual(_regime_bucket(72.0, 2.0), "Acute Stress")
        self.assertEqual(_regime_bucket(56.0, 12.5), "Acute Stress")
        self.assertEqual(_regime_bucket(45.0, 2.0), "Elevated Friction")
        self.assertEqual(_regime_bucket(25.0, 7.0), "Elevated Friction")
        self.assertEqual(_regime_bucket(25.0, 2.0), "Contained")

    def test_depth_builders_and_explanations(self):
        extractive = attach_explanations(build_extractive_records(pdf_url="http://127.0.0.1:9/offline.pdf"))
        macro_fiscal = attach_explanations(build_macro_fiscal_records())
        spatial = attach_explanations(build_spatial_livelihood_records())
        governance = attach_explanations(build_governance_records())

        self.assertEqual(len(extractive), 4)
        self.assertEqual(len(macro_fiscal), 3)
        self.assertEqual(len(spatial), 3)
        self.assertEqual(len(governance), 3)
        self.assertIn("[Measured Directly]", extractive[1]["explanation"])
        self.assertIn("[Measured Directly]", macro_fiscal[0]["explanation"])
        self.assertIn("[Proxy / Estimate]", spatial[0]["explanation"])
        self.assertIn("[Measured Directly]", governance[0]["explanation"])
        self.assertIn("[Conceptual / Analytical Bucket]", governance[1]["explanation"])

    def test_stochastic_layer_and_pipeline_write(self):
        cache = {}
        update_stochastic_layer(cache, "mineral_qoq_dispersion", 33.07)
        update_stochastic_layer(cache, "mineral_qoq_dispersion", 42.0)
        stream = cache["stochastic_streams"]["mineral_qoq_dispersion"]
        self.assertEqual(stream["status"], "online")
        self.assertEqual(len(stream["history"]), 2)
        self.assertEqual(len(stream["smoothed_history"]), 2)
        self.assertGreater(stream["volatility_std_10"], 0.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cache = os.path.join(tmpdir, "telemetry_cache.json")
            run_depth_pipeline(cache_path=tmp_cache)
            self.assertTrue(os.path.exists(tmp_cache))
            with open(tmp_cache, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved["depth_records"]), 13)
            self.assertIn("mineral_qoq_dispersion", saved["stochastic_streams"])
            self.assertIn("legislative_plc_friction", saved["stochastic_streams"])
            self.assertEqual(saved["stochastic_streams"]["legislative_plc_friction"]["latest_raw"], 72.0)
            self.assertEqual(saved["stochastic_streams"]["legislative_plc_friction"]["regime"], "Acute Stress")


if __name__ == "__main__":
    unittest.main()
