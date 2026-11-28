"""
Format spatial pin payloads for map marker rendering.

Guarantees every map marker carries explicit separation between:
  - Site-level extraction gaps (missing quantities from primary filings)
  - Official survey baselines (ZimLAC/FNC provincial surveys)
  - Conceptual classifications (measured vs proxy/estimate)
"""


def format_spatial_pin_payload(record):
    """
    Convert a spatial record into map marker payload with explicit lineage boundaries.
    
    Args:
        record: Dict with keys: id, label, location_name, lat, lon, value, unit, 
                notes, lineage, source_title, source_url, period
    
    Returns:
        Dict with separated extraction status, survey baseline, and epistemic badge.
    """
    qty = record.get("value")
    unit = record.get("unit") or ""
    
    # Explicit separation: site-level extraction quantity vs missing data
    if isinstance(qty, (int, float)):
        site_quantity_text = f"{qty:,} {unit}".strip()
    else:
        site_quantity_text = "No numeric extraction quantity reported in primary filings"
    
    # Determine epistemic badge based on lineage
    if record.get("lineage") == "Measured Directly":
        epistemic_badge = "[Measured Directly — Official Survey]"
    else:
        epistemic_badge = "[Proxy / Estimate — Contextual Survey Baseline]"
    
    return {
        "id": record.get("id"),
        "location_name": record.get("label") or record.get("location_name"),
        "lat": record.get("lat"),
        "lon": record.get("lon"),
        "site_extraction_status": site_quantity_text,
        "survey_baseline": record.get("notes") or "Anchored to ZimLAC/FNC provincial survey baseline",
        "lineage": record.get("lineage", "Proxy / Estimate"),
        "epistemic_badge": epistemic_badge,
        "source_title": record.get("source_title"),
        "source_url": record.get("source_url"),
        "period": record.get("period"),
    }


def filter_spatial_pins_by_lineage(pins, lineage_filter=None):
    """
    Filter spatial pins by lineage type.
    
    Args:
        pins: List of formatted pin payloads from format_spatial_pin_payload()
        lineage_filter: "Measured Directly", "Proxy / Estimate", or None for all
    
    Returns:
        List of pins matching the filter.
    """
    if lineage_filter is None:
        return pins
    return [pin for pin in pins if pin.get("lineage") == lineage_filter]


def build_spatial_pin_collection(raw_records):
    """
    Convert a collection of raw spatial records to formatted pins with lineage separation.
    
    Args:
        raw_records: List of spatial record dicts
    
    Returns:
        Dict with 'all_pins', 'measured_directly', and 'proxy_estimate' lists.
    """
    all_pins = [format_spatial_pin_payload(record) for record in raw_records]
    
    return {
        "all_pins": all_pins,
        "measured_directly": filter_spatial_pins_by_lineage(all_pins, "Measured Directly"),
        "proxy_estimate": filter_spatial_pins_by_lineage(all_pins, "Proxy / Estimate"),
        "total_pins": len(all_pins),
        "measured_count": len([p for p in all_pins if p["lineage"] == "Measured Directly"]),
        "estimate_count": len([p for p in all_pins if p["lineage"] == "Proxy / Estimate"]),
    }
