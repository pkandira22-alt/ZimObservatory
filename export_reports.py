import io
import json
import os
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, request, send_file
from docx import Document
from docx.shared import RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
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


def _partition_records(records):
    extraction = [r for r in records if r.get("domain") == "extraction"]
    spatial = [r for r in records if r.get("domain") in ("spatial", "livelihoods")]
    governance = [r for r in records if r.get("domain") in ("governance", "module")]
    other = [
        r
        for r in records
        if r.get("domain") not in ("extraction", "spatial", "livelihoods", "governance", "module")
    ]
    return extraction, spatial, governance, other


def _build_5page_briefing(cache, audience="layman"):
    """
    Assemble a structured 5-page executive & analytical briefing tailored for
    either 'technical' or 'layman' readers from telemetry_cache.json.
    """
    norm_audience = "technical" if (audience or "").strip().lower() == "technical" else "layman"
    records = cache.get("depth_records") or cache.get("spatial_reports") or []
    streams = cache.get("stochastic_streams") or {}
    updated = (
        cache.get("depth_updated_at")
        or cache.get("timestamp")
        or datetime.now(timezone.utc).isoformat()
    )

    extraction, spatial, governance, other = _partition_records(records)
    direct_count = sum(1 for r in records if r.get("lineage") == "Measured Directly")
    proxy_count = sum(1 for r in records if r.get("lineage") == "Proxy / Estimate")
    bucket_count = sum(1 for r in records if r.get("lineage") == "Conceptual / Analytical Bucket")
    flagged_count = sum(1 for r in records if r.get("audit_flags"))

    is_tech = norm_audience == "technical"

    doc_title = (
        "KUVHURA Observatory: 5-Page Technical Telemetry & Institutional Risk Analysis"
        if is_tech
        else "KUVHURA Observatory: 5-Page Executive Briefing on Zimbabwe's Political Economy"
    )
    subtitle = (
        f"Snapshot Timestamp: {updated} | Mode: Technical & Methodological Audit"
        if is_tech
        else f"Snapshot Timestamp: {updated} | Mode: Plain-Language Executive Briefing"
    )

    # PAGE 1: Executive Summary & Headline Risk Posture
    p1_paragraphs = [
        (
            f"This five-page analytical report synthesizes {len(records)} active telemetry records "
            f"across KUVHURA's extractive, spatial livelihoods, governance, and stochastic uncertainty layers. "
            f"To preserve evidentiary rigor, every indicator is strictly partitioned into primary empirical "
            f"observations ({direct_count} Measured Directly), contextual or derived indicators "
            f"({proxy_count} Proxy / Estimate), and structural classification frameworks "
            f"({bucket_count} Conceptual / Analytical Bucket)."
        ),
        (
            "Core Analytical Finding — Divergence Over Uniformity: Headline national indices mask sharp "
            "sectoral and geographic divergence. In the extractive sector, quarterly contractions in bulk "
            "index readings and base metals coexist with year-on-year resilience in gold and steady quarterly "
            "platinum output along the Great Dyke corridor. Similarly, provincial rural food-security averages "
            "conceal wide district-level dispersion in household income and cereal vulnerability."
            if is_tech
            else "Key Takeaway — Different Sectors Are Moving in Opposite Directions: Looking at one national "
            "headline number hides what is actually happening on the ground. While overall mining output "
            "dipped quarter-on-quarter due to sharp drops in nickel and diamonds, gold remains higher than a "
            "year ago and Great Dyke platinum held steady. The same pattern holds in rural provinces, where "
            "some districts face severe food pressure while neighboring districts show stronger household incomes."
        ),
        (
            "Institutional Bottlenecks & Epistemic Discipline: Legislative friction remains concentrated around "
            "resource-governance statutory reform—most notably Parliamentary Legal Committee (PLC) review bottlenecks "
            "on the Mines and Minerals Bill—while climate legislation has progressed further through parliamentary "
            "readings. Where site-level extraction or sub-ward input figures are not published in primary documents "
            "(such as Gutu North, Masvingo), KUVHURA explicitly preserves a 'no reported quantity' state rather than "
            "imputing synthetic values."
            if is_tech
            else "Laws, Institutions & Honest Data Boundaries: Key mining legislation continues to face legal and "
            "procedural delays in Parliament, whereas climate governance bills have moved closer to completion. "
            "Just as importantly, whenever official reports do not publish a local extraction figure—such as in "
            "Gutu North, Masvingo—this briefing states that openly instead of guessing."
        ),
    ]

    p1_highlights = [
        f"Total Audited Signals: {len(records)} records ({direct_count} Direct, {proxy_count} Proxy/Estimate, {bucket_count} Analytical Buckets).",
        f"Data Hygiene & Audit Flags: {flagged_count} records flagged for missing metadata or range review.",
        f"Active Stochastic Streams: {len(streams)} rolling dispersion and regime-state monitors.",
        "Primary Institutional Anchors: ZIMSTAT IMP releases, ZimLAC/FNC factsheets, and Parliament/Veritas bill trackers.",
    ]

    # PAGE 2: Extractive & Industrial Sector Analysis
    p2_intro = (
        "Sectoral decomposition of ZIMSTAT Index of Mineral Production (IMP) series evaluates both "
        "quarter-on-quarter (QoQ) momentum and year-on-year (YoY) structural trajectory across major corridors."
        if is_tech
        else "Mining remains Zimbabwe's primary foreign-currency anchor, but performance varies widely by mineral "
        "and corridor. Comparing both quarterly and annual changes separates short-term swings from deeper shifts."
    )
    p2_items = extraction or other

    # PAGE 3: Spatial Context & Rural Livelihoods
    p3_intro = (
        "Spatial telemetry integrates approximate geographic centroids with ZimLAC/ZimVAC household vulnerability "
        "and income metrics, enforcing strict separation between provincial survey baselines and locality-level gaps."
        if is_tech
        else "Map pins in KUVHURA represent approximate reference areas rather than exact mine boundaries or sensor feeds. "
        "In rural localities like Gutu North (Masvingo), household survey data provides essential livelihood context "
        "even when site-level extraction quantities are unreported."
    )
    p3_items = spatial

    # PAGE 4: Institutional Governance & Advanced Modules (Components 1-8)
    p4_intro = (
        "Legislative stage-friction telemetry tracks procedural bottlenecks across resource and environmental bills, "
        "feeding KUVHURA's Advanced Institutional Modules (Components 1–8: Asset Flight & Debt, Digital Repression [Sf], "
        "Strike Funds & Legal, Gender & Vulnerability [Vg], and Historical Backtesting & Climate)."
        if is_tech
        else "Beyond production numbers, political-economy stability depends on how laws move through Parliament and how "
        "institutional pressures interact. KUVHURA's eight analytical modules break these pressures down into specific "
        "areas—such as legal bottlenecks, debt and capital flight, digital controls, gender vulnerability, and climate shocks."
    )
    p4_items = governance

    # PAGE 5: Stochastic Uncertainty Layer, Methodology & Full Audit Matrix
    p5_intro = (
        "Stochastic Telemetry Specification: Rather than relying on deterministic point forecasts, KUVHURA tracks "
        "rolling 10-observation sample standard deviation (volatility_std_10) alongside exponentially weighted "
        "moving averages (alpha = 0.2, capped at 30 historical points). Regime classifications (Contained, Elevated "
        "Friction, Acute Stress, Unclassified / Stale) function strictly as [Conceptual / Analytical Buckets]."
        if is_tech
        else "How Uncertainty Is Measured: Real-world political and economic data arrives unevenly and contains sudden spikes. "
        "Instead of reacting to every single jump, KUVHURA tracks both how much a signal fluctuates (volatility) and "
        "its smoothed trend, grouping conditions into clear stages: Contained, Elevated Friction, or Acute Stress."
    )

    stream_rows = []
    for key, s in streams.items():
        if not isinstance(s, dict):
            continue
        stream_rows.append(
            {
                "stream": key,
                "raw": s.get("latest_raw"),
                "smoothed": s.get("smoothed_value"),
                "std_10": s.get("volatility_std_10"),
                "regime": s.get("regime", "Unclassified"),
                "status": s.get("status", "unknown"),
            }
        )

    return {
        "title": doc_title,
        "subtitle": subtitle,
        "updated": updated,
        "audience": norm_audience,
        "is_tech": is_tech,
        "page1": {"paragraphs": p1_paragraphs, "highlights": p1_highlights},
        "page2": {"title": "2. Extractive & Industrial Corridor Analysis", "intro": p2_intro, "items": p2_items},
        "page3": {"title": "3. Spatial Context, Rural Livelihoods & Agricultural Inputs", "intro": p3_intro, "items": p3_items},
        "page4": {"title": "4. Legislative Friction & Institutional Modules (Components 1–8)", "intro": p4_intro, "items": p4_items},
        "page5": {
            "title": "5. Stochastic Uncertainty Layer, Methodology & Audit Register",
            "intro": p5_intro,
            "streams": stream_rows,
            "all_records": records,
        },
    }


