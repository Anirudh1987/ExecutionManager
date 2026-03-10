"""Tests for time tracking and completion estimation."""

import pytest
from datetime import datetime, timedelta

from src.models.contract import ClauseType
from src.models.review import ClauseReview, Review, RiskLevel, ReviewStage
from src.services.time_tracker import TimeTracker


class TestTimeTracker:
    def test_record_and_get_average(self):
        tracker = TimeTracker()
        tracker.record_duration(ClauseType.INDEMNIFICATION, 10.0)
        tracker.record_duration(ClauseType.INDEMNIFICATION, 20.0)
        tracker.record_duration(ClauseType.INDEMNIFICATION, 30.0)

        avg = tracker.get_average_review_time(ClauseType.INDEMNIFICATION)
        assert avg == 20.0

    def test_default_estimate(self):
        tracker = TimeTracker()
        avg = tracker.get_average_review_time(ClauseType.OTHER)
        assert avg == 15.0  # default

    def test_estimate_deal_completion(self):
        tracker = TimeTracker()
        tracker.record_duration(ClauseType.INDEMNIFICATION, 10.0)

        review = Review(contract_id="c", deal_id="d")
        # One completed, one pending
        completed_cr = ClauseReview(
            clause_id="clause-1",
            review_id=review.id,
            stage=ReviewStage.APPROVED,
            ai_risk_level=RiskLevel.HIGH,
            human_started_at=datetime.utcnow() - timedelta(minutes=12),
            human_completed_at=datetime.utcnow(),
        )
        pending_cr = ClauseReview(
            clause_id="clause-2",
            review_id=review.id,
            stage=ReviewStage.HUMAN_REVIEW,
            ai_risk_level=RiskLevel.MEDIUM,
        )
        review.clause_reviews = [completed_cr, pending_cr]

        clauses_by_id = {
            "clause-1": ClauseType.INDEMNIFICATION,
            "clause-2": ClauseType.INDEMNIFICATION,
        }

        estimate = tracker.estimate_deal_completion(review, clauses_by_id)
        assert estimate["completed"] == 1
        assert estimate["pending"] == 1
        assert estimate["estimated_remaining_minutes"] == 10.0

    def test_get_all_averages(self):
        tracker = TimeTracker()
        tracker.record_duration(ClauseType.INDEMNIFICATION, 10.0)
        tracker.record_duration(ClauseType.TERMINATION, 5.0)

        avgs = tracker.get_all_averages()
        assert "indemnification" in avgs
        assert "termination" in avgs
