#!/usr/bin/env python3
"""ZIMSTAT mining production telemetry extraction and spatial feed sync.

Fetches ZIMSTAT Index of Mineral Production (IMP) PDF, extracts quarterly
commodity quantities, and maintains a cache of spatial extraction reports
for the interactive map UI.
"""

import io
import json
import os
import re
from datetime import datetime, timezone

try:
    from curl_cffi import requests as cureq
except ImportError:
    import requests as cureq

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


CACHE_PATH = "telemetry_cache.json"
ZIMSTAT_IMP_PDF_URL = os.environ.get(
    "ZIMSTAT_IMP_PDF_URL",
    "https://www.zimstat.co.zw/wp-content/uploads/production/Mining/2026/Q1/IMP_2026_Q1.pdf",
)

# Approximate reference coordinates for map pins (not exact incident coordinates)
PIN_COORDS = {
    "great_dyke": {
        "name": "Great Dyke Corridor",
        "lat": -18.85,
        "lon": 30.15,
    },
    "midlands_gold": {
        "name": "Midlands / Gold Corridors",
        "lat": -18.92,
        "lon": 29.82,
    },
    "gutu_north": {
        "name": "Gutu North, Masvingo",
        "lat": -19.43,
        "lon": 31.18,
    },
}


def fetch_zimstat_pdf_metrics(pdf_url=ZIMSTAT_IMP_PDF_URL):
    """Stream ZIMSTAT IMP PDF in memory and extract cited quarterly output figures.
    
    Returns:
        list: Extraction items with quantity, location, and source metadata.
    """
    items = []
    try:
        if not PdfReader:
            print("Warning: pypdf not installed; skipping PDF extraction")
            return items

        resp = cureq.get(pdf_url, timeout=25)
        if resp.status_code != 200:
            print(f"ZIMSTAT PDF fetch returned {resp.status_code}")
            return items

        reader = PdfReader(io.BytesIO(resp.content))
        text = re.sub(
            r"\s+",
            " ",
            "\n".join(p.extract_text() or "" for p in reader.pages),
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        # Platinum extraction
        plat_m = re.search(
            r"Platinum.*?Q1\s*['']?26\s*([\d,]+)",
            text,
            re.IGNORECASE,
        )
        if plat_m:
            items.append({
                "id": "zimstat-plat-q1-2026",
                "location_key": "great_dyke",
                "location_name": PIN_COORDS["great_dyke"]["name"],
                "lat": PIN_COORDS["great_dyke"]["lat"],
                "lon": PIN_COORDS["great_dyke"]["lon"],
                "category": "Mining Extraction",
                "commodity": "Platinum",
                "quantity": int(plat_m.group(1).replace(",", "")),
                "unit": "kg",
                "period": "Q1 2026",
                "lineage": "Measured Directly",
                "source_title": "ZIMSTAT Index of Mineral Production (Q1 2026)",
                "source_url": pdf_url,
                "fetched_at": now_iso,
            })

        # Gold extraction
        gold_m = re.search(
            r"Gold.*?Q1\s*['']?26\s*([\d,]+)",
            text,
            re.IGNORECASE,
        )
        if gold_m:
            items.append({
                "id": "zimstat-gold-q1-2026",
                "location_key": "midlands_gold",
                "location_name": PIN_COORDS["midlands_gold"]["name"],
                "lat": PIN_COORDS["midlands_gold"]["lat"],
                "lon": PIN_COORDS["midlands_gold"]["lon"],
                "category": "Mining Extraction",
                "commodity": "Gold",
                "quantity": int(gold_m.group(1).replace(",", "")),
                "unit": "kg",
                "period": "Q1 2026",
                "lineage": "Measured Directly",
                "source_title": "ZIMSTAT Index of Mineral Production (Q1 2026)",
                "source_url": pdf_url,
                "fetched_at": now_iso,
            })

        # Nickel extraction
        nickel_m = re.search(
            r"from\s*4,100mt\s*in\s*4th\s*quarter\s*2025\s*to\s*([\d,]+)mt",
            text,
            re.IGNORECASE,
        )
        if nickel_m:
            items.append({
                "id": "zimstat-nickel-q1-2026",
                "location_key": "great_dyke",
                "location_name": PIN_COORDS["great_dyke"]["name"],
                "lat": PIN_COORDS["great_dyke"]["lat"],
                "lon": PIN_COORDS["great_dyke"]["lon"],
                "category": "Mining Extraction",
                "commodity": "Nickel",
                "quantity": int(nickel_m.group(1).replace(",", "")),
                "unit": "metric tons",
                "period": "Q1 2026",
                "lineage": "Measured Directly",
                "source_title": "ZIMSTAT Index of Mineral Production (Q1 2026)",
                "source_url": pdf_url,
                "fetched_at": now_iso,
            })

    except Exception as exc:
        print(f"ZIMSTAT PDF fetch error: {exc}")

    return items


def build_curated_context_entries():
    """Source-attributed context entries (no fabricated quantities when unreported)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": "gutu-north-livelihoods-context",
            "location_key": "gutu_north",
            "location_name": PIN_COORDS["gutu_north"]["name"],
            "lat": PIN_COORDS["gutu_north"]["lat"],
            "lon": PIN_COORDS["gutu_north"]["lon"],
            "category": "Rural Livelihoods & Inputs",
            "commodity": None,
            "quantity": None,
            "unit": None,
            "period": "2025–2026",
            "lineage": "Proxy / Estimate",
            "note": "No site-level extraction quantity reported; district/provincial livelihoods & input context.",
            "source_title": "ZimLAC / ZimVAC Rural Livelihoods Assessment (Masvingo)",
            "source_url": "https://www.fnc.org.zw/documents/",
            "fetched_at": now_iso,
        }
    ]


def sync_spatial_feed(cache_path=CACHE_PATH):
    """Fetch and cache ZIMSTAT extraction metrics and curated context entries."""
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tracked_topics": [],
        }

    live_extraction = fetch_zimstat_pdf_metrics()
    context_entries = build_curated_context_entries()

    # Keep only verified items with explicit source URLs; deduplicate by id
    combined = {
        item["id"]: item
        for item in (context_entries + live_extraction)
        if item.get("source_url")
    }
    cache["spatial_reports"] = list(combined.values())
    cache["extraction_reports"] = [
        r for r in combined.values() if r.get("quantity") is not None
    ]
    cache["spatial_updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(
        f"Synced {len(cache['spatial_reports'])} spatial items "
        f"({len(cache['extraction_reports'])} with quantities)."
    )
    return cache


if __name__ == "__main__":
    cache = sync_spatial_feed()
    print(json.dumps(cache, indent=2))
