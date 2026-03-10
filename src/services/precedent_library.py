"""Precedent library — stores and retrieves human-written revisions from past reviews."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.models.contract import ClauseType


class PrecedentEntry(BaseModel):
    """A revision from a past review that can inform future analysis."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    clause_type: ClauseType
    finding_category: str  # e.g. "cap_analysis", "scope_gap"
    original_text: str  # the clause text that was revised
    revised_text: str  # the human-suggested language
    reviewer_id: str
    deal_id: str
    comment: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PrecedentLibrary:
    """In-memory precedent store. Captures human revisions and matches them to future clauses."""

    def __init__(self):
        self._entries: list[PrecedentEntry] = []

    def save_precedent(self, entry: PrecedentEntry) -> None:
        self._entries.append(entry)

    def find_precedents(
        self,
        clause_type: ClauseType,
        keywords: list[str] | None = None,
        limit: int = 5,
    ) -> list[PrecedentEntry]:
        """Find precedents matching clause type and optional keywords."""
        matches = [e for e in self._entries if e.clause_type == clause_type]

        if keywords:
            scored = []
            for entry in matches:
                combined = (entry.original_text + " " + entry.revised_text + " " + entry.finding_category).lower()
                score = sum(1 for kw in keywords if kw.lower() in combined)
                if score > 0:
                    scored.append((score, entry))
            scored.sort(key=lambda x: x[0], reverse=True)
            matches = [entry for _, entry in scored[:limit]]
        else:
            matches = matches[:limit]

        return matches

    def stats(self) -> dict[str, int]:
        """Precedent coverage by clause type."""
        counts: dict[str, int] = {}
        for entry in self._entries:
            key = entry.clause_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def total_count(self) -> int:
        return len(self._entries)
