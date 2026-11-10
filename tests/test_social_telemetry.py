import json
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import kuvhura_social_telemetry_pipeline as pipeline
import server


class SocialTelemetryTests(unittest.TestCase):
    def test_metrics_use_expected_columns_and_formulas(self):
        timestamp = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)

        rows = pipeline.calculate_metrics(
            {"#ZimResources": 4},
            timestamp=timestamp,
        )

        self.assertEqual(
            rows[0],
            ["2026-11-08T12:00:00Z", "#ZimResources", 260, 90.0, 6.6],
        )

    @patch.object(pipeline.requests, "post")
    @patch.object(pipeline, "calculate_metrics", return_value=[["timestamp", "#tag", 1, 50, 5]])
    @patch.object(pipeline, "fetch_rss_and_public_feeds", return_value={"#tag": 0})
    def test_main_trims_github_secret_whitespace(self, _fetch, _metrics, mock_post):
        response = MagicMock()
        response.json.return_value = {"status": "success"}
        mock_post.return_value = response
        environment = {
            "GOOGLE_SHEETS_WEB_APP_URL": " https://script.google.com/macros/s/id/exec \n",
            "GOOGLE_SHEETS_WEB_APP_TOKEN": " token \n",
        }

        with patch.dict(os.environ, environment):
            pipeline.main()

        self.assertEqual(mock_post.call_args.args[0], "https://script.google.com/macros/s/id/exec")
        self.assertEqual(mock_post.call_args.kwargs["json"]["token"], "token")

    @patch.object(pipeline.feedparser, "parse")
    @patch.object(pipeline.requests, "get")
    def test_feed_ingestion_counts_matching_articles(self, mock_get, mock_parse):
        mock_get.return_value = SimpleNamespace(raise_for_status=lambda: None, content=b"feed")
        mock_parse.side_effect = [
            SimpleNamespace(bozo=False, entries=[{"title": "New lithium resource", "summary": ""}]),
            SimpleNamespace(bozo=False, entries=[{"title": "Audit tender", "summary": ""}]),
            SimpleNamespace(bozo=False, entries=[{"title": "Unrelated news", "summary": ""}]),
        ]

        counts = pipeline.fetch_rss_and_public_feeds()

        self.assertEqual(counts["#ZimResources"], 1)
        self.assertEqual(counts["#OAGAudit"], 1)
        self.assertEqual(counts["#MutapaLeads"], 0)
        self.assertEqual(mock_get.call_count, len(pipeline.RSS_SOURCES))

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
            with patch.dict(os.environ, {"GOOGLE_SHEETS_WEB_APP_URL": "https://example.test/exec"}):
                with patch.object(server, "fetch_sheet_social_hashtag_trends", return_value=expected):
                    result = server.fetch_social_hashtag_trends()
            self.assertIs(result, expected)
        finally:
            server.SOCIAL_CACHE.update(previous_cache)


if __name__ == "__main__":
    unittest.main()
