import unittest
from unittest.mock import patch

import stream_server


class StreamServerTests(unittest.TestCase):
    @patch.object(stream_server, "fetch_social_hashtag_trends")
    def test_stream_uses_local_social_telemetry_collector(self, fetch_trends):
        payload = {
            "available": True,
            "updatedAt": "2026-11-08T12:00:00Z",
            "hashtags": [{"tag": "#ZimResources", "mentions": 4}],
            "orientationInputs": None,
        }
        fetch_trends.return_value = payload

        result = stream_server.fetch_trending_telemetry()

        fetch_trends.assert_called_once_with()
        self.assertEqual(result["status"], "available")
        self.assertIs(result["telemetry"], payload)
        self.assertEqual(result["telemetry"]["hashtags"][0]["tag"], "#ZimResources")


if __name__ == "__main__":
    unittest.main()
