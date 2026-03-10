"""Precedent library endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from src.models.contract import ClauseType

router = APIRouter()


@router.get("/")
async def search_precedents(
    request: Request,
    clause_type: ClauseType | None = None,
    keyword: str | None = None,
):
    """Search the precedent library by clause type and/or keyword."""
    precedents = request.app.state.precedents
    keywords = [keyword] if keyword else None

    if clause_type:
        results = precedents.find_precedents(clause_type, keywords)
    else:
        # Search across all types
        results = []
        if keywords:
            for ct in ClauseType:
                results.extend(precedents.find_precedents(ct, keywords))
        else:
            results = precedents._entries[:20]

    return [
        {
            "id": p.id,
            "clause_type": p.clause_type.value,
            "finding_category": p.finding_category,
            "original_text": p.original_text[:200],
            "revised_text": p.revised_text,
            "reviewer_id": p.reviewer_id,
            "deal_id": p.deal_id,
            "comment": p.comment,
            "created_at": p.created_at.isoformat(),
        }
        for p in results
    ]


@router.get("/stats")
async def precedent_stats(request: Request):
    """Precedent coverage by clause type."""
    precedents = request.app.state.precedents
    return {
        "total": precedents.total_count,
        "by_clause_type": precedents.stats(),
    }
