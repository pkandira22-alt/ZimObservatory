#!/usr/bin/env python3
"""Unit tests for depth_telemetry_pipeline.py."""

import json
import os
import tempfile
import unittest

from depth_telemetry_pipeline import (
    _regime_bucket,
    _sample_std,
    _smooth_step,
    attach_explanations,
    build_legislative_friction_records,
    build_masvingo_gutu_livelihood_records,
    build_mineral_divergence_records,
    run_depth_pipeline,
    update_stochastic_layer,
)


class DepthTelemetryPipelineTests(unittest.TestCase):
    def test_math_helpers_and_regime_buckets(self):
        self.assertIsNone(_sample_std([10.0]))
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
        minerals = attach_explanations(build_mineral_divergence_records(live_fetch=False))
        livelihoods = attach_explanations(build_masvingo_gutu_livelihood_records())
        legislative = attach_explanations(build_legislative_friction_records())

        self.assertEqual(len(minerals), 5)
        self.assertEqual(len(livelihoods), 3)
        self.assertEqual(len(legislative), 3)
        self.assertIn("[Measured Directly]", minerals[1]["explanation"])
        self.assertIn("[Proxy / Estimate]", livelihoods[0]["explanation"])
        self.assertIn("[Conceptual / Analytical Bucket]", legislative[0]["explanation"])

    def test_stochastic_layer_and_pipeline_write(self):
        cache = {}
        update_stochastic_layer(cache, "mineral_qoq_dispersion", 31.24)
        update_stochastic_layer(cache, "mineral_qoq_dispersion", 42.0)
        stream = cache["stochastic_streams"]["mineral_qoq_dispersion"]
        self.assertEqual(stream["status"], "online")
        self.assertEqual(len(stream["history"]), 2)
        self.assertIsNotNone(stream["volatility_std_10"])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_cache = os.path.join(tmpdir, "telemetry_cache.json")
            out = run_depth_pipeline(cache_path=tmp_cache, live_fetch=False)
            self.assertTrue(os.path.exists(tmp_cache))
            with open(tmp_cache, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved["depth_records"]), 11)
            self.assertIn("mineral_qoq_dispersion", saved["stochastic_streams"])
            self.assertIn("legislative_plc_friction", saved["stochastic_streams"])
            self.assertEqual(saved["stochastic_streams"]["legislative_plc_friction"]["regime"], "Acute Stress")
            self.assertEqual(len(out["audited_telemetry"]["flagged_for_review"]), 0)


if __name__ == "__main__":
    unittest.main()
