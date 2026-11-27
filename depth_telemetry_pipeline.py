import io
import json
import math
import re
from datetime import datetime, timezone
try:
    from curl_cffi import requests as cureq
except ImportError:
    cureq = None
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

CACHE_PATH = "telemetry_cache.json"
ZIMSTAT_IMP_Q1_2026_URL = (
    "https://www.zimstat.co.zw/wp-content/uploads/production/Mining/2026/Q1/IMP_2026_Q1.pdf"
)


def _sample_std(values):
    clean = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(clean) < 2:
        return 0.0
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


def build_extractive_records(pdf_url=ZIMSTAT_IMP_Q1_2026_URL):
    """ZIMSTAT Q1 2026 IMP series ([Measured Directly])."""
    now_iso = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "id": "zimstat-imp-overall-q1-2026",
            "label": "ZIMSTAT Index of Mineral Production (Overall)",
            "domain": "extraction",
            "value": 134.9,
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
            "value": 9894,
            "unit": "kg",
            "period": "Q1 2026",
            "qoq_pct": -32.8,
            "yoy_pct": 10.2,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Output fell from 14,731 kg in Q4 2025 (-32.8% index QoQ), while YoY index rose +10.2%.",
            "updated_at": now_iso,
        },
        {
            "id": "zimstat-platinum-q1-2026",
            "label": "Platinum Output (Great Dyke / National)",
            "domain": "extraction",
            "value": 3807,
            "unit": "kg",
            "period": "Q1 2026",
            "qoq_pct": 2.5,
            "yoy_pct": -8.9,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": pdf_url,
            "notes": "Q1 2026 output at 3,807 kg vs 3,716 kg in Q4 2025 (+2.5% index QoQ; -8.9% YoY).",
            "updated_at": now_iso,
        },
        {
            "id": "zimstat-nickel-q1-2026",
            "label": "Nickel Output",
            "domain": "extraction",
            "value": 1486,
            "unit": "metric tons",
            "period": "Q1 2026",
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

    try:
        resp = cureq.get(pdf_url, impersonate="chrome", timeout=20)
        if resp.status_code == 200:
            reader = PdfReader(io.BytesIO(resp.content))
            text = re.sub(r"\s+", " ", "\n".join(p.extract_text() or "" for p in reader.pages))
            m = re.search(r"stood at\s*([\d.]+),\s*reflecting a year- on-year", text, re.IGNORECASE)
            if m:
                records[0]["value"] = float(m.group(1))
                records[0]["status"] = "live"
                records[0]["updated_at"] = now_iso
    except Exception:
        pass

    return records


def build_macro_fiscal_records():
    """
    Non-ZIMSTAT direct empirical anchors from RBZ & Ministry of Finance
    to eliminate single-source dependency on ZIMSTAT.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    return [
        {
            "id": "mofed-imtt-zig-rate-2026",
            "label": "IMTT Electronic Transaction Tax Rate (ZiG)",
            "domain": "macro_fiscal",
            "value": 1.25,
            "unit": "pct",
            "period": "2026 Budget",
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "Ministry of Finance 2026 National Budget Statement",
            "source_url": "https://www.zimtreasury.gov.zw/",
            "notes": "Intermediated Money Transfer Tax reduced to 1.25% on ZiG transactions (1.75% on FX).",
            "updated_at": now_iso,
        },
        {
            "id": "mofed-pit-threshold-2026",
            "label": "Monthly Tax-Free PAYE Threshold (USD)",
            "domain": "macro_fiscal",
            "value": 150.0,
            "unit": "usd",
            "period": "2026 Budget",
            "qoq_pct": 50.0,
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "Ministry of Finance 2026 National Budget Statement",
            "source_url": "https://www.zimtreasury.gov.zw/",
            "notes": "Raised from USD 100 to USD 150/month to cushion formal wage earners.",
            "updated_at": now_iso,
        },
        {
            "id": "rbz-policy-rate-anchor-2026",
            "label": "RBZ Bank Policy Rate Anchor",
            "domain": "macro_fiscal",
            "value": 35.0,
            "unit": "pct",
            "period": "H2 2026",
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "Reserve Bank of Zimbabwe Monetary Policy Disclosures",
            "source_url": "https://www.rbz.co.zw/",
            "notes": "Tight liquidity stance maintained to anchor ZiG stability and curb parallel spread.",
            "updated_at": now_iso,
        },
    ]


def build_spatial_livelihood_records():
    """ZimLAC / FNC provincial & district anchors."""
    now_iso = datetime.now(timezone.utc).isoformat()
    src_url = "https://www.fnc.org.zw/wp-content/uploads/2026/01/Masvingo-ZimLAC-2025-Rural-Livelihoods-Assessment-Factsheet.pdf"
    return [
        {
            "id": "gutu-north-spatial-context",
            "label": "Gutu North, Masvingo — Spatial & Livelihood Context",
            "domain": "spatial",
            "value": None,
            "unit": None,
            "period": "2025–2026",
            "lat": -19.43,
            "lon": 31.18,
            "lineage": "Proxy / Estimate",
            "status": "no_reported_quantity",
            "source_title": "ZimLAC 2025 Masvingo Province Factsheet (FNC)",
            "source_url": src_url,
            "notes": (
                "No site-level extraction quantity reported. Provincial cereal insecurity: 15% "
                "(vs Zaka 35%, Mwenezi 25%); Gutu avg monthly household income: USD 222 (vs Bikita USD 68)."
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


def build_governance_records():
    """
    Separates empirical parliamentary stage milestones ([Measured Directly])
    from conceptual stage-friction buckets ([Conceptual / Analytical Bucket]).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    src_url = "https://www.veritaszim.net/node/8059"
    return [
        {
            "id": "parl-hb1-2025-plc-stage",
            "label": "Mines and Minerals Bill (H.B. 1, 2025) — Parliamentary Stage",
            "domain": "governance",
            "value": 2,
            "unit": "stage_code",
            "period": "Aug–Nov 2026",
            "lineage": "Measured Directly",
            "status": "cached",
            "source_title": "Parliamentary Bill Status Tracker (Veritas / Parliament)",
            "source_url": src_url,
            "notes": "Empirical status: Referred to National Assembly following Parliamentary Legal Committee (PLC) adverse report.",
            "updated_at": now_iso,
        },
        {
            "id": "bill-hb1-2025-mines-minerals",
            "label": "Legislative Stage Friction — Mines and Minerals Bill (H.B. 1, 2025)",
            "domain": "module",
            "value": 72.0,
            "unit": "score_0_100",
            "period": "Aug–Nov 2026",
            "lineage": "Conceptual / Analytical Bucket",
            "status": "cached",
            "source_title": "KUVHURA Component 6 (Legal) & Veritas Tracker",
            "source_url": src_url,
            "notes": "Elevated procedural friction due to unresolved PLC constitutional/legal objections.",
            "updated_at": now_iso,
        },
        {
            "id": "bill-hb5a-2025-climate-change",
            "label": "Legislative Stage Friction — Climate Change Management Bill (H.B. 5A, 2025)",
            "domain": "module",
            "value": 35.0,
            "unit": "score_0_100",
            "period": "Aug–Nov 2026",
            "lineage": "Conceptual / Analytical Bucket",
            "status": "cached",
            "source_title": "KUVHURA Component 8 (Climate) & Veritas Tracker",
            "source_url": src_url,
            "notes": "Passed final reading in Senate; low residual legislative bottleneck.",
            "updated_at": now_iso,
        },
    ]


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
            s2 = "Tagged [Measured Directly] because it comes from a cited primary or official report without estimation."
        elif lineage == "Conceptual / Analytical Bucket":
            s2 = "Tagged [Conceptual / Analytical Bucket] because it structures institutional or procedural regimes rather than acting as a direct physical measurement."
        else:
            s2 = "Tagged [Proxy / Estimate] because it provides contextual or indirect inference rather than a direct locality measurement."

        rec["explanation"] = f"{s1} {s2}"
    return records


def update_stochastic_layer(cache, stream_key, raw_val, alpha=0.2, max_hist=30, seed_series=None):
    """
    Ensures rolling history, exponential smoothing, and Std(10) stay mathematically
    consistent even on initial runs.
    """
    streams = cache.setdefault("stochastic_streams", {})
    entry = streams.get(stream_key, {
        "history": list(seed_series) if seed_series else [],
        "smoothed_history": [],
        "lineage_smoothed": "Proxy / Estimate",
        "lineage_regime": "Conceptual / Analytical Bucket",
    })

    if raw_val is not None:
        hist = list(entry.get("history", []))
        hist.append(float(raw_val))
        hist = hist[-max_hist:]

        # Recompute smoothed series consistently across history
        smoothed_hist = []
        for idx, pt in enumerate(hist):
            if idx == 0:
                smoothed_hist.append(round(pt, 4))
            else:
                smoothed_hist.append(round((alpha * pt) + ((1.0 - alpha) * smoothed_hist[-1]), 4))

        smoothed = smoothed_hist[-1]
        vol = _sample_std(hist[-10:])
        entry.update({
            "latest_raw": round(float(raw_val), 4),
            "history": hist,
            "smoothed_value": smoothed,
            "smoothed_history": smoothed_hist,
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


def run_depth_pipeline(cache_path=CACHE_PATH):
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {"timestamp": datetime.now(timezone.utc).isoformat(), "tracked_topics": []}

    extractive = attach_explanations(build_extractive_records())
    macro_fiscal = attach_explanations(build_macro_fiscal_records())
    spatial = attach_explanations(build_spatial_livelihood_records())
    governance = attach_explanations(build_governance_records())

    all_depth_records = extractive + macro_fiscal + spatial + governance
    cache["depth_records"] = all_depth_records
    cache["extraction_reports"] = [r for r in extractive if r.get("value") is not None]
    cache["spatial_reports"] = [r for r in (extractive + spatial) if "lat" in r or r["domain"] == "extraction"]

    qoq_magnitudes = [abs(m["qoq_pct"]) for m in extractive if m.get("qoq_pct") is not None]
    avg_qoq_swing = round(sum(qoq_magnitudes) / len(qoq_magnitudes), 2) if qoq_magnitudes else None
    update_stochastic_layer(cache, "mineral_qoq_dispersion", avg_qoq_swing)

    bucket_scores = [
        g["value"]
        for g in governance
        if g.get("lineage") == "Conceptual / Analytical Bucket" and g.get("value") is not None
    ]
    max_bill_friction = max(bucket_scores, default=None)
    update_stochastic_layer(cache, "legislative_plc_friction", max_bill_friction)

    cache["depth_updated_at"] = datetime.now(timezone.utc).isoformat()

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(all_depth_records)} rebalanced depth records to {cache_path}.")


# Backwards-compatible aliases
build_mineral_divergence_records = build_extractive_records
build_zimlac_livelihoods_records = build_spatial_livelihood_records
build_parliament_legislative_records = build_governance_records


if __name__ == "__main__":
    run_depth_pipeline()
