#!/usr/bin/env python3
"""KUVHURA Telemetry Data-Lineage & Sanity Auditing Module.

Provides single source-of-truth audited records with explicit lineage tags,
unit sanity bounds, source URL validation, honesty downgrades, plain-language
explanations, and partitioning into direct vs. proxy/conceptual buckets.
"""

from datetime import datetime, timezone
from urllib.parse import urlparse

VALID_LINEAGES = {
    "Measured Directly",
    "Proxy / Estimate",
    "Conceptual / Analytical Bucket",
}

VALID_STATUSES = {
    "live",
    "cached",
    "stale",
    "offline",
    "no_reported_quantity",
}

# Sanity bounds for common units to catch extraction/OCR glitches early
UNIT_BOUNDS = {
    "kg": (0.0, 500_000_000.0),
    "metric tons": (0.0, 50_000_000.0),
    "oz": (0.0, 500_000_000.0),
    "pct": (-100.0, 10_000.0),
    "score_0_100": (0.0, 100.0),
}


def _is_valid_url(url):
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _normalize_lineage(raw_lineage, has_direct_value=False):
    if raw_lineage in VALID_LINEAGES:
        return raw_lineage
    lowered = (raw_lineage or "").strip().lower()
    if "direct" in lowered or "measured" in lowered:
        return "Measured Directly" if has_direct_value else "Proxy / Estimate"
    if "conceptual" in lowered or "bucket" in lowered or "regime" in lowered:
        return "Conceptual / Analytical Bucket"
    return "Proxy / Estimate"


def _check_value_sanity(value, unit):
    """Return (is_sane, reason) for numeric observations."""
    if value is None:
        return True, None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False, "non_numeric_value"
    if value != value or value in (float("inf"), float("-inf")):
        return False, "non_finite_value"

    norm_unit = (unit or "").strip().lower()
    if norm_unit in UNIT_BOUNDS:
        lo, hi = UNIT_BOUNDS[norm_unit]
        if value < lo or value > hi:
            return False, f"out_of_bounds_for_{norm_unit}({value})"
    return True, None


