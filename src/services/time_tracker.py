"""Time tracking — measures review duration and predicts completion timelines."""

from __future__ import annotations

from datetime import datetime

from src.models.contract import ClauseType
from src.models.review import ClauseReview, Review


class TimeTracker:
    """Tracks review timing data and estimates completion."""

    def __init__(self):
        # clause_type -> list of durations in minutes
        self._durations: dict[str, list[float]] = {}

    def record_duration(self, clause_type: ClauseType, duration_minutes: float) -> None:
        key = clause_type.value
        if key not in self._durations:
            self._durations[key] = []
        self._durations[key].append(duration_minutes)

    def get_average_review_time(self, clause_type: ClauseType) -> float:
        """Average review time in minutes for a clause type."""
        key = clause_type.value
        durations = self._durations.get(key, [])
        if not durations:
            return 15.0  # default estimate: 15 minutes per clause
        return sum(durations) / len(durations)

    def estimate_deal_completion(
        self,
        review: Review,
        clauses_by_id: dict[str, ClauseType],
    ) -> dict:
        """Predict remaining time to complete a review."""
        pending = [cr for cr in review.clause_reviews if not cr.is_complete]
        completed = [cr for cr in review.clause_reviews if cr.is_complete]

        estimated_minutes = 0.0
        per_clause_estimates = []

        for cr in pending:
            clause_type = clauses_by_id.get(cr.clause_id, ClauseType.OTHER)
            avg_time = self.get_average_review_time(clause_type)
            estimated_minutes += avg_time
            per_clause_estimates.append({
                "clause_review_id": cr.id,
                "clause_type": clause_type.value,
                "estimated_minutes": round(avg_time, 1),
            })

        # Calculate actual average from completed reviews in this deal
        actual_durations = [
            cr.review_duration_minutes
            for cr in completed
            if cr.review_duration_minutes is not None
        ]
        actual_avg = (
            sum(actual_durations) / len(actual_durations)
            if actual_durations
            else None
        )

        return {
            "total_clauses": len(review.clause_reviews),
            "completed": len(completed),
            "pending": len(pending),
            "estimated_remaining_minutes": round(estimated_minutes, 1),
            "estimated_remaining_hours": round(estimated_minutes / 60, 1),
            "actual_average_minutes": round(actual_avg, 1) if actual_avg else None,
            "per_clause_estimates": per_clause_estimates,
        }

    def get_all_averages(self) -> dict[str, float]:
        """Average review time for every tracked clause type."""
        return {
            ct: round(sum(durations) / len(durations), 1)
            for ct, durations in self._durations.items()
            if durations
        }
