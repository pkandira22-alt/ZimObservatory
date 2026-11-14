import json
import unittest
from unittest.mock import MagicMock, patch

import stream_server


class StreamServerTests(unittest.TestCase):
    @patch.object(stream_server, "fetch_layer2_macro_telemetry")
    @patch.object(stream_server, "fetch_social_hashtag_trends")
    def test_stream_uses_local_social_telemetry_collector(self, fetch_trends, fetch_macro):
        payload = {
            "available": True,
            "updatedAt": "2026-11-08T12:00:00Z",
            "hashtags": [{"tag": "#ZimResources", "mentions": 4}],
            "orientationInputs": None,
        }
        macro_payload = {"GDP_Growth": 5.3, "Inflation": 104.2, "Debt_GNI": 44.1, "source": "world_bank_v2"}
        fetch_trends.return_value = payload
        fetch_macro.return_value = macro_payload

        result = stream_server.fetch_trending_telemetry()

        fetch_trends.assert_called_once_with()
        fetch_macro.assert_called_once_with()
        self.assertEqual(result["status"], "available")
        self.assertIs(result["telemetry"], payload)
        self.assertEqual(result["telemetry"]["hashtags"][0]["tag"], "#ZimResources")
        self.assertEqual(result["layer2Macro"], macro_payload)

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


if __name__ == "__main__":
    unittest.main()
