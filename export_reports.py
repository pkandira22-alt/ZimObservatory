import io
import json
import os
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, request, send_file
from docx import Document
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

export_bp = Blueprint("export_bp", __name__)
CACHE_PATH = os.environ.get("TELEMETRY_CACHE_PATH", "telemetry_cache.json")


def _load_cache():
    cache = {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                cache = loaded
    except Exception:
        cache = {}

    if not cache.get("depth_records") and not cache.get("spatial_reports"):
        try:
            from depth_telemetry_pipeline import (
                build_mineral_divergence_records,
                build_zimlac_livelihoods_records,
                build_parliament_legislative_records,
                update_stochastic_layer,
            )

            records = (
                build_mineral_divergence_records()
                + build_zimlac_livelihoods_records()
                + build_parliament_legislative_records()
            )
            cache.setdefault("depth_records", records)
            cache.setdefault("depth_updated_at", datetime.now(timezone.utc).isoformat())
            if not cache.get("stochastic_streams"):
                update_stochastic_layer(cache, records)
        except Exception:
            pass

    return cache


def _build_narrative_sections(cache, audience="layman"):
    """Return structured report sections tailored for 'technical' or 'layman' readers."""
    norm_audience = "technical" if (audience or "").strip().lower() == "technical" else "layman"
    records = cache.get("depth_records") or cache.get("spatial_reports") or []
    streams = cache.get("stochastic_streams") or {}
    updated = cache.get("depth_updated_at") or cache.get("timestamp") or datetime.now(timezone.utc).isoformat()

    direct_count = sum(1 for r in records if r.get("lineage") == "Measured Directly")
    proxy_count = sum(1 for r in records if r.get("lineage") == "Proxy / Estimate")
    bucket_count = sum(1 for r in records if r.get("lineage") == "Conceptual / Analytical Bucket")

    if norm_audience == "technical":
        title = "KUVHURA Technical Telemetry & Methodological Audit Report"
        intro = (
            f"Generated {updated}. This technical briefing details observed primary indicators, "
            f"derived proxies, analytical regime classifications, and stochastic dispersion parameters "
            f"from KUVHURA's rolling telemetry cache ({direct_count} Measured Directly, "
            f"{proxy_count} Proxy / Estimate, {bucket_count} Conceptual / Analytical Bucket)."
        )
        methodology = (
            "Epistemic Governance & Stochastic Layer: Primary figures are validated against source URLs "
            "and unit sanity bounds before ingestion. Exponential smoothing (alpha=0.2) and rolling 10-period "
            "sample standard deviations classify systemic stress regimes (Contained, Elevated Friction, Acute Stress) "
            "without altering raw reported values."
        )
    else:
        title = "KUVHURA Public Briefing: Zimbabwe Political Economy & Livelihoods"
        intro = (
            f"Report date: {updated}. This plain-language briefing summarizes what official statistics, "
            f"parliamentary tracking, and household vulnerability surveys currently show across Zimbabwe. "
            f"Every figure is labeled clearly to show whether it is an official measurement ({direct_count}), "
            f"a tracked estimate ({proxy_count}), or an analytical risk classification ({bucket_count})."
        )
        methodology = (
            "How to Read This Briefing: Direct measurements come straight from official statistical bulletins "
            "and published surveys. Estimates and risk labels help highlight where prices, mining output, "
            "food security, or new laws are shifting quickly, while separating hard data from analysis."
        )

    items = []
    for r in records:
        label = r.get("label") or r.get("title") or r.get("id") or "Unnamed Indicator"
        lineage = r.get("lineage") or "Proxy / Estimate"
        val = r.get("value")
        unit = r.get("unit") or ""
        period = r.get("period") or "Current"
        status = r.get("status") or "cached"
        src_title = r.get("source_title") or r.get("source") or "KUVHURA Registry"
        src_url = r.get("source_url") or ""
        explanation = r.get("explanation") or ""

        if norm_audience == "technical":
            val_str = f"{val} {unit}".strip() if val is not None else "No numeric quantity reported"
            detail = (
                f"[{lineage} | Status: {status} | Period: {period}] Value: {val_str}. "
                f"Source: {src_title} ({src_url}). {explanation}"
            ).strip()
        else:
            val_str = f"{val} {unit}".strip() if val is not None else "Qualitative / tracked update"
            detail = (
                f"Category: {lineage} ({period}). Current reading: {val_str}. "
                f"{explanation} Source: {src_title}."
            ).strip()

        items.append({"heading": str(label), "body": detail, "raw": r})

    stream_notes = []
    for key, s in streams.items():
        if not isinstance(s, dict):
            continue
        regime = s.get("regime", "Unclassified")
        smoothed = s.get("smoothed_value")
        vol = s.get("volatility_std_10")
        raw_v = s.get("latest_raw")
        if norm_audience == "technical":
            stream_notes.append(
                f"{key}: raw={raw_v}, smoothed(a=0.2)={smoothed}, rolling_std_10={vol}, regime={regime}."
            )
        else:
            stream_notes.append(
                f"{key.replace('_', ' ').title()}: Currently assessed as '{regime}' "
                f"(smoothed index: {smoothed}; volatility band: {vol})."
            )

    return {
        "title": title,
        "updated": updated,
        "audience": norm_audience,
        "intro": intro,
        "methodology": methodology,
        "items": items,
        "stream_notes": stream_notes,
        "records": records,
        "streams": streams,
    }


def _generate_pdf(report):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=42,
        bottomMargin=42,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph(xml_escape(report["title"]), styles["Title"]),
        Spacer(1, 8),
        Paragraph(xml_escape(report["intro"]), styles["BodyText"]),
        Spacer(1, 10),
        Paragraph("1. Methodology &amp; Data Lineage", styles["Heading2"]),
        Paragraph(xml_escape(report["methodology"]), styles["BodyText"]),
        Spacer(1, 12),
        Paragraph("2. Recorded Signals &amp; Explanations", styles["Heading2"]),
    ]

    for item in report["items"]:
        story.append(Paragraph(f"<b>{xml_escape(item['heading'])}</b>", styles["Heading4"]))
        story.append(Paragraph(xml_escape(item["body"]), styles["BodyText"]))
        story.append(Spacer(1, 6))

    if report["stream_notes"]:
        story.append(Spacer(1, 10))
        story.append(Paragraph("3. Volatility &amp; Regime State Summary", styles["Heading2"]))
        table_data = [["Stream / Metric", "Summary"]]
        for note in report["stream_notes"]:
            parts = note.split(":", 1)
            table_data.append(
                [
                    Paragraph(xml_escape(parts[0].strip()), styles["BodyText"]),
                    Paragraph(
                        xml_escape(parts[1].strip() if len(parts) > 1 else note),
                        styles["BodyText"],
                    ),
                ]
            )
        tbl = Table(table_data, colWidths=[150, 355])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(tbl)

    doc.build(story)
    buf.seek(0)
    return buf


