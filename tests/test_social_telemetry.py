import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import kuvhura_social_telemetry_pipeline as pipeline
import server


SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Zimbabwe News</title>
    <item>
      <title>Zimbabwe lithium mining dispute escalates in Harare</title>
      <description>Opposition protest over mining policy and inflation.</description>
      <pubDate>Sun, 08 Nov 2026 08:00:00 GMT</pubDate>
      <link>https://example.test/news/1</link>
      <source>Daily News</source>
    </item>
    <item>
      <title>Zimbabwe agriculture harvest outlook improves</title>
      <description>Farmers expect steady crop yields in Mutare.</description>
      <pubDate>Tue, 03 Nov 2026 08:00:00 GMT</pubDate>
      <link>https://example.test/news/2</link>
      <source>Herald</source>
    </item>
  </channel>
</rss>
"""


class SocialTelemetryTests(unittest.TestCase):
    def test_parse_feed_extracts_rss_entries(self):
        entries = pipeline.parse_feed(SAMPLE_RSS)

        self.assertEqual(len(entries), 2)
        self.assertIn("lithium mining", entries[0]["text"])
        self.assertEqual(entries[0]["link"], "https://example.test/news/1")
        self.assertEqual(entries[0]["source"], "Daily News")

    def test_build_rows_uses_expected_columns_and_formulas(self):
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        entries = pipeline.parse_feed(SAMPLE_RSS)

        rows = pipeline.build_rows(entries, now=now)
        by_topic = {row[1]: row for row in rows}

        # Both entries mention Zimbabwe; 1 is within 24h (velocity=10.0), 1 has contested terms (polarization=5.0)
        self.assertEqual(
            by_topic["#Zimbabwe"],
            ["2026-11-08T12:00:00Z", "#Zimbabwe", 2, 10.0, 5.0],
        )
        # Only first entry mentions lithium/mining; recent + contested -> velocity=10.0, polarization=10.0
        self.assertEqual(
            by_topic["#Mining"],
            ["2026-11-08T12:00:00Z", "#Mining", 1, 10.0, 10.0],
        )
        # Second entry is 5 days old and non-contested -> velocity=0.0, polarization=0.0
        self.assertEqual(
            by_topic["#Agriculture"],
            ["2026-11-08T12:00:00Z", "#Agriculture", 1, 0.0, 0.0],
        )
        # Sorted by descending mentions then alphabetical topic
        self.assertEqual(rows[0][1], "#Zimbabwe")

    @patch.object(pipeline.urllib.request, "urlopen")
    @patch.object(pipeline, "build_rows", return_value=[["2026-11-08T12:00:00Z", "#Zimbabwe", 2, 20.0, 5.0]])
    @patch.object(pipeline, "fetch_feed")
    def test_main_trims_github_secret_whitespace_and_deduplicates_links(self, mock_fetch, mock_build_rows, mock_urlopen):
        mock_fetch.side_effect = [
            [{"text": "Zimbabwe economy update", "published": "", "source": "", "link": "https://example.test/a"}],
            [{"text": "Zimbabwe economy update", "published": "", "source": "", "link": "https://example.test/a"}],
            [{"text": "Harare election debate", "published": "", "source": "", "link": "https://example.test/b"}],
        ]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"status": "success"}).encode("utf-8")
        response.__exit__.return_value = False
        mock_urlopen.return_value = response

        environment = {
            "GOOGLE_SHEETS_WEB_APP_URL": " https://script.google.com/macros/s/id/exec \n",
            "GOOGLE_SHEETS_WEB_APP_TOKEN": " token \n",
        }

        with patch.dict(os.environ, environment):
            pipeline.main()

        self.assertEqual(mock_fetch.call_count, len(pipeline.RSS_SEARCHES))
        # Deduplicated 3 returned items down to 2 unique links
        self.assertEqual(len(mock_build_rows.call_args.args[0]), 2)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://script.google.com/macros/s/id/exec")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["token"], "token")

    @patch.object(pipeline.urllib.request, "urlopen")
    def test_fetch_feed_parses_remote_rss_bytes(self, mock_urlopen):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = SAMPLE_RSS
        response.__exit__.return_value = False
        mock_urlopen.return_value = response

        entries = pipeline.fetch_feed("Zimbabwe")

        self.assertEqual(len(entries), 2)
        request = mock_urlopen.call_args.args[0]
        self.assertIn("news.google.com/rss/search", request.full_url)
        self.assertIn("q=Zimbabwe", request.full_url)

    @patch.object(server, "urlopen")
    def test_sheet_rows_are_adapted_for_dashboard(self, mock_urlopen):
        body = json.dumps({
            "updatedAt": "2026-11-08T12:00:00Z",
            "rows": [
                ["2026-11-08T12:00:00Z", "#ZimResources", 260, 90.0, 6.6],
                ["2026-11-08T12:00:00Z", "#OAGAudit", 155, 52.5, 5.4],
            ],
        }).encode()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = body
        response.__exit__.return_value = False
        mock_urlopen.return_value = response

        result = server.fetch_sheet_social_hashtag_trends("https://example.test/exec")

        self.assertTrue(result["available"])
        self.assertEqual(result["sampleType"], "rss-sheet")
        self.assertEqual(result["hashtags"][0]["tag"], "#ZimResources")
        self.assertEqual(result["hashtags"][0]["narrativeVelocity"], 90.0)
        self.assertEqual(result["hashtags"][0]["polarizationIndex"], 6.6)

    def test_configured_sheet_is_used_by_social_feed_endpoint(self):
        previous_cache = server.SOCIAL_CACHE.copy()
        try:
            server.SOCIAL_CACHE.update(expires_at=0, payload=None)
            expected = {"available": True, "sampleType": "rss-sheet", "hashtags": []}
            with patch.dict(os.environ, {"GOOGLE_SHEETS_WEB_APP_URL": " https://example.test/exec \n"}):
                with patch.object(server, "fetch_sheet_social_hashtag_trends", return_value=expected) as mock_fetch:
                    result = server.fetch_social_hashtag_trends()
            self.assertIs(result, expected)
            mock_fetch.assert_called_once_with("https://example.test/exec")
        finally:
            server.SOCIAL_CACHE.update(previous_cache)


if __name__ == "__main__":
    unittest.main()