def build_audited_record(
    record_id,
    label,
    domain,
    value=None,
    unit=None,
    period=None,
    lineage=None,
    status="cached",
    source_title=None,
    source_url=None,
    notes=None,
    updated_at=None,
):
    """
    Create a single source-of-truth audited record with explicit lineage,
    source attribution, status, and plain-language explanation.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    has_num = isinstance(value, (int, float)) and not isinstance(value, bool)
    clean_lineage = _normalize_lineage(lineage, has_direct_value=has_num)

    # Enforce honesty: if Measured Directly has no value, downgrade to Proxy / Estimate
    if clean_lineage == "Measured Directly" and not has_num and value is None:
        clean_lineage = "Proxy / Estimate"

    is_sane, sanity_issue = _check_value_sanity(value, unit)
    clean_status = status if status in VALID_STATUSES else "cached"

    if not is_sane:
        clean_status = "stale"
        effective_value = None
    else:
        effective_value = value

    if effective_value is None and clean_status == "live":
        clean_status = "no_reported_quantity"

    source_ok = _is_valid_url(source_url)
    audit_flags = []
    if not source_ok:
        audit_flags.append("missing_or_invalid_source_url")
    if not source_title:
        audit_flags.append("missing_source_title")
    if not period:
        audit_flags.append("missing_period")
    if sanity_issue:
        audit_flags.append(sanity_issue)

    record = {
        "id": str(record_id).strip(),
        "label": str(label).strip(),
        "domain": str(domain).strip(),  # e.g., "extraction", "spatial", "macro", "module"
        "value": effective_value,
        "unit": unit,
        "period": period or "unspecified",
        "lineage": clean_lineage,
        "status": clean_status,
        "source_title": source_title or "Unsourced Entry",
        "source_url": source_url if source_ok else None,
        "notes": notes,
        "audit_flags": audit_flags,
        "updated_at": updated_at or now_iso,
    }
    record["explanation"] = explain_record(record)
    return record


def explain_record(record):
    """
    Generate a concise, two-part plain-language explanation of what the record
    shows and how much evidentiary weight it carries.
    """
    label = record.get("label", "Record")
    val = record.get("value")
    unit = record.get("unit") or ""
    period = record.get("period", "unspecified period")
    lineage = record.get("lineage", "Proxy / Estimate")
    status = record.get("status", "cached")
    source_title = record.get("source_title", "cited source")

    if val is not None:
        val_str = f"{val:,.4f}".rstrip("0").rstrip(".") if isinstance(val, float) else f"{val:,}"
        part_one = f"{label} is recorded at {val_str} {unit}".strip() + f" ({period}) via {source_title} [status: {status}]."
    else:
        part_one = f"{label} has no reported numeric quantity for {period} via {source_title} [status: {status}]."

    if lineage == "Measured Directly":
        part_two = "Tagged [Measured Directly] because it comes from a cited primary or official report without estimation."
    elif lineage == "Conceptual / Analytical Bucket":
        part_two = "Tagged [Conceptual / Analytical Bucket] because it organizes structural regimes or categories rather than acting as a direct physical measurement."
    else:
        part_two = "Tagged [Proxy / Estimate] because it relies on an indirect indicator, derived adjustment, or non-direct observation."

    return f"{part_one} {part_two}"


def audit_and_partition_records(records):
    """
    Validate a list of records and partition into:
    - measured_directly: strictly [Measured Directly] with valid numeric values
    - proxy_and_buckets: [Proxy / Estimate] and [Conceptual / Analytical Bucket]
    - flagged_for_review: any item with audit warnings (e.g., missing source URL or sanity issue)
    """
    direct = []
    derived_or_bucket = []
    flagged = []

    for raw in records:
        rec = build_audited_record(
            record_id=raw.get("id", "unknown"),
            label=raw.get("label") or raw.get("location_name") or raw.get("commodity") or "Untitled",
            domain=raw.get("domain", "general"),
            value=raw.get("value", raw.get("quantity")),
            unit=raw.get("unit"),
            period=raw.get("period"),
            lineage=raw.get("lineage"),
            status=raw.get("status", "cached"),
            source_title=raw.get("source_title"),
            source_url=raw.get("source_url"),
            notes=raw.get("notes") or raw.get("note") or raw.get("context"),
            updated_at=raw.get("updated_at"),
        )
        if rec["lineage"] == "Measured Directly" and rec["value"] is not None:
            direct.append(rec)
        else:
            derived_or_bucket.append(rec)

        if rec["audit_flags"]:
            flagged.append(rec)

    return {
        "measured_directly": direct,
        "proxy_and_buckets": derived_or_bucket,
        "flagged_for_review": flagged,
    }


if __name__ == "__main__":
    sample_inputs = [
        {
            "id": "plat-q1-2026",
            "label": "Great Dyke Corridor — Platinum",
            "domain": "extraction",
            "value": 3807,
            "unit": "kg",
            "period": "Q1 2026",
            "lineage": "Measured Directly",
            "status": "live",
            "source_title": "ZIMSTAT Index of Mineral Production Q1 2026",
            "source_url": "https://www.zimstat.co.zw/wp-content/uploads/production/Mining/2026/Q1/IMP_2026_Q1.pdf",
        },
        {
            "id": "gutu-north-livelihoods",
            "label": "Gutu North, Masvingo — Rural Livelihoods",
            "domain": "spatial",
            "value": None,
            "unit": None,
            "period": "2025–2026",
            "lineage": "Proxy / Estimate",
            "status": "no_reported_quantity",
            "source_title": "ZimLAC / ZimVAC Masvingo Context",
            "source_url": "https://www.fnc.org.zw/documents/",
        },
        {
            "id": "mod-2-digital-repression",
            "label": "Component 2: Digital Repression (Sf)",
            "domain": "module",
            "value": 58.0,
            "unit": "score_0_100",
            "period": "Q4 2026",
            "lineage": "Conceptual / Analytical Bucket",
            "status": "cached",
            "source_title": "KUVHURA Analytical Module Definition",
            "source_url": "https://kuvhura.org/methodology",
        },
    ]

    result = audit_and_partition_records(sample_inputs)
    for bucket_name, items in result.items():
        print(f"=== {bucket_name} ({len(items)}) ===")
        for item in items:
            print("-", item["explanation"])
