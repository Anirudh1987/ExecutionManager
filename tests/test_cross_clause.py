"""Tests for cross-clause pattern detection."""

import pytest

from src.models.contract import Clause, ClauseType
from src.models.review import ClauseReview, RiskLevel, ReviewStage
from src.engine.cross_clause_analyzer import CrossClauseAnalyzer


@pytest.fixture
def analyzer():
    return CrossClauseAnalyzer()


def _make_clause(clause_type, title, text):
    return Clause(
        contract_id="test-contract",
        clause_type=clause_type,
        title=title,
        text=text,
    )


def _make_review(clause, risk=RiskLevel.MEDIUM):
    return ClauseReview(
        clause_id=clause.id,
        review_id="test-review",
        ai_risk_level=risk,
        stage=ReviewStage.AI_COMPLETE,
    )


class TestCrossClauseAnalyzer:
    def test_detects_indemnification_vs_reps(self, analyzer):
        indem = _make_clause(
            ClauseType.INDEMNIFICATION,
            "Indemnification",
            "Seller shall indemnify Buyer. The aggregate liability shall not exceed $5,000,000.",
        )
        reps = _make_clause(
            ClauseType.REPRESENTATIONS_WARRANTIES,
            "Representations",
            "Seller represents and warrants that all financial statements are accurate.",
        )
        reviews = [_make_review(indem, RiskLevel.HIGH), _make_review(reps)]

        patterns = analyzer.analyze_patterns(
            [indem, reps], reviews
        )

        # Should detect issues — cap without fundamental exception, no survival
        assert len(patterns) >= 1
        assert any(p.pattern_type == "indemnification_vs_reps" for p in patterns)

    def test_detects_mac_vs_conditions(self, analyzer):
        mac = _make_clause(
            ClauseType.MATERIAL_ADVERSE_CHANGE,
            "MAC",
            "Material Adverse Change means any change that affects the business.",
        )
        cond = _make_clause(
            ClauseType.CONDITIONS_PRECEDENT,
            "Conditions",
            "The obligations are subject to regulatory approval.",
        )
        reviews = [_make_review(mac), _make_review(cond)]

        patterns = analyzer.analyze_patterns([mac, cond], reviews)

        # Should detect: MAC not in conditions, missing carve-outs
        mac_patterns = [p for p in patterns if p.pattern_type == "mac_vs_conditions"]
        assert len(mac_patterns) >= 1

    def test_no_patterns_when_types_missing(self, analyzer):
        clause = _make_clause(
            ClauseType.GOVERNING_LAW,
            "Governing Law",
            "This Agreement shall be governed by Delaware law.",
        )
        reviews = [_make_review(clause)]

        patterns = analyzer.analyze_patterns([clause], reviews)
        # Governing law alone shouldn't trigger cross-clause patterns
        assert len(patterns) == 0

    def test_detects_termination_vs_break_fee(self, analyzer):
        term = _make_clause(
            ClauseType.TERMINATION,
            "Termination",
            "Either party may terminate this Agreement upon 30 days written notice.",
        )
        price = _make_clause(
            ClauseType.PURCHASE_PRICE,
            "Purchase Price",
            "The purchase price shall be $50,000,000.",
        )
        reviews = [_make_review(term), _make_review(price)]

        patterns = analyzer.analyze_patterns([term, price], reviews)

        # Should detect missing break fee
        assert any(p.pattern_type == "termination_vs_break_fee" for p in patterns)
