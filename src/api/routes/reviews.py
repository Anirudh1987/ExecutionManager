"""Review workflow endpoints — the human-in-the-loop interface."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.models.review import HumanAnnotation, HumanVerdict, RiskLevel

router = APIRouter()


class SubmitVerdictRequest(BaseModel):
    reviewer_id: str
    finding_id: str | None = None
    verdict: HumanVerdict
    comment: str = ""
    revised_risk_level: RiskLevel | None = None
    suggested_language: str = ""


@router.get("/{review_id}")
async def get_review(review_id: str, request: Request):
    """Get full review status with all clause reviews."""
    store = request.app.state.store
    review = store.get_review(review_id)
    return {
        "id": review.id,
        "contract_id": review.contract_id,
        "progress": review.progress,
        "is_complete": review.completed_at is not None,
        "critical_findings": review.critical_findings_count,
        "pending_human_reviews": len(review.pending_human_reviews),
        "clause_reviews": [
            {
                "id": cr.id,
                "clause_id": cr.clause_id,
                "stage": cr.stage.value,
                "ai_risk_level": cr.ai_risk_level.value,
                "ai_summary": cr.ai_summary,
                "ai_confidence": cr.ai_confidence,
                "assigned_to": cr.assigned_to,
                "final_risk_level": cr.final_risk_level.value if cr.final_risk_level else None,
                "findings_count": len(cr.ai_findings),
                "is_complete": cr.is_complete,
            }
            for cr in review.clause_reviews
        ],
    }


@router.get("/{review_id}/dashboard")
async def review_dashboard(review_id: str, request: Request):
    """Team dashboard view — what needs attention."""
    pipeline = request.app.state.pipeline
    return pipeline.get_review_dashboard(review_id)


@router.get("/{review_id}/clause/{clause_review_id}")
async def get_clause_review_detail(
    review_id: str, clause_review_id: str, request: Request
):
    """Detailed view of a single clause review with all AI findings."""
    store = request.app.state.store
    review = store.get_review(review_id)
    cr = next(
        (cr for cr in review.clause_reviews if cr.id == clause_review_id), None
    )
    if not cr:
        return {"error": "Clause review not found"}

    # Get the clause text for context
    contract = store.get_contract(review.contract_id)
    clause = next((c for c in contract.clauses if c.id == cr.clause_id), None)

    return {
        "clause_review": {
            "id": cr.id,
            "stage": cr.stage.value,
            "ai_risk_level": cr.ai_risk_level.value,
            "ai_confidence": cr.ai_confidence,
            "ai_summary": cr.ai_summary,
            "assigned_to": cr.assigned_to,
        },
        "clause": {
            "title": clause.title if clause else "",
            "text": clause.text if clause else "",
            "clause_type": clause.clause_type.value if clause else "",
            "section_reference": clause.section_reference if clause else "",
        },
        "ai_findings": [
            {
                "id": f.id,
                "category": f.category,
                "title": f.title,
                "description": f.description,
                "risk_level": f.risk_level.value,
                "confidence": f.confidence,
                "suggested_revision": f.suggested_revision,
                "market_comparison": f.market_comparison,
            }
            for f in cr.ai_findings
        ],
        "human_annotations": [
            {
                "id": a.id,
                "reviewer_id": a.reviewer_id,
                "verdict": a.verdict.value,
                "comment": a.comment,
                "revised_risk_level": a.revised_risk_level.value if a.revised_risk_level else None,
                "suggested_language": a.suggested_language,
            }
            for a in cr.human_annotations
        ],
    }


@router.post("/{review_id}/clause/{clause_review_id}/verdict")
async def submit_verdict(
    review_id: str,
    clause_review_id: str,
    req: SubmitVerdictRequest,
    request: Request,
):
    """Submit a human verdict on a clause review."""
    pipeline = request.app.state.pipeline
    feedback = request.app.state.feedback

    annotation = HumanAnnotation(
        finding_id=req.finding_id,
        reviewer_id=req.reviewer_id,
        verdict=req.verdict,
        comment=req.comment,
        revised_risk_level=req.revised_risk_level,
        suggested_language=req.suggested_language,
    )

    clause_review = await pipeline.submit_human_verdict(
        review_id, clause_review_id, annotation
    )

    # Feed the learning loop
    feedback.record_feedback(clause_review)

    return {
        "clause_review_id": clause_review.id,
        "stage": clause_review.stage.value,
        "final_risk_level": (
            clause_review.final_risk_level.value
            if clause_review.final_risk_level
            else None
        ),
    }


@router.get("/{review_id}/my-queue/{reviewer_id}")
async def my_review_queue(review_id: str, reviewer_id: str, request: Request):
    """Get the list of clause reviews assigned to a specific reviewer."""
    store = request.app.state.store
    review = store.get_review(review_id)

    my_items = [
        cr
        for cr in review.clause_reviews
        if cr.assigned_to == reviewer_id and not cr.is_complete
    ]

    # Sort: critical first, then high, then medium
    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
    my_items.sort(key=lambda cr: risk_order.get(cr.ai_risk_level.value, 5))

    return {
        "reviewer_id": reviewer_id,
        "pending_count": len(my_items),
        "items": [
            {
                "clause_review_id": cr.id,
                "clause_id": cr.clause_id,
                "ai_risk_level": cr.ai_risk_level.value,
                "ai_summary": cr.ai_summary,
                "ai_confidence": cr.ai_confidence,
                "findings_count": len(cr.ai_findings),
            }
            for cr in my_items
        ],
    }
