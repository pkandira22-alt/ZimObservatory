#!/usr/bin/env python3
"""KUVHURA Depth & Stochastic Telemetry Pipeline.

Integrates four high-rigor empirical and analytical layers into telemetry_cache.json:
1. ZIMSTAT Q1 2026 IMP Mineral Divergence (QoQ & YoY, [Measured Directly])
2. ZimLAC 2025 Masvingo & Gutu Livelihood Contrasts ([Measured Directly] & [Proxy / Estimate])
3. Parliamentary Bill Lifecycle & PLC Bottleneck Friction ([Conceptual / Analytical Bucket])
4. Stochastic Rolling Volatility, Exponential Smoothing & Regime Classification
"""

import io
import json
import math
import os
import re
import urllib.request
from datetime import datetime, timezone

try:
    from curl_cffi import requests as cureq
except ImportError:
    cureq = None

try:
    import requests as _std_requests
except ImportError:
    _std_requests = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from telemetry_audit import audit_and_partition_records

CACHE_PATH = "telemetry_cache.json"
ZIMSTAT_IMP_Q1_2026_URL = os.environ.get(
    "ZIMSTAT_IMP_PDF_URL",
    "https://www.zimstat.co.zw/wp-content/uploads/production/Mining/2026/Q1/IMP_2026_Q1.pdf",
)


def _sample_std(values):
    clean = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    var = sum((x - mean) ** 2 for x in clean) / (len(clean) - 1)
    return round(math.sqrt(var), 4)


def _smooth_step(history, current_val, alpha=0.2):
    if current_val is None:
        return history[-1] if history else None
    val = float(current_val)
    if not history:
        return round(val, 4)
    return round((alpha * val) + ((1.0 - alpha) * float(history[-1])), 4)


def _regime_bucket(smoothed_val, volatility):
    if smoothed_val is None:
        return "Unclassified / Stale"
    vol = volatility or 0.0
    if smoothed_val >= 70.0 or (smoothed_val >= 55.0 and vol >= 12.0):
        return "Acute Stress"
    if smoothed_val >= 40.0 or vol >= 6.0:
        return "Elevated Friction"
    return "Contained"


