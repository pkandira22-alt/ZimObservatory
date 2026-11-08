#!/usr/bin/env python3
"""Publish estimated Zimbabwe news telemetry to the Google Apps Script bridge."""

import datetime as dt
import email.utils
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


USER_AGENT = "KUVHURA-Observatory/1.0"
FEED_TIMEOUT_SECONDS = 20
PUBLISH_TIMEOUT_SECONDS = 30
RSS_SEARCHES = (
    "Zimbabwe",
    "Zimbabwe economy OR mining OR agriculture",
    "Zimbabwe politics OR election OR protest",
)
TOPICS = {
    "#Zimbabwe": (r"\bzimbabwe\b",),
    "#Harare": (r"\bharare\b",),
    "#Bulawayo": (r"\bbulawayo\b",),
    "#Mutare": (r"\bmutare\b",),
    "#Economy": (r"\beconomy\b", r"\binflation\b", r"\bcurrency\b", r"\bcost of living\b"),
    "#Politics": (r"\bpolitic\w*\b", r"\belection\w*\b", r"\bgovernment\b", r"\bopposition\b"),
    "#Agriculture": (r"\bagricultur\w*\b", r"\bfarm(?:ing|er|ers)?\b", r"\bharvest\b", r"\bcrop\w*\b"),
    "#Mining": (r"\bmin(?:e|es|ing|er|ers)\b", r"\bgold\b", r"\blithium\b"),
}
CONTESTED_TERMS = re.compile(
    r"\b(protest\w*|clash\w*|disput\w*|critic\w*|allegation\w*|conflict\w*|"
    r"opposition|crackdown|controvers\w*)\b",
    re.IGNORECASE,
)


def _local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def _text_for(entry, names):
    for element in entry.iter():
        if _local_name(element.tag) in names:
            return " ".join(element.itertext()).strip()
    return ""


def _entry_link(entry):
    for element in entry.iter():
        if _local_name(element.tag) == "link":
            href = element.attrib.get("href")
            if href:
                return href
            if element.text:
                return element.text.strip()
    return ""


def parse_feed(content):
    root = ET.fromstring(content)
    entries = []
    for entry in root.iter():
        if _local_name(entry.tag) not in ("item", "entry"):
            continue
        title = _text_for(entry, {"title"})
        summary = _text_for(entry, {"description", "summary", "content"})
        published = _text_for(entry, {"pubdate", "published", "updated"})
        source = _text_for(entry, {"source"})
        text = f"{title} {summary}".strip()
        if text:
            entries.append({
                "text": text,
                "published": published,
                "source": source,
                "link": _entry_link(entry),
            })
    return entries


def _published_datetime(value):
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def build_rows(entries, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)

    counts = {topic: {"mentions": 0, "recent": 0, "contested": 0} for topic in TOPICS}
    for entry in entries:
        text = entry["text"]
        published = _published_datetime(entry.get("published", ""))
        is_recent = published is not None and dt.timedelta(0) <= now - published <= dt.timedelta(hours=24)
        is_contested = CONTESTED_TERMS.search(text) is not None
        for topic, patterns in TOPICS.items():
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
                counts[topic]["mentions"] += 1
                counts[topic]["recent"] += int(is_recent)
                counts[topic]["contested"] += int(is_contested)

    timestamp = now.isoformat().replace("+00:00", "Z")
    rows = []
    for topic, metrics in counts.items():
        mentions = metrics["mentions"]
        if not mentions:
            continue
        velocity = min(100.0, metrics["recent"] * 10.0)
        polarization = round(metrics["contested"] / mentions * 10.0, 1)
        rows.append([timestamp, topic, mentions, velocity, polarization])
    return sorted(rows, key=lambda row: (-row[2], row[1]))


def fetch_feed(query):
    params = urllib.parse.urlencode({
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })
    url = f"https://news.google.com/rss/search?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=FEED_TIMEOUT_SECONDS) as response:
        return parse_feed(response.read())


def publish(rows, web_app_url, token):
    payload = json.dumps({"token": token, "rows": rows}).encode("utf-8")
    request = urllib.request.Request(
        web_app_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=PUBLISH_TIMEOUT_SECONDS) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("status") != "success":
        raise RuntimeError(result.get("message", "Apps Script rejected the telemetry update"))


def main():
    web_app_url = os.environ.get("GOOGLE_SHEETS_WEB_APP_URL", "").strip()
    token = os.environ.get("GOOGLE_SHEETS_WEB_APP_TOKEN", "").strip()
    if not web_app_url or not token:
        raise RuntimeError(
            "Set GOOGLE_SHEETS_WEB_APP_URL and GOOGLE_SHEETS_WEB_APP_TOKEN in the environment"
        )

    entries_by_link = {}
    successful_feeds = 0
    for query in RSS_SEARCHES:
        try:
            entries = fetch_feed(query)
            successful_feeds += 1
            for entry in entries:
                key = entry["link"] or entry["text"]
                entries_by_link.setdefault(key, entry)
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as error:
            print(f"Warning: RSS search {query!r} failed: {error}", file=sys.stderr)

    if successful_feeds == 0:
        raise RuntimeError("All Google News RSS searches failed")

    rows = build_rows(list(entries_by_link.values()))
    if not rows:
        raise RuntimeError("RSS searches returned no articles matching the telemetry topics")

    publish(rows, web_app_url, token)
    print(f"Published {len(rows)} topic rows from {len(entries_by_link)} unique articles")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, urllib.error.URLError, json.JSONDecodeError) as error:
        print(f"Telemetry sync failed: {error}", file=sys.stderr)
        sys.exit(1)
