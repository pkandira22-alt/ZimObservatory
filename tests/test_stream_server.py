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

    @patch.object(stream_server, "fetch_layer2_macro_telemetry")
    @patch.object(stream_server, "fetch_social_hashtag_trends")
    def test_stream_uses_local_social_telemetry_collector(self, fetch_trends, fetch_macro):
        payload = {
            "available": True,
            "updatedAt": "2026-11-08T12:00:00Z",
            "scannedPosts": 4,
            "hashtags": [{"tag": "#ZimResources", "mentions": 4, "latestMentions": 4}],
            "orientationInputs": None,
        }
        macro_payload = {"GDP_Growth": 5.3, "Inflation": 104.2, "Debt_GNI": 44.1, "source": "world_bank_v2"}
        fetch_trends.return_value = payload
        fetch_macro.return_value = macro_payload

        with (
            patch.object(stream_server, "TELEMETRY_TIMELINE", [
                {"date": "2026-11-07", "phi": 50.0, "markov_crisis_prob": 35.0, "state": "Latent Friction"}
            ]),
            patch.object(stream_server, "TIMELINE_BASELINE_DATE", None),
            patch.object(stream_server, "TIMELINE_BASELINE", None),
            patch.object(stream_server, "LATEST_DUAL_ENGINE_INPUTS", None),
        ):
            result = stream_server.fetch_trending_telemetry()

        fetch_trends.assert_called_once_with()
        fetch_macro.assert_called_once_with()
        self.assertEqual(result["status"], "available")
        self.assertIs(result["telemetry"], payload)
        self.assertEqual(result["telemetry"]["hashtags"][0]["tag"], "#ZimResources")
        self.assertEqual(result["layer2Macro"], macro_payload)
        self.assertEqual(result["dualEngineTimeline"]["inputStatus"], "updated")

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


if __name__ == "__main__":
    unittest.main()
