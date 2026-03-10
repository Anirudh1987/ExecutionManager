"""Analytics endpoints — feedback loop insights and accuracy metrics."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/accuracy")
async def accuracy_by_category(request: Request):
    """How accurate is the AI for each finding category?"""
    feedback = request.app.state.feedback
    stats = feedback.accuracy_by_category()
    return {
        category: {
            "total": s.total,
            "agreement_rate": s.agreement_rate,
            "accuracy": s.accuracy,
        }
        for category, s in stats.items()
    }


@router.get("/calibration")
async def confidence_calibration(request: Request):
    """Is AI confidence well-calibrated against human agreement?"""
    feedback = request.app.state.feedback
    return feedback.confidence_calibration()


@router.get("/risk-adjustments")
async def risk_adjustments(request: Request):
    """Where is the AI consistently over/under-estimating risk?"""
    feedback = request.app.state.feedback
    return feedback.risk_adjustment_suggestions()


@router.get("/reviewer-patterns")
async def reviewer_patterns(request: Request):
    """Per-reviewer agreement/disagreement patterns."""
    feedback = request.app.state.feedback
    return feedback.reviewer_patterns()


@router.get("/time-estimates/{review_id}")
async def time_estimates(review_id: str, request: Request):
    """Predicted completion time for a review based on historical averages."""
    store = request.app.state.store
    time_tracker = request.app.state.time_tracker

    review = store.get_review(review_id)
    contract = store.get_contract(review.contract_id)
    clauses_by_id = {c.id: c.clause_type for c in contract.clauses}

    return time_tracker.estimate_deal_completion(review, clauses_by_id)


@router.get("/review-times")
async def review_times(request: Request):
    """Average review time by clause type."""
    time_tracker = request.app.state.time_tracker
    return time_tracker.get_all_averages()


@router.get("/summary")
async def analytics_summary(request: Request):
    """Overall feedback loop health metrics."""
    feedback = request.app.state.feedback
    stats = feedback.accuracy_by_category()

    total_feedback = feedback.total_feedback_count
    overall_accuracy = 0.0
    if stats:
        overall_accuracy = sum(s.accuracy for s in stats.values()) / len(stats)

    return {
        "total_feedback_signals": total_feedback,
        "categories_tracked": len(stats),
        "overall_ai_accuracy": round(overall_accuracy, 2),
        "calibration": feedback.confidence_calibration(),
    }
