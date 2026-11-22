#!/usr/bin/env python3
"""
Land Portal Zimbabwe Dataset Ingestion Script for KUVHURA Observatory.

Loads a structured CSV or JSON dataset export downloaded from Land Portal,
filters strictly to Zimbabwe (ZWE / Zimbabwe) records, classifies data lineage
into "Measured Directly" vs "Proxy / Estimate", and merges up to 15 records
into telemetry_cache.json under `landportal_zwe_signals`.
"""

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

CACHE_PATH = os.environ.get("TELEMETRY_CACHE_PATH", "telemetry_cache.json")
MAX_RECORDS = 15
DEFAULT_SOURCE_URL = "https://landportal.org/book/datasets"


def sanitize_https_url(raw_url, default=DEFAULT_SOURCE_URL):
    try:
        parsed = urlparse(str(raw_url or "").strip())
        if parsed.scheme == "https" and parsed.netloc:
            return parsed.geturl()
    except Exception:
        pass
    return default


def load_rows_from_file(filepath):
    """Load rows from a structured CSV or JSON dataset export (not a raw HTML page)."""
    ext = os.path.splitext(filepath)[1].lower()
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        if ext == ".csv":
            return list(csv.DictReader(f))
        if ext == ".json":
            data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("results", "data", "records", "items"):
                    if isinstance(data.get(key), list):
                        return data[key]
    raise ValueError(f"Unsupported or unrecognized dataset structure in '{filepath}'")


def is_zimbabwe_record(row):
    """Filter strictly to Zimbabwe records by ISO3 code or country name."""
    if not isinstance(row, dict):
        return False
    candidates = [
        str(row.get(k, "")).strip().upper()
        for k in ("iso3", "country_code", "country", "country_name", "region", "area")
        if k in row
    ]
    if any(val in ("ZWE", "ZIMBABWE") for val in candidates):
        return True
    blob = " ".join(str(v) for v in row.values() if v is not None).lower()
    return "zimbabwe" in blob


def extract_first(row, keys, default=""):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return str(row[k]).strip()
    return default


def parse_numeric_value(raw_val):
    if raw_val is None:
        return None
    cleaned = str(raw_val).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def classify_lineage(row, numeric_val):
    """
    Explicitly separate direct observations from proxies/estimates:
    - Measured Directly when a numeric figure/record is present and not marked estimated/projected/proxy.
    - Proxy / Estimate when missing numeric values, estimated/projected flags, or indirect indicators are present.
    """
    status_blob = " ".join(
        str(row.get(k, "")).lower()
        for k in ("status", "obs_status", "type", "estimate", "method", "notes")
        if k in row
    )
    is_proxy_hint = any(
        word in status_blob
        for word in ("proxy", "estimate", "estimated", "projection", "projected", "modelled", "modeled")
    )
    if numeric_val is not None and not is_proxy_hint:
        return "Measured Directly"
    return "Proxy / Estimate"


def ingest_landportal_dataset(
    filepath,
    dataset_title="Land Portal Dataset",
    source_url=DEFAULT_SOURCE_URL,
):
    rows = load_rows_from_file(filepath)
    zwe_rows = [r for r in rows if is_zimbabwe_record(r)]
    safe_url = sanitize_https_url(source_url)

    normalized = []
    for idx, row in enumerate(zwe_rows):
        indicator = extract_first(
            row,
            ("indicator", "indicator_name", "title", "deal_size", "land_use", "topic", "variable"),
            default=f"Record #{idx + 1}",
        )[:140]
        provider = extract_first(
            row,
            ("provider", "source", "organization", "institution", "data_provider"),
            default=dataset_title,
        )[:100]
        period = extract_first(
            row,
            ("year", "date", "period", "time", "start_year"),
            default="N/A",
        )[:32]
        unit = extract_first(row, ("unit", "units", "measurement_unit"), default="")[:40]
        raw_val = extract_first(row, ("value", "obs_value", "amount", "size_ha", "hectares"), default="")
        num_val = parse_numeric_value(raw_val)

        lineage = classify_lineage(row, num_val)
        note = extract_first(row, ("notes", "description", "summary", "status"), default="")[:220]

        normalized.append({
            "id": f"landportal-zwe-{idx + 1}",
            "country": "Zimbabwe",
            "indicator": indicator,
            "value": num_val if num_val is not None else (raw_val or None),
            "unit": unit or None,
            "period": period,
            "provider": provider,
            "lineage": lineage,
            "note": note or None,
            "source_url": safe_url,
        })

    # Keep most recent periods first when period looks like a year/date, capped to MAX_RECORDS
    normalized.sort(key=lambda x: str(x.get("period") or ""), reverse=True)
    return normalized[:MAX_RECORDS]


def save_to_telemetry_cache(records, dataset_title, cache_path=CACHE_PATH):
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        if not isinstance(cache, dict):
            raise ValueError("Invalid cache root")
    except Exception:
        cache = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tracked_topics": [],
        }

    existing = cache.get("landportal_zwe_signals", [])
    if not isinstance(existing, list):
        existing = []
    merged_by_key = {}
    for item in existing + records:
        key = f"{item.get('provider')}|{item.get('indicator')}|{item.get('period')}"
        merged_by_key[key] = item

    merged_list = list(merged_by_key.values())
    merged_list.sort(key=lambda x: str(x.get("period") or ""), reverse=True)

    cache["landportal_zwe_signals"] = merged_list[:MAX_RECORDS]
    cache["landportal_updated_at"] = datetime.now(timezone.utc).isoformat()
    cache["landportal_last_dataset"] = dataset_title

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"Stored {len(cache['landportal_zwe_signals'])} Zimbabwe records in {cache_path}.")
    return cache["landportal_zwe_signals"]


def main():
    parser = argparse.ArgumentParser(description="Ingest a Land Portal CSV/JSON dataset for Zimbabwe.")
    parser.add_argument("--file", default="landportal_zimbabwe.csv", help="Path to downloaded Land Portal CSV or JSON file")
    parser.add_argument("--title", default="Land Portal Curated Dataset (Zimbabwe)", help="Dataset title label")
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help="Reference HTTPS source URL")
    parser.add_argument("--cache", default=CACHE_PATH, help="Path to telemetry_cache.json")
    args = parser.parse_args()

    if os.path.exists(args.file):
        parsed = ingest_landportal_dataset(args.file, dataset_title=args.title, source_url=args.url)
        save_to_telemetry_cache(parsed, args.title, cache_path=args.cache)
    else:
        print(f"Place your downloaded Land Portal CSV/JSON at '{args.file}' and re-run.")


if __name__ == "__main__":
    main()
