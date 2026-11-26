#!/usr/bin/env python3
"""Unit tests for telemetry_audit.py."""

import unittest
from telemetry_audit import (
    audit_and_partition_records,
    build_audited_record,
    explain_record,
)


class TelemetryAuditTests(unittest.TestCase):
    def test_direct_record_passes_cleanly(self):
        rec = build_audited_record(
            record_id="plat-q1-2026",
            label="Great Dyke Corridor — Platinum",
            domain="extraction",
            value=3807,
            unit="kg",
            period="Q1 2026",
            lineage="Measured Directly",
            status="live",
            source_title="ZIMSTAT IMP Q1 2026",
            source_url="https://www.zimstat.co.zw/wp-content/uploads/production/Mining/2026/Q1/IMP_2026_Q1.pdf",
        )
        self.assertEqual(rec["lineage"], "Measured Directly")
        self.assertEqual(rec["status"], "live")
        self.assertEqual(rec["value"], 3807)
        self.assertEqual(rec["audit_flags"], [])
        self.assertIn("[Measured Directly]", rec["explanation"])

    def test_honesty_downgrade_when_measured_directly_has_no_value(self):
        rec = build_audited_record(
            record_id="missing-qty",
            label="Gutu North Context",
            domain="spatial",
            value=None,
            unit="kg",
            period="2025-2026",
            lineage="Measured Directly",
            status="live",
            source_title="ZimVAC",
            source_url="https://www.fnc.org.zw/documents/",
        )
        self.assertEqual(rec["lineage"], "Proxy / Estimate")
        self.assertEqual(rec["status"], "no_reported_quantity")

    def test_sanity_bounds_catch_ocr_glitch_and_flag(self):
        rec = build_audited_record(
            record_id="ocr-glitch",
            label="Glitched Score",
            domain="module",
            value=999.0,
            unit="score_0_100",
            period="2026-Q4",
            lineage="Measured Directly",
            status="live",
            source_title="Test Source",
            source_url="javascript:alert(1)",
        )
        self.assertIsNone(rec["value"])
        self.assertEqual(rec["status"], "stale")
        self.assertIsNone(rec["source_url"])
        self.assertIn("missing_or_invalid_source_url", rec["audit_flags"])
        self.assertTrue(any(f.startswith("out_of_bounds_for_score_0_100") for f in rec["audit_flags"]))

    def test_partitioning_separates_direct_proxy_and_flagged(self):
        result = audit_and_partition_records([
            {
                "id": "direct-1",
                "label": "Gold",
                "domain": "extraction",
                "value": 9894,
                "unit": "kg",
                "period": "Q1 2026",
                "lineage": "Measured Directly",
                "status": "live",
                "source_title": "ZIMSTAT",
                "source_url": "https://www.zimstat.co.zw/",
            },
            {
                "id": "bucket-1",
                "label": "Component 4: Gender (Vg)",
                "domain": "module",
                "value": 1.65,
                "unit": "multiplier",
                "period": "2026",
                "lineage": "Conceptual / Analytical Bucket",
                "status": "cached",
                "source_title": "KUVHURA Framework",
                "source_url": "https://www.zimstat.co.zw/",
            },
            {
                "id": "flagged-1",
                "label": "Unsourced Entry",
                "domain": "macro",
                "value": 42,
                "unit": "pct",
                "period": None,
                "lineage": "Proxy / Estimate",
                "status": "cached",
                "source_title": None,
                "source_url": "not-a-url",
            },
        ])
        self.assertEqual(len(result["measured_directly"]), 1)
        self.assertEqual(len(result["proxy_and_buckets"]), 2)
        self.assertEqual(len(result["flagged_for_review"]), 1)
        self.assertIn("Tagged [Conceptual / Analytical Bucket]", explain_record(result["proxy_and_buckets"][0]))


if __name__ == "__main__":
    unittest.main()