def _generate_docx(report):
    doc = Document()
    doc.add_heading(report["title"], level=0)
    doc.add_paragraph(report["intro"])

    doc.add_heading("1. Methodology & Data Lineage", level=1)
    doc.add_paragraph(report["methodology"])

    doc.add_heading("2. Recorded Signals & Explanations", level=1)
    for item in report["items"]:
        doc.add_heading(item["heading"], level=2)
        doc.add_paragraph(item["body"])

    if report["stream_notes"]:
        doc.add_heading("3. Volatility & Regime State Summary", level=1)
        for note in report["stream_notes"]:
            doc.add_paragraph(note, style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def _generate_xlsx(report):
    wb = Workbook()
    ws_rec = wb.active
    ws_rec.title = "Recorded_Telemetry"

    headers = [
        "ID",
        "Domain",
        "Label",
        "Value",
        "Unit",
        "Period",
        "Lineage",
        "Status",
        "Source Title",
        "Source URL",
        "Explanation",
        "Updated At",
    ]
    ws_rec.append(headers)
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws_rec[1]:
        cell.fill = header_fill
        cell.font = header_font

    for r in report["records"]:
        ws_rec.append(
            [
                r.get("id", ""),
                r.get("domain", ""),
                r.get("label") or r.get("title") or "",
                r.get("value"),
                r.get("unit", ""),
                r.get("period", ""),
                r.get("lineage", ""),
                r.get("status", ""),
                r.get("source_title") or r.get("source") or "",
                r.get("source_url", ""),
                r.get("explanation", ""),
                r.get("updated_at", report["updated"]),
            ]
        )

    ws_st = wb.create_sheet(title="Stochastic_Streams")
    st_headers = [
        "Stream Key",
        "Latest Raw",
        "Smoothed Value",
        "Volatility (Std 10)",
        "Regime",
        "Status",
        "Updated At",
    ]
    ws_st.append(st_headers)
    for cell in ws_st[1]:
        cell.fill = header_fill
        cell.font = header_font

    for key, s in (report["streams"] or {}).items():
        if not isinstance(s, dict):
            continue
        ws_st.append(
            [
                key,
                s.get("latest_raw"),
                s.get("smoothed_value"),
                s.get("volatility_std_10"),
                s.get("regime", ""),
                s.get("status", ""),
                s.get("updated_at", report["updated"]),
            ]
        )

    for ws in (ws_rec, ws_st):
        for col in ws.columns:
            max_len = max((len(str(c.value or "")) for c in col), default=12)
            ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 48)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@export_bp.route("/api/export", methods=["GET"])
def export_telemetry():
    fmt = (request.args.get("format") or "pdf").strip().lower()
    audience = (request.args.get("audience") or "layman").strip().lower()
    if audience not in ("technical", "layman"):
        audience = "layman"

    cache = _load_cache()
    report = _build_narrative_sections(cache, audience=audience)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")

    if fmt == "pdf":
        buf = _generate_pdf(report)
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"kuvhura_report_{audience}_{stamp}.pdf",
        )
    if fmt == "docx":
        buf = _generate_docx(report)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=f"kuvhura_report_{audience}_{stamp}.docx",
        )
    if fmt == "xlsx":
        buf = _generate_xlsx(report)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"kuvhura_telemetry_data_{stamp}.xlsx",
        )

    return {"error": "Unsupported format. Use format=pdf, docx, or xlsx."}, 400