def _fetch_pdf_bytes(url, timeout=15):
    if cureq is not None:
        resp = cureq.get(url, impersonate="chrome", timeout=timeout)
        return resp.status_code, resp.content
    if _std_requests is not None:
        resp = _std_requests.get(
            url,
            headers={"User-Agent": "KUVHURA-Observatory/1.0"},
            timeout=timeout,
        )
        return resp.status_code, resp.content
    req = urllib.request.Request(url, headers={"User-Agent": "KUVHURA-Observatory/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return getattr(resp, "status", 200), resp.read()


def build_mineral_divergence_records(pdf_url=ZIMSTAT_IMP_Q1_2026_URL, live_fetch=True):
    """
    1. ZIMSTAT Q1 2026 IMP QoQ & YoY mineral divergence ([Measured Directly]).
    Attempts live PDF parse first; falls back to verified Q1 2026 release figures if needed.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "id": "zimstat-imp-overall-q1-2026",
            "label": "ZIMSTAT Index of Mineral Production (Overall)",
            "domain": "extraction",
            "commodity": "Overall Mineral Index",
            "value": 134.9,
            "quantity": 134.9,
            "formatted_quantity": "134.9 index (Q1 2026)",
            "unit": "index_2019_100",
            "period": "Q1 2026",
            "qoq_pct": -33.2,
            "yoy_pct": -5.3,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Down 33.2% QoQ from 201.8 in Q4 2025 and down 5.3% YoY from 142.4 in Q1 2025.",
            "updated_at": now_iso,
        },
        {
            "id": "zimstat-gold-q1-2026",
            "label": "Gold Output (National)",
            "domain": "extraction",
            "location_key": "midlands_gold",
            "location_name": "Midlands / Gold Corridors",
            "location": "Midlands / Gold Corridors",
            "lat": -18.92,
            "lon": 29.82,
            "commodity": "Gold",
            "value": 9894,
            "quantity": 9894,
            "formatted_quantity": "9,894 kg (Q1 2026)",
            "unit": "kg",
            "period": "Q1 2026",
            "index_val": 142.1,
            "qoq_pct": -32.8,
            "yoy_pct": 10.2,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Output fell from 14,731 kg in Q4 2025 (-32.8% index QoQ), while YoY index rose +10.2% vs Q1 2025.",
            "updated_at": now_iso,
        },
        {
            "id": "zimstat-platinum-q1-2026",
            "label": "Platinum Output (Great Dyke / National)",
            "domain": "extraction",
            "location_key": "great_dyke",
            "location_name": "Great Dyke Corridor",
            "location": "Great Dyke Corridor",
            "lat": -18.85,
            "lon": 30.15,
            "commodity": "Platinum (PGMs)",
            "value": 3807,
            "quantity": 3807,
            "formatted_quantity": "3,807 kg (Q1 2026)",
            "unit": "kg",
            "period": "Q1 2026",
            "index_val": 111.4,
            "qoq_pct": 2.5,
            "yoy_pct": -8.9,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Q1 2026 output at 3,807 kg vs 3,716 kg in Q4 2025 (+2.5% index QoQ; -8.9% YoY vs Q1 2025).",
            "updated_at": now_iso,
        },
        {
            "id": "zimstat-diamond-q1-2026",
            "label": "Diamond Production Index",
            "domain": "extraction",
            "location_key": "marange_diamonds",
            "location_name": "Marange / Chiadzwa Diamond Fields",
            "location": "Marange / Chiadzwa Diamond Fields",
            "lat": -19.58,
            "lon": 32.42,
            "commodity": "Diamond Index",
            "value": 95.1,
            "quantity": 95.1,
            "formatted_quantity": "95.1 index (Q1 2026)",
            "unit": "index_2019_100",
            "period": "Q1 2026",
            "qoq_pct": -23.9,
            "yoy_pct": -43.9,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Down 23.9% QoQ from 124.9 in Q4 2025 and down 43.9% YoY from 169.6 in Q1 2025.",
            "updated_at": now_iso,
        },
        {
            "id": "zimstat-nickel-q1-2026",
            "label": "Nickel Output",
            "domain": "extraction",
            "location_key": "great_dyke",
            "location_name": "Great Dyke Corridor",
            "location": "Great Dyke Corridor",
            "lat": -18.85,
            "lon": 30.15,
            "commodity": "Nickel",
            "value": 1486,
            "quantity": 1486,
            "formatted_quantity": "1,486 metric tons (Q1 2026)",
            "unit": "metric tons",
            "period": "Q1 2026",
            "index_val": 33.6,
            "qoq_pct": -63.8,
            "yoy_pct": -52.0,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Dropped from 4,100 mt in Q4 2025 to 1,486 mt in Q1 2026 (-63.8% QoQ; -52.0% YoY).",
            "updated_at": now_iso,
        },
    ]

    if live_fetch and PdfReader is not None:
        try:
            status_code, content = _fetch_pdf_bytes(pdf_url, timeout=12)
            if status_code == 200 and content:
                reader = PdfReader(io.BytesIO(content))
                text = re.sub(r"\s+", " ", "\n".join(p.extract_text() or "" for p in reader.pages))
                overall_m = re.search(
                    r"stood at\s*([\d.]+),\s*reflecting a year-\s*on-year percentage decrease of\s*([\d.]+)",
                    text,
                    re.IGNORECASE,
                )
                if overall_m:
                    val = float(overall_m.group(1))
                    records[0]["value"] = val
                    records[0]["quantity"] = val
                    records[0]["status"] = "live"
                    records[0]["updated_at"] = now_iso
        except Exception:
            pass

    return records


def build_masvingo_gutu_livelihood_records():
    """
    2. ZimLAC 2025 Masvingo & Gutu district contrasts ([Measured Directly] for
    reported survey figures; [Proxy / Estimate] when applied to Gutu North locality).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    src_url = "https://www.fnc.org.zw/wp-content/uploads/2026/01/Masvingo-ZimLAC-2025-Rural-Livelihoods-Assessment-Factsheet.pdf"
    return [
        {
            "id": "gutu-north-spatial-context",
            "label": "Gutu North, Masvingo — Spatial & Livelihood Context",
            "domain": "spatial",
            "location_key": "gutu_north",
            "location_name": "Gutu North, Masvingo",
            "location": "Gutu North, Masvingo",
            "commodity": "Rural Livelihoods & Inputs",
            "value": None,
            "quantity": None,
            "formatted_quantity": "No site extraction quantity reported",
            "unit": None,
            "period": "2025–2026",
            "lat": -19.43,
            "lon": 31.18,
            "lineage": "Proxy / Estimate",
            "status": "no_reported_quantity",
            "source_title": "ZimLAC 2025 Masvingo Province Factsheet (FNC)",
            "source_url": src_url,
            "notes": (
                "No site-level mineral extraction quantity reported for Gutu North. "
                "Masvingo provincial projected cereal insecurity (Jan–Mar 2026): 15% (vs Zaka 35%, Mwenezi 25%); "
                "Gutu April 2025 avg monthly household income: USD 222 (vs Bikita USD 68); "
                "provincial income anchors: casual labour 48%, domestic remittances 29%, crop production 21%."
            ),
            "updated_at": now_iso,
        },
        {
            "id": "zimlac-masvingo-cereal-insecurity-2026",
            "label": "Masvingo Projected Cereal Insecurity (Jan–Mar 2026)",
            "domain": "livelihoods",
            "value": 15.0,
            "unit": "pct",
            "period": "Jan–Mar 2026",
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZimLAC 2025 Masvingo Province Factsheet (FNC)",
            "source_url": src_url,
            "notes": "Provincial average masks higher projected district shares in Zaka (35%) and Mwenezi (25%).",
            "updated_at": now_iso,
        },
        {
            "id": "zimlac-gutu-avg-income-2025",
            "label": "Gutu District Avg Monthly Household Income (Apr 2025)",
            "domain": "livelihoods",
            "value": 222.0,
            "unit": "usd",
            "period": "Apr 2025",
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZimLAC 2025 Masvingo Province Factsheet (FNC)",
            "source_url": src_url,
            "notes": "Highest among surveyed Masvingo districts in April 2025 (compared to USD 68 in Bikita).",
            "updated_at": now_iso,
        },
    ]


def build_legislative_friction_records():
    """
    3. Parliamentary bill lifecycle & PLC bottleneck tracking ([Conceptual / Analytical Bucket]
    for stage-friction mapping; [Measured Directly] for published bill status).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    src_url = "https://www.veritaszim.net/node/8059"
    bills = [
        (
            "bill-hb1-2025-mines-minerals",
            "Mines and Minerals Bill (H.B. 1, 2025)",
            72.0,
            "National Assembly considering adverse report from Parliamentary Legal Committee (PLC).",
        ),
        (
            "bill-hb5a-2025-climate-change",
            "Climate Change Management Bill (H.B. 5A, 2025)",
            35.0,
            "Passed final reading in the Senate; lower residual stage friction than PLC-stalled bills.",
        ),
        (
            "bill-hb5-2026-ema-amendment",
            "Environmental Management Amendment Bill (H.B. 5, 2026)",
            45.0,
            "Bill proofs sent to Attorney-General's Office; awaiting final enactment steps.",
        ),
    ]
    out = []
    for bid, name, friction_idx, stage_note in bills:
        out.append({
            "id": bid,
            "label": f"Legislative Stage Friction — {name}",
            "domain": "governance",
            "value": friction_idx,
            "unit": "score_0_100",
            "period": "Aug–Nov 2026",
            "lineage": "Conceptual / Analytical Bucket",
            "status": "cached",
            "source_title": "Parliamentary Bill Status Tracker (Veritas / Parliament)",
            "source_url": src_url,
            "notes": stage_note,
            "updated_at": now_iso,
        })
    return out


def attach_explanations(records):
    for rec in records:
        val = rec.get("value")
        unit = rec.get("unit") or ""
        label = rec.get("label", "Indicator")
        period = rec.get("period", "N/A")
        src = rec.get("source_title", "cited source")
        lineage = rec.get("lineage", "Proxy / Estimate")

        if val is not None:
            fmt_val = f"{val:,.4f}".rstrip("0").rstrip(".") if isinstance(val, float) else f"{val:,}"
            s1 = f"{label} is recorded at {fmt_val} {unit}".strip() + f" ({period}) from {src}."
        else:
            s1 = f"{label} has no numeric quantity reported for {period} from {src}."

        if lineage == "Measured Directly":
            s2 = "Labeled [Measured Directly] as an explicit reported figure from the cited source."
        elif lineage == "Conceptual / Analytical Bucket":
            s2 = "Labeled [Conceptual / Analytical Bucket] because it structures institutional/procedural stages rather than acting as a direct physical measurement."
        else:
            s2 = "Labeled [Proxy / Estimate] because it provides contextual or indirect inference rather than a direct locality measurement."

        rec["explanation"] = f"{s1} {s2}"
    return records


def update_stochastic_layer(cache, stream_key, raw_val, alpha=0.2, max_hist=30):
    """
    4. Stochastic rolling volatility + exponential smoothing + regime bucket.
    """
    streams = cache.setdefault("stochastic_streams", {})
    entry = streams.get(
        stream_key,
        {
            "history": [],
            "smoothed_history": [],
            "lineage_smoothed": "Proxy / Estimate",
            "lineage_regime": "Conceptual / Analytical Bucket",
        },
    )

    if raw_val is not None:
        hist = list(entry.get("history", []))
        hist.append(float(raw_val))
        hist = hist[-max_hist:]

        smoothed = _smooth_step(entry.get("smoothed_history", []), float(raw_val), alpha=alpha)
        shist = list(entry.get("smoothed_history", []))
        if smoothed is not None:
            shist.append(smoothed)
            shist = shist[-max_hist:]

        vol = _sample_std(hist[-10:])
        entry.update({
            "latest_raw": float(raw_val),
            "history": hist,
            "smoothed_value": smoothed,
            "smoothed_history": shist,
            "volatility_std_10": vol,
            "regime": _regime_bucket(smoothed, vol),
            "status": "online",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        entry.update({
            "status": "stale_or_offline",
            "regime": _regime_bucket(entry.get("smoothed_value"), entry.get("volatility_std_10")),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        })

    streams[stream_key] = entry


def run_depth_pipeline(cache_path=CACHE_PATH, live_fetch=True):
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {"timestamp": datetime.now(timezone.utc).isoformat(), "tracked_topics": []}

    minerals = attach_explanations(build_mineral_divergence_records(live_fetch=live_fetch))
    livelihoods = attach_explanations(build_masvingo_gutu_livelihood_records())
    legislative = attach_explanations(build_legislative_friction_records())

    all_depth_records = minerals + livelihoods + legislative
    partitioned = audit_and_partition_records(all_depth_records)

    cache["depth_records"] = all_depth_records
    cache["audited_telemetry"] = partitioned
    cache["extraction_reports"] = [
        r for r in minerals if r.get("quantity") is not None and r.get("location_key")
    ]
    cache["spatial_reports"] = [
        r for r in (minerals + livelihoods) if "lat" in r or r["domain"] == "extraction"
    ]

    # Feed dispersion/volatility into stochastic streams (e.g., absolute QoQ swings on minerals & bill friction)
    qoq_magnitudes = [abs(m["qoq_pct"]) for m in minerals if m.get("qoq_pct") is not None]
    avg_qoq_swing = round(sum(qoq_magnitudes) / len(qoq_magnitudes), 2) if qoq_magnitudes else None
    update_stochastic_layer(cache, "mineral_qoq_dispersion", avg_qoq_swing)

    max_bill_friction = max((b["value"] for b in legislative if b.get("value") is not None), default=None)
    update_stochastic_layer(cache, "legislative_plc_friction", max_bill_friction)

    cache["depth_updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(all_depth_records)} depth records and updated stochastic streams in {cache_path}.")
    return cache


if __name__ == "__main__":
    run_depth_pipeline()
