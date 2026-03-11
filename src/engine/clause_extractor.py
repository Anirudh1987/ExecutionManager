"""Decomposes raw contract text into atomic clauses using hierarchical parsing.

Supports nested numbering patterns common in M&A contracts:
  Article X → Section X.Y → X.Y.Z → (a) → (i)

Also extracts defined terms and resolves cross-references between clauses.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from src.models.contract import Clause, ClauseType, Contract


# Hierarchy patterns: (compiled regex, depth_level)
HIERARCHY_PATTERNS = [
    (re.compile(r'^ARTICLE\s+([IVXLC\d]+)\.?\s*', re.IGNORECASE), 0),
    (re.compile(r'^Section\s+(\d+(?:\.\d+)*)\s*', re.IGNORECASE), 1),
    (re.compile(r'^(\d+\.\d+\.\d+(?:\.\d+)*)\s'), 2),
    (re.compile(r'^(\d+\.\d+)\s'), 1),
    (re.compile(r'^(\d+)\.\s'), 0),
]

# Patterns that indicate schedule/exhibit sections
_SCHEDULE_PATTERN = re.compile(
    r'^(Schedule|Exhibit|Annex|Appendix)\s+([A-Z\d]+)',
    re.IGNORECASE,
)

# Pattern for defined terms: "Term" means... or "Term" shall mean...
_DEFINED_TERM_PATTERN = re.compile(
    r'"([A-Z][A-Za-z\s]+?)"\s+(?:means|shall mean|has the meaning)',
)

# Cross-reference patterns
_CROSS_REF_PATTERNS = [
    re.compile(r'(?:Section|Article)\s+(\d+(?:\.\d+)*)', re.IGNORECASE),
    re.compile(r'(?:Schedule|Exhibit|Annex)\s+([A-Z\d]+)', re.IGNORECASE),
]

# Keyword-based header detection
_SECTION_KEYWORDS = ["ARTICLE", "SECTION", "Article", "Section"]


def extract_clauses(contract: Contract) -> list[Clause]:
    """Split a contract into reviewable clauses using hierarchical parsing.

    1. Extract defined terms from the full text
    2. Parse hierarchical structure (Articles > Sections > Subsections)
    3. Classify each clause by type
    4. Resolve cross-references between clauses
    5. Tag defined terms used in each clause
    """
    if not contract.raw_text:
        return []

    # Step 1: Extract defined terms
    contract.defined_terms = _extract_defined_terms(contract.raw_text)

    # Step 2: Hierarchical section parsing
    sections = _split_into_sections(contract.raw_text)
    clauses = []
    parent_stack: list[tuple[int, str]] = []  # (depth, clause_id)

    for i, (title, text, depth) in enumerate(sections):
        # Determine parent from the stack
        while parent_stack and parent_stack[-1][0] >= depth:
            parent_stack.pop()
        parent_id = parent_stack[-1][1] if parent_stack else None

        clause = Clause(
            contract_id=contract.id,
            clause_type=_infer_clause_type(title, text),
            title=title,
            text=text,
            section_reference=title,
            depth=depth,
            parent_clause_id=parent_id,
            page_number=_estimate_page(i, len(sections), contract.page_count),
            defined_terms_used=_find_used_defined_terms(
                text, contract.defined_terms
            ),
        )
        clauses.append(clause)
        parent_stack.append((depth, clause.id))

    # Step 3: Resolve cross-references
    _link_related_clauses(clauses)

    return clauses


def _split_into_sections(text: str) -> list[tuple[str, str, int]]:
    """Split contract text into (title, body, depth) triples.

    Uses hierarchical pattern matching to determine nesting depth.
    """
    lines = text.split("\n")
    sections: list[tuple[str, str, int]] = []
    current_title = "Preamble"
    current_depth = 0
    current_body: list[str] = []

    for line in lines:
        stripped = line.strip()
        header_depth = _detect_header(stripped)
        if header_depth is not None:
            if current_body:
                body_text = "\n".join(current_body).strip()
                if body_text:
                    sections.append((current_title, body_text, current_depth))
            current_title = stripped
            current_depth = header_depth
            current_body = []
        else:
            current_body.append(line)

    # Don't forget the last section
    if current_body:
        body_text = "\n".join(current_body).strip()
        if body_text:
            sections.append((current_title, body_text, current_depth))

    return sections


def _detect_header(line: str) -> int | None:
    """Detect if a line is a section header and return its depth level.

    Returns None if not a header, or depth (0=Article, 1=Section, 2+=subsection).
    """
    if not line:
        return None

    # Check schedule/exhibit headers
    if _SCHEDULE_PATTERN.match(line):
        return 0

    # Check hierarchical patterns
    for pattern, depth in HIERARCHY_PATTERNS:
        if pattern.match(line):
            return depth

    # Check keyword-based headers
    for kw in _SECTION_KEYWORDS:
        if line.startswith(kw):
            if kw.lower().startswith("article"):
                return 0
            return 1

    # Numbered sections like "1." at the start of a short line
    parts = line.split(".", 1)
    if parts[0].strip().isdigit() and len(line) < 200:
        return 0

    return None


def _extract_defined_terms(text: str) -> dict[str, str]:
    """Extract defined terms and their definitions from contract text."""
    terms: dict[str, str] = {}
    for match in _DEFINED_TERM_PATTERN.finditer(text):
        term_name = match.group(1).strip()
        # Grab the rest of the sentence as the definition
        start = match.end()
        snippet = text[start:start + 500]
        for delim in [". ", ";\n", ".\n"]:
            idx = snippet.find(delim)
            if idx != -1:
                snippet = snippet[:idx + 1]
                break
        terms[term_name] = snippet.strip()
    return terms


def _find_used_defined_terms(
    text: str, defined_terms: dict[str, str]
) -> list[str]:
    """Find which defined terms are referenced in a clause's text."""
    used = []
    text_lower = text.lower()
    for term in defined_terms:
        if term.lower() in text_lower:
            used.append(term)
    return used


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
        # India-specific M&A clause types
        ClauseType.ANTI_DILUTION: [
            "anti-dilution", "anti dilution", "weighted average",
            "full ratchet", "price protection",
        ],
        ClauseType.TAG_ALONG_DRAG_ALONG: [
            "tag along", "tag-along", "drag along", "drag-along",
            "co-sale", "bring along",
        ],
        ClauseType.RESERVED_MATTERS: [
            "reserved matter", "affirmative vote", "investor consent",
            "promoter consent", "veto right", "prior written consent",
        ],
        ClauseType.ROFR_ROFO: [
            "right of first refusal", "rofr", "right of first offer",
            "rofo", "pre-emptive right", "pre emptive",
        ],
        ClauseType.LOCK_IN: [
            "lock-in", "lock in period", "minimum holding",
            "restriction on transfer", "holding period",
        ],
        ClauseType.INFORMATION_RIGHTS: [
            "information right", "inspection right", "audit right",
            "board observer", "board seat", "nominee director",
        ],
        ClauseType.AFFIRMATIVE_COVENANTS: [
            "affirmative covenant", "shall ensure", "shall maintain",
            "positive covenant",
        ],
        ClauseType.NEGATIVE_COVENANTS: [
            "negative covenant", "shall not without", "restricted action",
            "restrictive covenant",
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
    """Detect cross-references between clauses and link them.

    Uses regex to find Section X.Y, Article X, Schedule X references
    and maps them to actual clause IDs.
    """
    # Build lookup: section_reference (lowercase) -> clause_id
    ref_to_id: dict[str, str] = {}
    for clause in clauses:
        ref_to_id[clause.section_reference.lower()] = clause.id
        # Also index by extracted numbers (e.g., "3.1" from "Section 3.1 ...")
        for pattern, _ in HIERARCHY_PATTERNS:
            m = pattern.match(clause.section_reference)
            if m:
                ref_to_id[m.group(1).lower()] = clause.id
                break

    for clause in clauses:
        text = clause.text
        for ref_pattern in _CROSS_REF_PATTERNS:
            for match in ref_pattern.finditer(text):
                ref_key = match.group(1).lower()
                target_id = ref_to_id.get(ref_key)
                if target_id and target_id != clause.id:
                    if target_id not in clause.related_clause_ids:
                        clause.related_clause_ids.append(target_id)

        # Fallback: simple substring matching for section references
        text_lower = text.lower()
        for ref, clause_id in ref_to_id.items():
            if clause_id == clause.id:
                continue
            if ref and ref in text_lower and clause_id not in clause.related_clause_ids:
                clause.related_clause_ids.append(clause_id)
