import json
import unittest
from unittest.mock import MagicMock, patch

from aiohttp.test_utils import TestClient, TestServer

import stream_server


class StreamServerTests(unittest.TestCase):
    def test_bayesian_phi_uses_strict_signal_thresholds(self):
        self.assertEqual(stream_server.compute_bayesian_posterior(40, 80, 1200), 73.53)
        self.assertEqual(stream_server.compute_bayesian_posterior(40, 81, 0), 16.89)
        self.assertEqual(stream_server.compute_bayesian_posterior(40, 0, 1201), 16.89)

    def test_engines_reject_invalid_inputs(self):
        with self.assertRaises(ValueError):
            stream_server.compute_bayesian_posterior(101, 0, 0)
        with self.assertRaises(ValueError):
            stream_server.compute_bayesian_posterior(50, -1, 0)
        with self.assertRaises(ValueError):
            stream_server.compute_markov_path_projection(float("nan"))
        with self.assertRaises(ValueError):
            stream_server.compute_fragility_state_index(50, 40, 101)

    def test_fragility_index_formula_and_warning_bands(self):
        self.assertEqual(stream_server.compute_fragility_state_index(40, 45, 40), 49.75)
        self.assertEqual(stream_server.compute_fragility_state_index(40, 45, 40, hansard_friction=70), 53.0)
        cases = (
            (25, "Stable Consolidation"),
            (25.01, "Latent Friction"),
            (50, "Latent Friction"),
            (50.01, "Accelerated Degradation"),
            (75, "Accelerated Degradation"),
            (75.01, "Acute Systemic Crisis"),
        )
        for fsi, expected in cases:
            with self.subTest(fsi=fsi):
                self.assertEqual(stream_server.classify_fragility_state(fsi), expected)

    def test_hansard_tfidf_scoring_and_cloudflare_challenge_handling(self):
        high_friction = stream_server.score_hansard_text(
            "Parliament debated corruption tender embezzlement, inflation parallel market depreciation, "
            "budget deficit unauthorized expenditure audit discrepancy, and a parliamentary walkout standoff."
        )
        low_friction = stream_server.score_hansard_text(
            "The honorable committee approved routine agricultural irrigation maintenance minutes for rural schools."
        )
        self.assertIsNotNone(high_friction)
        self.assertIsNotNone(low_friction)
        self.assertGreater(high_friction, low_friction)
        self.assertGreaterEqual(low_friction, 40.0)
        self.assertLessEqual(high_friction, 100.0)

        cf_error = stream_server.urllib.error.HTTPError(
            "https://e-portal.parlzim.gov.zw/",
            403,
            "Forbidden",
            {"cf-mitigated": "challenge", "server": "cloudflare"},
            None,
        )
        with (
            patch.dict("os.environ", {"TELEMETRY_CACHE_PATH": "/tmp/nonexistent_kuvhura_cache.json"}),
            patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
            patch.object(stream_server, "cureq", None),
            patch("stream_server.urllib.request.urlopen", side_effect=cf_error),
        ):
            blocked = stream_server.fetch_semantic_hansard_telemetry(use_cache=False)
        self.assertIsNone(blocked["score"])
        self.assertEqual(blocked["status"], "blocked_by_cloudflare")
        self.assertEqual(blocked["source"], "unavailable")
        self.assertEqual(blocked["totalSources"], 5)
        self.assertEqual(blocked["accessibleSources"], 0)
        self.assertEqual(blocked["tracked_topics"], [])
        self.assertEqual(len(blocked["sources"]), 5)

    def test_parliamentary_policy_tracker_extracts_real_topics_across_mixed_portals(self):
        bill_html = """
        <html><body>
          <h2>Public Procurement Corruption Amendment Bill</h2>
          <p>Committee debate on corruption, tender embezzlement, and illicit financial flows accountability.</p>
          <a href="/bill-digest/exchange-rate-stability">Exchange Rate Currency Stabilization Digest 2026</a>
        </body></html>
        """.encode("utf-8")
        hansard_html = """
        <html><body>
          <h3>Parliamentary Order Paper: Rural Irrigation Maintenance Motion</h3>
          <p>The honorable committee approved routine agricultural irrigation maintenance minutes for rural schools.</p>
        </body></html>
        """.encode("utf-8")

        def fake_urlopen(request, timeout=5):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "bill-digest" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.read.return_value = bill_html
                cm.__exit__.return_value = False
                return cm
            if "e-portal.parlzim.gov.zw" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.read.return_value = hansard_html
                cm.__exit__.return_value = False
                return cm
            raise stream_server.urllib.error.HTTPError(
                url, 403, "Forbidden", {"cf-mitigated": "challenge", "server": "cloudflare"}, None
            )

        with patch.object(stream_server, "cureq", None), patch("stream_server.urllib.request.urlopen", side_effect=fake_urlopen):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False)

        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["source"], "parlzim_hansards")
        self.assertEqual(tracker["accessibleSources"], 2)
        self.assertEqual(tracker["totalSources"], 5)
        self.assertEqual(len(tracker["sources"]), 5)
        self.assertIsNotNone(tracker["score"])
        topics = [t["topic"] for t in tracker["tracked_topics"]]
        self.assertIn("Public Procurement Corruption Amendment Bill", topics)
        self.assertNotIn("National Energy & Power Amendment Bill", topics)

    def test_parliamentary_policy_tracker_uses_curl_cffi_chrome_impersonation(self):
        fake_cureq = MagicMock()

        def fake_get(url, impersonate=None, timeout=None):
            self.assertEqual(impersonate, "chrome")
            self.assertEqual(timeout, 10)
            resp = MagicMock()
            if "e-portal.parlzim.gov.zw" in url:
                resp.status_code = 200
                resp.headers = {"content-type": "text/html"}
                resp.text = (
                    "<html><body><h2>Audit Discrepancy & Public Funds Committee Report</h2>"
                    "<p>Parliament reviewed audit discrepancy, tender embezzlement, and currency depreciation.</p>"
                    "</body></html>"
                )
            else:
                resp.status_code = 403
                resp.headers = {"cf-mitigated": "challenge", "server": "cloudflare"}
                resp.text = "Just a moment..."
            return resp

        fake_cureq.get.side_effect = fake_get
        with patch.object(stream_server, "cureq", fake_cureq):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=False)

        self.assertEqual(fake_cureq.get.call_count, 5)
        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["accessibleSources"], 1)
        self.assertEqual(tracker["totalSources"], 5)
        self.assertEqual(tracker["sources"][-1]["transport"], "curl_cffi_chrome")
        self.assertEqual(tracker["tracked_topics"][0]["topic"], "Audit Discrepancy & Public Funds Committee Report")

    def test_cloudflare_403_fails_over_to_zimlii_and_parliament_rss_mirrors(self):
        zimlii_html = """
        <html><body>
          <a href="/akn/zw/act/si/2026/9/eng@2026-01-12">Public Procurement and Disposal of Public Assets (Amendment) Regulations, 2026</a>
          <p>Regulations addressing tender audit discrepancy, public funds accountability, and procurement transparency across ministries.</p>
        </body></html>
        """.encode("utf-8")
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Parliament Debates</title>
          <item>
            <title>Parliament portfolio committee debates 2027 National Budget and audit discrepancies</title>
            <link>https://news.google.com/articles/zimbabwe-parliament-budget</link>
            <description>Parliamentary committee oversight on expenditure, debt, and exchange rate friction.</description>
          </item>
        </channel></rss>
        """.encode("utf-8")

        def fake_urlopen(request, timeout=8):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "zimlii.org" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.headers = {}
                cm.__enter__.return_value.read.return_value = zimlii_html
                cm.__exit__.return_value = False
                return cm
            if "news.google.com" in url:
                cm = MagicMock()
                cm.__enter__.return_value.status = 200
                cm.__enter__.return_value.headers = {}
                cm.__enter__.return_value.read.return_value = rss_xml
                cm.__exit__.return_value = False
                return cm
            raise stream_server.urllib.error.HTTPError(
                url, 403, "Forbidden", {"cf-mitigated": "challenge", "server": "cloudflare"}, None
            )

        with (
            patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
            patch.object(stream_server, "cureq", None),
            patch("stream_server.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            tracker = stream_server.fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=True)

        self.assertEqual(tracker["status"], "available")
        self.assertEqual(tracker["accessibleSources"], 5)
        self.assertTrue(all(src.get("viaFallbackMirror") for src in tracker["sources"]))
        self.assertTrue(all(src.get("primaryBlockedByCloudflare") for src in tracker["sources"]))
        topic_titles = [t["topic"] for t in tracker["tracked_topics"]]
        self.assertIn("Public Procurement and Disposal of Public Assets (Amendment) Regulations, 2026", topic_titles)
        self.assertIn("Parliament portfolio committee debates 2027 National Budget and audit discrepancies", topic_titles)

    def test_telemetry_cache_fallback_only_uses_verified_available_snapshots(self):
        import os
        import tempfile

        cf_error = stream_server.urllib.error.HTTPError(
            "https://e-portal.parlzim.gov.zw/",
            403,
            "Forbidden",
            {"cf-mitigated": "challenge", "server": "cloudflare"},
            None,
        )
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
            cache_file = tf.name
            json.dump({
                "updated_at": "2026-11-15T06:00:00Z",
                "parlzim": {
                    "score": None,
                    "status": "blocked_by_cloudflare",
                    "source": "unavailable",
                    "accessibleSources": 0,
                    "totalSources": 5,
                    "tracked_topics": [],
                },
                "last_available_parlzim": {
                    "score": 61.5,
                    "status": "available",
                    "source": "parlzim_portals",
                    "accessibleSources": 2,
                    "totalSources": 5,
                    "sources": [],
                    "tracked_topics": [{"topic": "Verified Cached Finance Bill", "category": "Bill Digests", "status": "Legislative Pipeline", "friction": 61.5}],
                },
            }, tf)

        try:
            with (
                patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file}),
                patch.object(stream_server, "cureq", None),
                patch("stream_server.urllib.request.urlopen", side_effect=cf_error),
            ):
                fallback = stream_server.fetch_parliamentary_policy_tracker(use_cache=False)
            self.assertEqual(fallback["status"], "available")
            self.assertEqual(fallback["score"], 61.5)
            self.assertTrue(fallback["fromCache"])
            self.assertEqual(fallback["cacheUpdatedAt"], "2026-11-15T06:00:00Z")
            self.assertEqual(fallback["tracked_topics"][0]["topic"], "Verified Cached Finance Bill")

            with open(cache_file, "w", encoding="utf-8") as wf:
                json.dump({
                    "timestamp": "2026-11-15T06:00:00Z",
                    "accessible_sources": 0,
                    "total_sources": 5,
                    "hansard_friction": 58.0,
                    "tracked_topics": [],
                    "status": "Live Crawl Attempted via Actions",
                }, wf)

            with (
                patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file}),
                patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
                patch.object(stream_server, "cureq", None),
                patch("stream_server.urllib.request.urlopen", side_effect=cf_error),
            ):
                blocked = stream_server.fetch_parliamentary_policy_tracker(use_cache=False)
            self.assertEqual(blocked["status"], "blocked_by_cloudflare")
            self.assertIsNone(blocked["score"])

            with open(cache_file, "w", encoding="utf-8") as wf:
                json.dump({
                    "timestamp": "2026-11-15T06:00:00Z",
                    "accessible_sources": 3,
                    "total_sources": 5,
                    "hansard_friction": 64.25,
                    "tracked_topics": [{"topic": "Cached Treasury Oversight Brief", "category": "Policy Briefs", "status": "Policy Review", "friction": 64.25}],
                    "status": "Live Crawl Attempted via Actions",
                }, wf)

            with (
                patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file}),
                patch.object(stream_server, "HANSARD_CACHE", {"expires_at": 0.0, "data": None}),
                patch("stream_server.urllib.request.urlopen", side_effect=AssertionError("Should read disk cache first")),
            ):
                cache_first = stream_server.fetch_parliamentary_policy_tracker(use_cache=True)
                tuple_result = stream_server.load_telemetry_cache()
            self.assertEqual(cache_first["score"], 64.25)
            self.assertEqual(cache_first["accessibleSources"], 3)
            self.assertTrue(cache_first["fromCache"])
            self.assertEqual(cache_first["tracked_topics"][0]["topic"], "Cached Treasury Oversight Brief")
            self.assertEqual(tuple_result[0], 64.25)
            self.assertEqual(tuple_result[2], 3)
            self.assertEqual(tuple_result[1][0]["topic"], "Cached Treasury Oversight Brief")
        finally:
            os.remove(cache_file)

        with patch.dict(os.environ, {"TELEMETRY_CACHE_PATH": cache_file + ".missing"}):
            self.assertEqual(stream_server.load_telemetry_cache(), (None, [], 0))

    def test_macro_stress_proxy_requires_sourced_world_bank_data(self):
        macro = {
            "GDP_Growth": 5.3,
            "Inflation": 104.2,
            "Debt_GNI": 44.1,
            "source": "world_bank_v2",
        }
        self.assertEqual(stream_server.compute_macro_stress_proxy(macro), 43.98)
        macro["source"] = "fallback_baseline"
        self.assertIsNone(stream_server.compute_macro_stress_proxy(macro))

    def test_markov_projection_and_social_proxy_derivation(self):
        self.assertEqual(stream_server.compute_markov_path_projection(46.8), 41.9)
        self.assertEqual(
            stream_server.derive_social_metrics({
                "available": True,
                "scannedPosts": 120,
                "hashtags": [
                    {"latestMentions": 12},
                    {"latestMentions": 8},
                    {"mentions": 5},
                ],
            }),
            (120, 25),
        )
        self.assertIsNone(stream_server.derive_social_metrics({
            "available": True,
            "sampleType": "rss-sheet",
            "scannedPosts": 0,
            "hashtags": [{"mentions": 40}],
        }))

    def test_timeline_refresh_recalculates_from_daily_baseline(self):
        seed_timeline = [
            {"date": "2026-11-14", "phi": 40.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
        ]
        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", seed_timeline),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
            patch.object(stream_server, "LATEST_FSI_INPUTS", None),
            patch.object(stream_server, "LATEST_HANSARD_STATUS", None),
        ):
            evaluated_at = stream_server.datetime(2026, 11, 15, tzinfo=stream_server.timezone.utc)
            stream_server.update_telemetry_timeline({
                "available": True,
                "scannedPosts": 100,
                "hashtags": [{"latestMentions": 12}],
            }, evaluated_at)
            high_signal_phi = seed_timeline[-1]["phi"]
            self.assertEqual(high_signal_phi, 16.89)

            stream_server.update_telemetry_timeline({
                "available": True,
                "scannedPosts": 10,
                "hashtags": [{"latestMentions": 2}],
            }, evaluated_at)

            self.assertEqual(seed_timeline[-1]["phi"], 73.53)
            self.assertEqual(len(seed_timeline), 2)

    def test_timeline_fsi_uses_live_macro_proxy_and_withholds_fallback(self):
        seed_timeline = [
            {"date": "2026-11-14", "phi": 40.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
        ]
        social_payload = {
            "available": True,
            "scannedPosts": 10,
            "hashtags": [{"latestMentions": 2}],
        }
        live_macro = {
            "GDP_Growth": 5.3,
            "Inflation": 104.2,
            "Debt_GNI": 44.1,
            "source": "world_bank_v2",
        }
        evaluated_at = stream_server.datetime(2026, 11, 15, tzinfo=stream_server.timezone.utc)
        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", seed_timeline),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
            patch.object(stream_server, "LATEST_FSI_INPUTS", None),
            patch.object(stream_server, "LATEST_HANSARD_STATUS", None),
        ):
            stream_server.update_telemetry_timeline(
                social_payload, evaluated_at, layer2_macro=live_macro
            )
            entry = seed_timeline[-1]
            self.assertEqual(entry["macro_volatility_proxy"], 43.98)
            self.assertEqual(
                entry["fsi"],
                stream_server.compute_fragility_state_index(
                    entry["phi"], entry["markov_crisis_prob"], 43.98
                ),
            )
            self.assertEqual(entry["warning_level"], stream_server.classify_fragility_state(entry["fsi"]))

            stream_server.update_telemetry_timeline(
                social_payload,
                evaluated_at,
                layer2_macro={**live_macro, "source": "fallback_baseline"},
            )
            self.assertNotIn("fsi", seed_timeline[-1])
            self.assertEqual(
                stream_server.get_dual_engine_timeline()["fsiStatus"]["status"],
                "awaiting_sourced_macro_data",
            )

    @patch.object(stream_server, "fetch_semantic_hansard_telemetry")
    @patch.object(stream_server, "fetch_layer2_macro_telemetry")
    @patch.object(stream_server, "fetch_social_hashtag_trends")
    def test_stream_uses_local_social_telemetry_collector(self, fetch_trends, fetch_macro, fetch_hansard):
        payload = {
            "available": True,
            "updatedAt": "2026-11-08T12:00:00Z",
            "scannedPosts": 4,
            "hashtags": [{"tag": "#ZimResources", "mentions": 4, "latestMentions": 4}],
            "orientationInputs": None,
        }
        macro_payload = {"GDP_Growth": 5.3, "Inflation": 104.2, "Debt_GNI": 44.1, "source": "world_bank_v2"}
        hansard_payload = {"score": 68.4, "status": "available", "source": "parlzim_hansards"}
        fetch_trends.return_value = payload
        fetch_macro.return_value = macro_payload
        fetch_hansard.return_value = hansard_payload

        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", [
                {"date": "2026-11-07", "phi": 50.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
            ]),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
            patch.object(stream_server, "LATEST_FSI_INPUTS", None),
            patch.object(stream_server, "LATEST_HANSARD_STATUS", None),
        ):
            result = stream_server.fetch_trending_telemetry()

        fetch_trends.assert_called_once_with()
        fetch_macro.assert_called_once_with()
        fetch_hansard.assert_called_once_with()
        self.assertEqual(result["status"], "available")
        self.assertIs(result["telemetry"], payload)
        self.assertEqual(result["telemetry"]["hashtags"][0]["tag"], "#ZimResources")
        self.assertEqual(result["layer2Macro"], macro_payload)
        self.assertEqual(result["dualEngineTimeline"]["inputStatus"], "updated")
        self.assertEqual(result["dualEngineTimeline"]["fsiStatus"]["status"], "available")
        self.assertTrue(result["dualEngineTimeline"]["fsiStatus"]["hansard_included"])
        self.assertEqual(result["dualEngineTimeline"]["hansardStatus"]["score"], 68.4)

    @patch("stream_server.urllib.request.urlopen")
    def test_fetch_layer2_macro_telemetry_parses_world_bank_values(self, mock_urlopen):
        responses = [
            json.dumps([{}, [{"value": 6.1}]]).encode("utf-8"),
            json.dumps([{}, [{"value": 4.8}]]).encode("utf-8"),
            json.dumps([{}, [{"value": 39.2}]]).encode("utf-8"),
        ]
        side_effects = []
        for raw in responses:
            cm = MagicMock()
            cm.__enter__.return_value.read.return_value = raw
            cm.__exit__.return_value = False
            side_effects.append(cm)
        mock_urlopen.side_effect = side_effects

        result = stream_server.fetch_layer2_macro_telemetry(use_cache=False)

        self.assertEqual(result["GDP_Growth"], 6.1)
        self.assertEqual(result["Inflation"], 4.8)
        self.assertEqual(result["Debt_GNI"], 39.2)
        self.assertEqual(result["source"], "world_bank_v2")

    @patch("stream_server.urllib.request.urlopen", side_effect=TimeoutError("timed out"))
    def test_fetch_layer2_macro_telemetry_falls_back_to_baseline_on_error(self, _mock_urlopen):
        result = stream_server.fetch_layer2_macro_telemetry(use_cache=False)

        self.assertEqual(result["GDP_Growth"], 8.3)
        self.assertEqual(result["Inflation"], 5.2)
        self.assertEqual(result["Debt_GNI"], 37.9)
        self.assertEqual(result["source"], "fallback_baseline")


class TimelineApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeline_endpoint_returns_seed_history_and_cors(self):
        client = TestClient(TestServer(stream_server.create_app()))
        with patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None):
            await client.start_server()
            try:
                response = await client.get("/api/timeline")
                payload = await response.json()
            finally:
                await client.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(payload["inputStatus"], "awaiting_social_sample")
        self.assertEqual(payload["timeline"][-1]["date"], "2026-11-14")
        self.assertEqual(payload["timeline"][-1]["fsi"], 62.97)


if __name__ == "__main__":
    unittest.main()
