"""Domain models for M&A contracts and their decomposed clauses."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ClauseType(str, Enum):
    """Categories of M&A contract clauses that drive different review strategies."""

    REPRESENTATIONS_WARRANTIES = "representations_warranties"
    INDEMNIFICATION = "indemnification"
    CONDITIONS_PRECEDENT = "conditions_precedent"
    COVENANTS = "covenants"
    TERMINATION = "termination"
    PURCHASE_PRICE = "purchase_price"
    CLOSING_MECHANICS = "closing_mechanics"
    NON_COMPETE = "non_compete"
    CONFIDENTIALITY = "confidentiality"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    EMPLOYEE_MATTERS = "employee_matters"
    TAX = "tax"
    GOVERNING_LAW = "governing_law"
    DISPUTE_RESOLUTION = "dispute_resolution"
    MATERIAL_ADVERSE_CHANGE = "material_adverse_change"
    EARNOUT = "earnout"
    ESCROW = "escrow"
    # India-specific M&A clause types
    ANTI_DILUTION = "anti_dilution"
    TAG_ALONG_DRAG_ALONG = "tag_along_drag_along"
    RESERVED_MATTERS = "reserved_matters"
    ROFR_ROFO = "rofr_rofo"
    LOCK_IN = "lock_in"
    INFORMATION_RIGHTS = "information_rights"
    AFFIRMATIVE_COVENANTS = "affirmative_covenants"
    NEGATIVE_COVENANTS = "negative_covenants"
    OTHER = "other"


class Clause(BaseModel):
    """An atomic unit of a contract — one reviewable provision.

    The system decomposes contracts into clauses so each can be independently
    analyzed, scored, and routed to the right reviewer.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contract_id: str
    clause_type: ClauseType
    title: str
    text: str
    section_reference: str = ""
    page_number: int | None = None
    parent_clause_id: str | None = None  # for nested sub-clauses
    depth: int = 0  # nesting level (Article=0, Section=1, subsection=2...)
    related_clause_ids: list[str] = Field(default_factory=list)
    defined_terms_used: list[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)

    # AI-populated fields after analysis
    summary: str = ""
    key_terms: list[str] = Field(default_factory=list)
    monetary_values: list[str] = Field(default_factory=list)
    deadlines: list[str] = Field(default_factory=list)
    parties_referenced: list[str] = Field(default_factory=list)


class Contract(BaseModel):
    """A complete M&A contract document."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    deal_id: str
    filename: str
    title: str = ""
    contract_type: str = ""  # e.g. "Stock Purchase Agreement", "Asset Purchase Agreement"
    parties: list[str] = Field(default_factory=list)
    effective_date: str = ""
    raw_text: str = ""
    clauses: list[Clause] = Field(default_factory=list)
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    defined_terms: dict[str, str] = Field(default_factory=dict)
    page_count: int = 0
    version: int = 1
    previous_version_id: str | None = None

    @property
    def clause_count(self) -> int:
        return len(self.clauses)

    def clauses_by_type(self, clause_type: ClauseType) -> list[Clause]:
        return [c for c in self.clauses if c.clause_type == clause_type]


class ClauseDiff(BaseModel):
    """Diff between two versions of a clause."""

    old_title: str
    new_title: str
    old_text: str
    new_text: str
    change_type: str  # "modified", "added", "removed"
    unified_diff: str  # unified diff text
    change_summary: str = ""


class ContractDiff(BaseModel):
    """Diff between two contract versions."""

    old_contract_id: str
    new_contract_id: str
    added_clauses: list[Clause] = Field(default_factory=list)
    removed_clauses: list[Clause] = Field(default_factory=list)
    modified_clauses: list[ClauseDiff] = Field(default_factory=list)
    summary: str = ""
