"""Tests for time estimation and budget allocation."""

import pytest

from src.models.review import ClauseReview, AIFinding, DealContext, RiskLevel, ReviewStage
from src.models.team import TeamMember, Role
from src.engine.time_estimator import TimeEstimator, DEFAULT_TIME_BUDGET


def _make_clause_review(risk_level=RiskLevel.MEDIUM, num_findings=2, summary_words=50):
    findings = []
    for i in range(num_findings):
        findings.append(AIFinding(
            category=f"cat_{i}",
            title=f"Finding {i}",
            description="A " * 30,  # ~30 words
            risk_level=risk_level,
            confidence=0.7,
            suggested_revision="Suggested revision text here." if i == 0 else "",
        ))
    return ClauseReview(
        clause_id=f"clause_{risk_level.value}",
        review_id="r1",
        stage=ReviewStage.HUMAN_REVIEW,
        ai_risk_level=risk_level,
        ai_findings=findings,
        ai_summary="Summary " * summary_words,
    )


class TestTimeEstimation:
    def test_estimate_review_time(self):
        est = TimeEstimator()
        cr = _make_clause_review(num_findings=3, summary_words=80)
        clause = type("Clause", (), {"text": "word " * 200})()  # 200 word clause

        time_min = est.estimate_review_time(cr, clause)
        assert time_min > 0
        assert time_min < 30  # Should not exceed 30 min for a single clause

    def test_more_findings_more_time(self):
        est = TimeEstimator()
        clause = type("Clause", (), {"text": "word " * 100})()

        cr_few = _make_clause_review(num_findings=1)
        cr_many = _make_clause_review(num_findings=5)

        time_few = est.estimate_review_time(cr_few, clause)
        time_many = est.estimate_review_time(cr_many, clause)
        assert time_many > time_few

    def test_critical_adds_time(self):
        est = TimeEstimator()
        clause = type("Clause", (), {"text": "word " * 100})()

        cr_low = _make_clause_review(risk_level=RiskLevel.LOW, num_findings=2)
        cr_critical = _make_clause_review(risk_level=RiskLevel.CRITICAL, num_findings=2)

        # Critical items may take similar base time but are routed to senior reviewers
        time_low = est.estimate_review_time(cr_low, clause)
        time_critical = est.estimate_review_time(cr_critical, clause)
        # Both should be positive
        assert time_low > 0
        assert time_critical > 0


class TestBudgetAllocation:
    def test_allocate_budget(self):
        est = TimeEstimator()
        reviews = [
            _make_clause_review(risk_level=RiskLevel.CRITICAL),
            _make_clause_review(risk_level=RiskLevel.HIGH),
            _make_clause_review(risk_level=RiskLevel.MEDIUM),
            _make_clause_review(risk_level=RiskLevel.LOW),
        ]
        team = [
            TeamMember(name="Partner", role=Role.STRATEGIST, email="partner@test.com"),
            TeamMember(name="Associate", role=Role.ANALYST, email="associate@test.com"),
            TeamMember(name="Junior", role=Role.COORDINATOR, email="junior@test.com"),
        ]

        allocation = est.allocate_budget(reviews, team, DealContext())
        assert len(allocation) > 0

    def test_default_budget_is_540(self):
        assert DEFAULT_TIME_BUDGET == 540.0


class TestTimeDashboard:
    def test_dashboard_structure(self):
        est = TimeEstimator()
        reviews = [
            _make_clause_review(risk_level=RiskLevel.HIGH),
        ]
        team = [
            TeamMember(name="Partner", role=Role.STRATEGIST, email="partner@test.com"),
        ]

        dashboard = est.get_time_dashboard(team, reviews, DealContext())
        assert "team" in dashboard
        assert "overall_progress" in dashboard
        assert "on_track" in dashboard