def _format_record_text(r, is_tech):
    label = r.get("label") or r.get("location_name") or "Indicator"
    val = r.get("value", r.get("quantity"))
    unit = r.get("unit") or ""
    period = r.get("period") or "unspecified"
    lineage = r.get("lineage") or "Proxy / Estimate"
    src = r.get("source_title") or "Cited source"
    val_disp = (
        f"{val:,} {unit}".strip()
        if isinstance(val, (int, float)) and not isinstance(val, bool)
        else "No numeric quantity reported"
    )

    if is_tech:
        extra = []
        if r.get("qoq_pct") is not None:
            extra.append(f"QoQ: {r['qoq_pct']:+.1f}%")
        if r.get("yoy_pct") is not None:
            extra.append(f"YoY: {r['yoy_pct']:+.1f}%")
        extra_str = f" ({', '.join(extra)})" if extra else ""
        return (
            f"[{lineage}] Observed: {val_disp}{extra_str} | Period: {period} | "
            f"Status: {r.get('status', 'cached')} | Source: {src}. "
            f"Analytical Note: {r.get('notes') or r.get('explanation') or 'N/A'}"
        )
    return r.get("explanation") or f"{label}: {val_disp} ({period}, {lineage}) via {src}."


def _generate_docx(briefing):
    doc = Document()
    is_tech = briefing["is_tech"]

    # --- PAGE 1 ---
    doc.add_heading(briefing["title"], level=0)
    sub = doc.add_paragraph(briefing["subtitle"])
    if sub.runs:
        sub.runs[0].font.color.rgb = RGBColor(90, 98, 110)

    doc.add_heading("1. Executive Summary & Headline Risk Posture", level=1)
    for para in briefing["page1"]["paragraphs"]:
        doc.add_paragraph(para)

    doc.add_heading("Key Snapshot Metrics", level=2)
    for h in briefing["page1"]["highlights"]:
        doc.add_paragraph(h, style="List Bullet")

    # --- PAGES 2, 3, 4 ---
    for page_key in ("page2", "page3", "page4"):
        doc.add_page_break()
        section = briefing[page_key]
        doc.add_heading(section["title"], level=1)
        doc.add_paragraph(section["intro"])

        items = section["items"]
        if not items:
            doc.add_paragraph("No active records in this domain for the current cache snapshot.")
        else:
            for r in items:
                heading_txt = f"{r.get('label') or r.get('location_name')} [{r.get('lineage', 'Proxy / Estimate')}]"
                doc.add_heading(heading_txt, level=2)
                doc.add_paragraph(_format_record_text(r, is_tech))

    # --- PAGE 5 ---
    doc.add_page_break()
    p5 = briefing["page5"]
    doc.add_heading(p5["title"], level=1)
    doc.add_paragraph(p5["intro"])

    doc.add_heading("Stochastic Volatility & Regime State Table", level=2)
    streams = p5["streams"]
    if streams:
        tbl = doc.add_table(rows=1, cols=6)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        for idx, col_name in enumerate(["Stream", "Raw", "Smoothed", "Volatility (Std10)", "Regime", "Status"]):
            hdr[idx].text = col_name
        for s in streams:
            row = tbl.add_row().cells
            row[0].text = str(s["stream"])
            row[1].text = str(s["raw"])
            row[2].text = str(s["smoothed"])
            row[3].text = str(s["std_10"])
            row[4].text = str(s["regime"])
            row[5].text = str(s["status"])
    else:
        doc.add_paragraph("No stochastic streams populated in current snapshot.")

    doc.add_heading("Source Lineage & Audit Register", level=2)
    reg_tbl = doc.add_table(rows=1, cols=4)
    reg_tbl.style = "Table Grid"
    rhdr = reg_tbl.rows[0].cells
    for idx, col_name in enumerate(["Indicator / Locality", "Period", "Lineage Tag", "Primary Source"]):
        rhdr[idx].text = col_name
    for r in p5["all_records"]:
        row = reg_tbl.add_row().cells
        row[0].text = str(r.get("label") or r.get("location_name") or "")
        row[1].text = str(r.get("period") or "N/A")
        row[2].text = str(r.get("lineage") or "Proxy / Estimate")
        row[3].text = str(r.get("source_title") or "Cited source")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def _generate_pdf(briefing):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()
    sub_style = ParagraphStyle(
        "SubMeta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "BodySpaced",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14,
        spaceAfter=8,
    )
    is_tech = briefing["is_tech"]

    story = [
        Paragraph(xml_escape(briefing["title"]), styles["Title"]),
        Paragraph(xml_escape(briefing["subtitle"]), sub_style),
        Paragraph("1. Executive Summary &amp; Headline Risk Posture", styles["Heading1"]),
    ]
    for para in briefing["page1"]["paragraphs"]:
        story.append(Paragraph(xml_escape(para), body_style))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Key Snapshot Metrics", styles["Heading2"]))
    for h in briefing["page1"]["highlights"]:
        story.append(Paragraph(f"• {xml_escape(h)}", body_style))

    for page_key in ("page2", "page3", "page4"):
        story.append(PageBreak())
        section = briefing[page_key]
        story.append(Paragraph(xml_escape(section["title"]), styles["Heading1"]))
        story.append(Paragraph(xml_escape(section["intro"]), body_style))
        story.append(Spacer(1, 6))

        items = section["items"]
        if not items:
            story.append(Paragraph("No active records in this domain for the current snapshot.", body_style))
        else:
            for r in items:
                label = r.get("label") or r.get("location_name") or "Indicator"
                lineage = r.get("lineage") or "Proxy / Estimate"
                story.append(
                    Paragraph(
                        f"<b>{xml_escape(str(label))}</b> [{xml_escape(str(lineage))}]",
                        styles["Heading3"],
                    )
                )
                story.append(Paragraph(xml_escape(_format_record_text(r, is_tech)), body_style))

    # --- PAGE 5 ---
    story.append(PageBreak())
    p5 = briefing["page5"]
    story.append(Paragraph(xml_escape(p5["title"]), styles["Heading1"]))
    story.append(Paragraph(xml_escape(p5["intro"]), body_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Stochastic Volatility &amp; Regime State Summary", styles["Heading2"]))

    if p5["streams"]:
        s_data = [["Stream", "Raw", "Smoothed", "Std(10)", "Regime", "Status"]]
        for s in p5["streams"]:
            s_data.append(
                [
                    str(s["stream"]),
                    str(s["raw"]),
                    str(s["smoothed"]),
                    str(s["std_10"]),
                    str(s["regime"]),
                    str(s["status"]),
                ]
            )
        s_tbl = Table(s_data, colWidths=[125, 55, 65, 60, 110, 85])
        s_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("PADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.append(s_tbl)
    else:
        story.append(Paragraph("No stochastic streams populated in current snapshot.", body_style))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Source Lineage &amp; Audit Register", styles["Heading2"]))
    r_data = [["Indicator / Locality", "Period", "Lineage", "Source"]]
    for r in p5["all_records"]:
        r_data.append(
            [
                str(r.get("label") or r.get("location_name") or "")[:42],
                str(r.get("period") or "N/A")[:18],
                str(r.get("lineage") or "Proxy / Estimate")[:28],
                str(r.get("source_title") or "Cited source")[:38],
            ]
        )
    r_tbl = Table(r_data, colWidths=[165, 75, 120, 140])
    r_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(r_tbl)

    doc.build(story)
    buf.seek(0)
    return buf


def _generate_xlsx(cache):
    wb = Workbook()
    ws_data = wb.active
    ws_data.title = "Recorded_Telemetry"

    headers = [
        "ID",
        "Domain",
        "Label",
        "Value",
        "Unit",
        "QoQ %",
        "YoY %",
        "Period",
        "Lineage",
        "Status",
        "Source Title",
        "Source URL",
        "Explanation",
        "Updated At",
    ]
    ws_data.append(headers)
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws_data[1]:
        cell.fill = header_fill
        cell.font = header_font

    updated = (
        cache.get("depth_updated_at")
        or cache.get("timestamp")
        or datetime.now(timezone.utc).isoformat()
    )
    records = cache.get("depth_records") or cache.get("spatial_reports") or []
    for r in records:
        ws_data.append(
            [
                r.get("id", ""),
                r.get("domain", ""),
                r.get("label") or r.get("location_name") or "",
                r.get("value", r.get("quantity")),
                r.get("unit", ""),
                r.get("qoq_pct"),
                r.get("yoy_pct"),
                r.get("period", ""),
                r.get("lineage", ""),
                r.get("status", ""),
                r.get("source_title") or r.get("source") or "",
                r.get("source_url", ""),
                r.get("explanation") or r.get("notes") or "",
                r.get("updated_at", updated),
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

    for key, s in (cache.get("stochastic_streams") or {}).items():
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
                s.get("updated_at", updated),
            ]
        )

    for ws in (ws_data, ws_st):
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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")

    if fmt == "pdf":
        briefing = _build_5page_briefing(cache, audience=audience)
        buf = _generate_pdf(briefing)
        return send_file(
            buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"kuvhura_5page_briefing_{audience}_{stamp}.pdf",
        )
    if fmt == "docx":
        briefing = _build_5page_briefing(cache, audience=audience)
        buf = _generate_docx(briefing)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name=f"kuvhura_5page_briefing_{audience}_{stamp}.docx",
        )
    if fmt == "xlsx":
        buf = _generate_xlsx(cache)
        return send_file(
            buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"kuvhura_telemetry_data_{stamp}.xlsx",
        )

    return {"error": "Unsupported format. Use format=pdf, docx, or xlsx."}, 400
