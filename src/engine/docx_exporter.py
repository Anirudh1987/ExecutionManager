"""Word document exporter — generates professional advisory reports and redlined contracts.

Three export types:
A. Advisory report: cover page, TOC, recommendation, risks, playbook, regulatory roadmap
B. Redline document: strikethrough/underline markup with margin comments
C. Compliance tracker: post-closing obligations with deadlines
"""

from __future__ import annotations

import io
from datetime import datetime

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from src.models.contract import Contract
from src.models.deal import Deal
from src.models.review import (
    ClauseReview,
    DealContext,
    Review,
    RiskLevel,
)


# Color constants
_RED = RGBColor(0xCC, 0x00, 0x00)
_BLUE = RGBColor(0x00, 0x33, 0xCC)
_GREEN = RGBColor(0x00, 0x66, 0x00)
_ORANGE = RGBColor(0xCC, 0x66, 0x00)
_GRAY = RGBColor(0x66, 0x66, 0x66)

_RISK_COLORS = {
    RiskLevel.CRITICAL: _RED,
    RiskLevel.HIGH: _ORANGE,
    RiskLevel.MEDIUM: RGBColor(0xCC, 0xCC, 0x00),
    RiskLevel.LOW: _GREEN,
    RiskLevel.INFORMATIONAL: _GRAY,
}

_RECOMMENDATION_LABELS = {
    "proceed": "PROCEED",
    "negotiate": "PROCEED WITH NEGOTIATIONS",
    "walk_away": "WALK AWAY / SIGNIFICANT RENEGOTIATION REQUIRED",
}


def _add_heading(doc: Document, text: str, level: int = 1) -> None:
    """Add a heading with Times New Roman font."""
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = "Times New Roman"


