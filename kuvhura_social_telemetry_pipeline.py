#!/usr/bin/env python3
import logging
import os
from datetime import datetime, timezone

import feedparser
import requests

LOGGER = logging.getLogger("kuvhura_social_telemetry")

RSS_SOURCES = (
    ("New Zimbabwe", "https://www.newzimbabwe.com/feed/"),
    ("The Zimbabwe Independent", "https://www.theindependent.co.zw/feed/"),
    ("Voice of America Zimbabwe", "https://www.voazimbabwe.com/api/z_roqevtmv"),
)

KEYWORDS = {
    "#ZimResources": ("resource", "mineral", "lithium", "gold", "platinum", "mutapa"),
    "#MutapaLeads": ("mutapa", "parastatal", "fund", "asset", "disposal"),
    "#OAGAudit": ("auditor", "audit", "corruption", "leakage", "tender", "procurement"),
    "#EconomicAutonomy": ("inflation", "currency", "prices", "vending", "strike"),
}


def fetch_rss_and_public_feeds():
    counts = {hashtag: 0 for hashtag in KEYWORDS}
    successful_sources = []
    failures = []
    total_entries = 0

    for source, url in RSS_SOURCES:
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "KUVHURA-Observatory/1.0"},
                timeout=20,
            )
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError("Feed response could not be parsed")

            successful_sources.append(source)
            total_entries += len(parsed.entries)
            for entry in parsed.entries:
                text = f"{entry.get('title', '')} {entry.get('summary', '')}".casefold()
                for hashtag, terms in KEYWORDS.items():
                    if any(term in text for term in terms):
                        counts[hashtag] += 1
        except (requests.RequestException, ValueError) as error:
            LOGGER.warning("Could not read RSS source %s: %s", source, error)
            failures.append(source)

    if not successful_sources:
        raise RuntimeError(f"All RSS sources failed: {', '.join(failures)}")
    if total_entries == 0:
        raise RuntimeError("RSS sources returned no entries; refusing to publish an empty sample")

    LOGGER.info(
        "Read %d feed entries from %d sources (%d unavailable)",
        total_entries,
        len(successful_sources),
        len(failures),
    )
    return counts


def calculate_metrics(counts, timestamp=None):
    timestamp = timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    current_time = timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []

    for hashtag, count in counts.items():
        count = max(0, int(count))
        velocity = round(min(100.0, max(45.0, count * 12.5 + 40.0)), 1)
        polarization = round(min(9.5, max(4.0, 5.0 + count * 0.4)), 1)
        estimated_mentions = count * 35 + 120
        rows.append([current_time, hashtag, estimated_mentions, velocity, polarization])

    return rows


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    web_app_url = os.environ.get("GOOGLE_SHEETS_WEB_APP_URL")
    sync_token = os.environ.get("GOOGLE_SHEETS_WEB_APP_TOKEN")
    if not web_app_url or not sync_token:
        raise SystemExit(
            "GOOGLE_SHEETS_WEB_APP_URL and GOOGLE_SHEETS_WEB_APP_TOKEN must be configured"
        )

    counts = fetch_rss_and_public_feeds()
    rows = calculate_metrics(counts)
    response = requests.post(
        web_app_url,
        json={"token": sync_token, "rows": rows},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    try:
        result = response.json()
    except requests.exceptions.JSONDecodeError as error:
        raise RuntimeError("Google Apps Script returned an invalid response") from error
    if not isinstance(result, dict) or result.get("status") != "success":
        raise RuntimeError(f"Google Apps Script rejected the telemetry update: {result}")

    LOGGER.info("Published telemetry for %d hashtags to Google Sheets", len(rows))


if __name__ == "__main__":
    main()
