"""Decomposes raw contract text into atomic clauses using AI."""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from src.models.contract import Clause, ClauseType, Contract


# Structural patterns that signal clause boundaries
_SECTION_PATTERNS = [
    "ARTICLE",
    "SECTION",
    "Article",
    "Section",
]


def extract_clauses(contract: Contract) -> list[Clause]:
    """Split a contract into reviewable clauses.

    Uses a hybrid approach:
    1. Structural splitting on section headers
    2. AI-based classification of each section's clause type

    For the initial implementation, we use structural splitting.
    The AI classification step is handled by the analyzer.
    """
    if not contract.raw_text:
        return []

    sections = _split_into_sections(contract.raw_text)
    clauses = []

    for i, (title, text) in enumerate(sections):
        clause = Clause(
            contract_id=contract.id,
            clause_type=_infer_clause_type(title, text),
            title=title,
            text=text,
            section_reference=title,
            page_number=_estimate_page(i, len(sections), contract.page_count),
        )
        clauses.append(clause)

    # Link related clauses (e.g., indemnification references reps & warranties)
    _link_related_clauses(clauses)

    return clauses


def _split_into_sections(text: str) -> list[tuple[str, str]]:
    """Split contract text into (title, body) pairs at section boundaries."""
    lines = text.split("\n")
    sections: list[tuple[str, str]] = []
    current_title = "Preamble"
    current_body: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _is_section_header(stripped):
            if current_body:
                body_text = "\n".join(current_body).strip()
                if body_text:
                    sections.append((current_title, body_text))
            current_title = stripped
            current_body = []
        else:
            current_body.append(line)

    # Don't forget the last section
    if current_body:
        body_text = "\n".join(current_body).strip()
        if body_text:
            sections.append((current_title, body_text))

    return sections


def _is_section_header(line: str) -> bool:
    """Check if a line looks like a section/article header."""
    if not line:
        return False
    for pattern in _SECTION_PATTERNS:
        if line.startswith(pattern):
            return True
    # Numbered sections like "1.", "1.1", "2.3.1"
    parts = line.split(".", 1)
    if parts[0].strip().isdigit() and len(line) < 200:
        return True
    return False


def _infer_clause_type(title: str, text: str) -> ClauseType:
    """Keyword-based clause type inference as a fast first pass.

    The AI analyzer will refine this classification.
    """
    combined = (title + " " + text[:500]).lower()

    type_keywords: dict[ClauseType, list[str]] = {
        ClauseType.REPRESENTATIONS_WARRANTIES: [
            "represent", "warrant", "representation", "warranty",
        ],
        ClauseType.INDEMNIFICATION: [
            "indemnif", "hold harmless", "indemnity",
        ],
        ClauseType.CONDITIONS_PRECEDENT: [
            "condition", "conditions precedent", "conditions to closing",
        ],
        ClauseType.COVENANTS: [
            "covenant", "shall not", "agrees to", "undertakes",
        ],
        ClauseType.TERMINATION: [
            "terminat", "expir", "break fee", "reverse break",
        ],
        ClauseType.PURCHASE_PRICE: [
            "purchase price", "consideration", "payment",
        ],
        ClauseType.CLOSING_MECHANICS: [
            "closing", "settlement", "completion",
        ],
        ClauseType.NON_COMPETE: [
            "non-compete", "noncompete", "restrictive covenant", "non-solicitation",
        ],
        ClauseType.CONFIDENTIALITY: [
            "confidential", "non-disclosure", "nda",
        ],
        ClauseType.INTELLECTUAL_PROPERTY: [
            "intellectual property", "patent", "trademark", "copyright", "license",
        ],
        ClauseType.EMPLOYEE_MATTERS: [
            "employee", "benefit", "pension", "severance", "retention",
        ],
        ClauseType.TAX: [
            "tax", "withholding", "transfer tax",
        ],
        ClauseType.GOVERNING_LAW: [
            "governing law", "jurisdiction", "applicable law",
        ],
        ClauseType.DISPUTE_RESOLUTION: [
            "arbitration", "dispute", "mediation",
        ],
        ClauseType.MATERIAL_ADVERSE_CHANGE: [
            "material adverse", "mac", "mae",
        ],
        ClauseType.EARNOUT: [
            "earnout", "earn-out", "contingent consideration",
        ],
        ClauseType.ESCROW: [
            "escrow", "holdback",
        ],
    }

    for clause_type, keywords in type_keywords.items():
        if any(kw in combined for kw in keywords):
            return clause_type

    return ClauseType.OTHER


def _estimate_page(section_index: int, total_sections: int, page_count: int) -> int:
    """Rough page number estimate based on position in document."""
    if page_count == 0 or total_sections == 0:
        return 0
    return max(1, int((section_index / total_sections) * page_count))


def _link_related_clauses(clauses: list[Clause]) -> None:
    """Detect cross-references between clauses and link them."""
    clause_map = {c.section_reference.lower(): c.id for c in clauses}

    for clause in clauses:
        text_lower = clause.text.lower()
        for ref, clause_id in clause_map.items():
            if clause_id == clause.id:
                continue
            # Simple cross-reference detection
            if ref and ref in text_lower:
                clause.related_clause_ids.append(clause_id)