def _add_para(doc: Document, text: str, bold: bool = False, color: RGBColor | None = None) -> None:
    """Add a paragraph with consistent formatting."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(11)
    run.bold = bold
    if color:
        run.font.color.rgb = color


def _add_table_row(table, cells: list[str], bold: bool = False) -> None:
    """Add a row to a table with consistent formatting."""
    row = table.add_row()
    for i, text in enumerate(cells):
        cell = row.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        run = p.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(10)
        run.bold = bold


def export_advisory_docx(
    deal: Deal,
    advisory: dict,
    contracts: list[Contract],
    deal_context: DealContext | None = None,
) -> bytes:
    """Export a professional advisory report as a Word document.

    Includes: cover page, recommendation, key risks, negotiation playbook,
    financial exposure, regulatory roadmap, and market benchmarks.
    """
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Times New Roman"
    font.size = Pt(11)

    # --- Cover Page ---
    doc.add_paragraph("")
    doc.add_paragraph("")
    title = doc.add_heading(f"M&A Contract Review", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    subtitle = doc.add_heading(deal.name, level=1)
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

    _add_para(doc, f"Client: {deal.client_name}")
    _add_para(doc, f"Date: {datetime.utcnow().strftime('%B %d, %Y')}")
    if deal_context:
        if deal_context.client_side:
            _add_para(doc, f"Perspective: {deal_context.client_side.upper()}")
        if deal_context.jurisdiction:
            _add_para(doc, f"Jurisdiction: {deal_context.jurisdiction}")
        if deal_context.industry:
            _add_para(doc, f"Industry: {deal_context.industry}")

    _add_para(doc, "CONFIDENTIAL — ATTORNEY-CLIENT PRIVILEGED", bold=True, color=_RED)

    doc.add_page_break()

    # --- Recommendation Badge ---
    recommendation = advisory.get("recommendation", "negotiate")
    rec_label = _RECOMMENDATION_LABELS.get(recommendation, recommendation.upper())
    rec_color = _RED if recommendation == "walk_away" else (_ORANGE if recommendation == "negotiate" else _GREEN)

    _add_heading(doc, "1. Recommendation", level=1)
    _add_para(doc, rec_label, bold=True, color=rec_color)
    _add_para(doc, advisory.get("recommendation_rationale", ""))

    # --- Executive Summary ---
    _add_heading(doc, "2. Executive Summary", level=1)
    _add_para(doc, advisory.get("executive_summary", ""))

    # --- Key Risks ---
    _add_heading(doc, "3. Key Risks", level=1)
    key_risks = advisory.get("key_risks", [])
    if key_risks:
        for risk in key_risks:
            _add_para(doc, f"• {risk}")
    else:
        _add_para(doc, "No significant risks identified.")

    # --- Deal Breakers ---
    deal_breakers = advisory.get("deal_breakers", [])
    if deal_breakers:
        _add_heading(doc, "4. Deal Breakers", level=1)
        for db in deal_breakers:
            _add_para(doc, f"• {db}", color=_RED)

    # --- Missing Clauses ---
    missing = advisory.get("missing_clauses", [])
    if missing:
        _add_heading(doc, "5. Missing Clauses", level=1)
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Clause Type"
        hdr[1].text = "Severity"
        hdr[2].text = "Rationale"
        for m in missing:
            _add_table_row(table, [
                m.get("clause_type", ""),
                m.get("severity", ""),
                m.get("rationale", ""),
            ])

    # --- Negotiation Playbook ---
    playbook = advisory.get("negotiation_playbook", [])
    if playbook:
        _add_heading(doc, "6. Negotiation Playbook", level=1)
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Issue"
        hdr[1].text = "Priority"
        hdr[2].text = "Opening Position"
        hdr[3].text = "Fallback"
        hdr[4].text = "Walk-Away"
        for item in playbook:
            _add_table_row(table, [
                item.get("issue", ""),
                item.get("priority", ""),
                item.get("opening_position", "")[:100],
                item.get("fallback_position", "")[:100],
                item.get("walk_away_point", "")[:100],
            ])

    # --- Financial Exposure ---
    exposure = advisory.get("financial_exposure", {})
    if exposure.get("breakdown"):
        _add_heading(doc, "7. Financial Exposure Analysis", level=1)
        total = exposure.get("estimated_total", 0)
        pct = exposure.get("exposure_percentage")
        _add_para(doc, f"Estimated Total Exposure: ${total:,.0f}")
        if pct is not None:
            _add_para(doc, f"As Percentage of Deal Value: {pct:.1f}%")

        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Clause"
        hdr[1].text = "Risk Level"
        hdr[2].text = "Amount"
        for item in exposure["breakdown"]:
            _add_table_row(table, [
                item.get("clause", ""),
                item.get("risk_level", ""),
                f"${item.get('amount', 0):,.0f}",
            ])

    # --- Regulatory Roadmap ---
    regulatory = advisory.get("regulatory", {})
    approval_seq = regulatory.get("approval_sequence", [])
    if approval_seq:
        _add_heading(doc, "8. Regulatory Approval Roadmap", level=1)
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Step"
        hdr[1].text = "Approval"
        hdr[2].text = "Timeline"
        hdr[3].text = "Dependencies"
        for i, step in enumerate(approval_seq, 1):
            _add_table_row(table, [
                str(i),
                step.get("step", ""),
                step.get("timeline", ""),
                ", ".join(step.get("depends_on", [])),
            ])

    industry_risks = regulatory.get("industry_risks", [])
    if industry_risks:
        _add_heading(doc, "Industry-Specific Regulatory Risks", level=2)
        for risk in industry_risks:
            _add_para(doc, f"• [{risk.get('regulator', '')}] {risk.get('description', '')}")

    # --- Cross-Clause Risks ---
    cross = advisory.get("cross_clause_risks", [])
    if cross:
        _add_heading(doc, "9. Cross-Clause Risk Interactions", level=1)
        for item in cross:
            _add_para(doc, f"• {item}")

    # --- Risk Distribution ---
    dist = advisory.get("risk_distribution", {})
    if dist:
        _add_heading(doc, "10. Risk Distribution Summary", level=1)
        _add_para(doc, f"Total clauses reviewed: {advisory.get('total_clauses_reviewed', 0)}")
        _add_para(doc, f"Human override rate: {advisory.get('human_override_rate', 0):.0%}")
        for level, count in dist.items():
            _add_para(doc, f"  {level.upper()}: {count}")

    # Save to bytes
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def export_redline_docx(
    contract: Contract,
    review: Review,
    deal_context: DealContext | None = None,
    negotiation_round: int = 1,
) -> bytes:
    """Export a redlined contract with AI/human markup and margin comments.

    Strikethrough (red) for problematic text, underline (blue) for suggested
    replacements, with comments explaining legal reasoning.
    """
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Times New Roman"
    font.size = Pt(11)

    # Title
    title = doc.add_heading(f"Redline Markup — {contract.title or contract.filename}", level=0)
    _add_para(doc, f"Contract: {contract.filename}")
    _add_para(doc, f"Negotiation Round: {negotiation_round}")
    _add_para(doc, f"Date: {datetime.utcnow().strftime('%B %d, %Y')}")
    _add_para(doc, "CONFIDENTIAL — ATTORNEY WORK PRODUCT", bold=True, color=_RED)

    doc.add_page_break()

    # Build clause review lookup
    cr_lookup: dict[str, ClauseReview] = {
        cr.clause_id: cr for cr in review.clause_reviews
    }

    for clause in contract.clauses:
        cr = cr_lookup.get(clause.id)

        # Section heading
        risk_label = ""
        risk_color = _GRAY
        if cr:
            risk_level = cr.final_risk_level or cr.ai_risk_level
            risk_label = f" [{risk_level.value.upper()}]"
            risk_color = _RISK_COLORS.get(risk_level, _GRAY)

        _add_heading(doc, f"{clause.section_reference} — {clause.title}{risk_label}", level=2)

        # Original clause text
        p = doc.add_paragraph()
        run = p.add_run(clause.text[:2000])  # Limit for safety
        run.font.name = "Times New Roman"
        run.font.size = Pt(10)
        run.font.color.rgb = _GRAY

        if not cr or not cr.ai_findings:
            continue

        # Findings and suggested revisions
        for finding in cr.ai_findings:
            if finding.suppressed:
                continue

            finding_color = _RISK_COLORS.get(finding.risk_level, _GRAY)

            # Finding description as a comment-style block
            comment_p = doc.add_paragraph()
            comment_p.paragraph_format.left_indent = Inches(0.5)

            marker = comment_p.add_run(f"[{finding.risk_level.value.upper()}] ")
            marker.font.name = "Times New Roman"
            marker.font.size = Pt(9)
            marker.font.color.rgb = finding_color
            marker.bold = True

            desc = comment_p.add_run(finding.title)
            desc.font.name = "Times New Roman"
            desc.font.size = Pt(9)
            desc.bold = True

            if finding.description:
                desc_p = doc.add_paragraph()
                desc_p.paragraph_format.left_indent = Inches(0.5)
                r = desc_p.add_run(finding.description[:300])
                r.font.name = "Times New Roman"
                r.font.size = Pt(9)
                r.font.color.rgb = _GRAY

            # Market context
            if finding.market_comparison:
                market_p = doc.add_paragraph()
                market_p.paragraph_format.left_indent = Inches(0.5)
                m = market_p.add_run(f"Market: {finding.market_comparison[:200]}")
                m.font.name = "Times New Roman"
                m.font.size = Pt(9)
                m.font.italic = True

            # Enforceability note (India-specific)
            if finding.enforceability_note:
                enf_p = doc.add_paragraph()
                enf_p.paragraph_format.left_indent = Inches(0.5)
                e = enf_p.add_run(f"Enforceability: {finding.enforceability_note}")
                e.font.name = "Times New Roman"
                e.font.size = Pt(9)
                e.font.italic = True
                e.font.color.rgb = _ORANGE

            # Suggested revision (blue underline)
            if finding.suggested_revision:
                rev_p = doc.add_paragraph()
                rev_p.paragraph_format.left_indent = Inches(0.5)
                label = rev_p.add_run("Suggested: ")
                label.font.name = "Times New Roman"
                label.font.size = Pt(9)
                label.font.color.rgb = _BLUE
                label.bold = True

                rev_text = rev_p.add_run(finding.suggested_revision[:500])
                rev_text.font.name = "Times New Roman"
                rev_text.font.size = Pt(9)
                rev_text.font.color.rgb = _BLUE
                rev_text.underline = True

        # Human annotations
        for annotation in cr.human_annotations:
            ann_p = doc.add_paragraph()
            ann_p.paragraph_format.left_indent = Inches(0.5)
            label = ann_p.add_run(f"[Human — {annotation.verdict.value.upper()}] ")
            label.font.name = "Times New Roman"
            label.font.size = Pt(9)
            label.font.color.rgb = _GREEN
            label.bold = True

            if annotation.comment:
                c = ann_p.add_run(annotation.comment[:300])
                c.font.name = "Times New Roman"
                c.font.size = Pt(9)

            if annotation.suggested_language:
                lang_p = doc.add_paragraph()
                lang_p.paragraph_format.left_indent = Inches(0.5)
                lt = lang_p.add_run(f"Revised language: {annotation.suggested_language[:500]}")
                lt.font.name = "Times New Roman"
                lt.font.size = Pt(9)
                lt.font.color.rgb = _BLUE
                lt.underline = True

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def export_compliance_tracker_docx(
    deal: Deal,
    advisory: dict,
    deal_context: DealContext | None = None,
) -> bytes:
    """Export a post-closing compliance tracker with deadlines.

    Lists all regulatory filings, approvals, and ongoing obligations
    with timelines and responsible parties.
    """
    doc = Document()

    style = doc.styles["Normal"]
    font = style.font
    font.name = "Times New Roman"
    font.size = Pt(11)

    title = doc.add_heading(f"Post-Closing Compliance Tracker — {deal.name}", level=0)
    _add_para(doc, f"Client: {deal.client_name}")
    _add_para(doc, f"Date: {datetime.utcnow().strftime('%B %d, %Y')}")
    _add_para(doc, "CONFIDENTIAL", bold=True, color=_RED)

    doc.add_page_break()

    # Regulatory approvals
    regulatory = advisory.get("regulatory", {})
    approval_seq = regulatory.get("approval_sequence", [])
    if approval_seq:
        _add_heading(doc, "Pre-Closing Regulatory Approvals", level=1)
        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "#"
        hdr[1].text = "Approval"
        hdr[2].text = "Timeline"
        hdr[3].text = "Status"
        hdr[4].text = "Notes"
        for i, step in enumerate(approval_seq, 1):
            _add_table_row(table, [
                str(i),
                step.get("step", ""),
                step.get("timeline", ""),
                "Pending",
                ", ".join(step.get("depends_on", [])),
            ])

    # Post-closing obligations from regulatory checks
    reg_checks = regulatory.get("checks", [])
    if reg_checks:
        _add_heading(doc, "Post-Closing Obligations", level=1)
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Obligation"
        hdr[1].text = "Legal Basis"
        hdr[2].text = "Risk Level"
        hdr[3].text = "Status"
        for check in reg_checks:
            _add_table_row(table, [
                check.get("title", ""),
                check.get("legal_basis", ""),
                check.get("risk_level", ""),
                "Pending",
            ])

    # Timeline risks from advisory
    timeline_risks = advisory.get("timeline_risks", [])
    if timeline_risks:
        _add_heading(doc, "Timeline Risks", level=1)
        for risk in timeline_risks:
            _add_para(doc, f"• {risk}")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
