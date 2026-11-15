#!/usr/bin/env python3
"""
Daily ParlZim & Macro Telemetry Cache Generator for KUVHURA Observatory.

Runs `fetch_parliamentary_policy_tracker(use_cache=False)` (Chrome TLS impersonation
via `curl_cffi` + optional `FLARESOLVERR_URL` + verified ZimLII / Parliamentary RSS
mirror failover on Cloudflare HTTP 403) and writes `telemetry_cache.json`.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from stream_server import (  # noqa: E402
    fetch_layer2_macro_telemetry,
    fetch_parliamentary_policy_tracker,
)


def _load_existing_cache(cache_path: Path):
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def generate_telemetry_cache():
    cache_path = Path(os.environ.get("TELEMETRY_CACHE_PATH", ROOT_DIR / "telemetry_cache.json"))
    previous = _load_existing_cache(cache_path)

    parlzim = fetch_parliamentary_policy_tracker(use_cache=False, allow_mirror_fallback=True)
    macro = fetch_layer2_macro_telemetry(use_cache=False)
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    accessible_sources = int(parlzim.get("accessibleSources") or 0)
    total_sources = int(parlzim.get("totalSources") or 5)
    avg_friction = parlzim.get("score")
    tracked_topics = parlzim.get("tracked_topics") or []

    last_available_parlzim = previous.get("last_available_parlzim")
    if parlzim.get("status") == "available" and avg_friction is not None:
        last_available_parlzim = {
            **parlzim,
            "captured_at": now_iso,
        }

    cache_data = {
        "schema_version": 2,
        "timestamp": now_iso,
        "updated_at": now_iso,
        "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local-cli",
        "accessible_sources": accessible_sources,
        "total_sources": total_sources,
        "hansard_friction": avg_friction,
        "tracked_topics": tracked_topics,
        "status": (
            f"Resolved {accessible_sources}/{total_sources} via CF-free mirrors/live"
            if accessible_sources > 0
            else "Live Crawl Blocked (CF 403)"
        ),
        "parlzim": parlzim,
        "last_available_parlzim": last_available_parlzim,
        "layer2_macro": macro,
    }

    cache_path.write_text(json.dumps(cache_data, indent=2) + "\n", encoding="utf-8")
    print(
        f"Telemetry cache generated successfully ({accessible_sources}/{total_sources} portals accessible, "
        f"score={avg_friction}, topics={len(tracked_topics)})."
    )
    return cache_data


if __name__ == "__main__":
    generate_telemetry_cache()
