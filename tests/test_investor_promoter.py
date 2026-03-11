"""Tests for investor/promoter perspective-aware analysis and advisory."""

import pytest

from src.models.contract import Clause, ClauseType
from src.models.review import DealContext, RiskLevel
from src.engine.analyzer import ClauseAnalyzer


class TestPerspectiveAnalysis:
    """Verify that investor and promoter get different risk assessments."""

    def test_investor_gets_buyer_fallback(self):
        """Investor should use investor_risk, falling back to buyer_risk."""
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.INDEMNIFICATION,
            title="Indemnification",
            text="Standard indemnification clause",
        )
        context = DealContext(client_side="investor")
        findings = analyzer._rule_based_analyze(clause, context)
        # Should use buyer_risk since INDEMNIFICATION doesn't have investor_risk
        assert len(findings) > 0

    def test_promoter_gets_seller_fallback(self):
        """Promoter should use promoter_risk, falling back to seller_risk."""
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.INDEMNIFICATION,
            title="Indemnification",
            text="Standard indemnification clause",
        )
        context = DealContext(client_side="promoter")
        findings = analyzer._rule_based_analyze(clause, context)
        assert len(findings) > 0

    def test_negative_covenants_investor_critical(self):
        """Related party restrictions should be CRITICAL for investor."""
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.NEGATIVE_COVENANTS,
            title="Negative Covenants",
            text="Restrictions on company activities",
        )
        context = DealContext(client_side="investor")
        findings = analyzer._rule_based_analyze(clause, context)
        rpt = next(f for f in findings if f.category == "related_party_restrictions")
        assert rpt.risk_level == RiskLevel.CRITICAL

    def test_negative_covenants_promoter_low(self):
        """Related party restrictions should be LOW for promoter."""
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.NEGATIVE_COVENANTS,
            title="Negative Covenants",
            text="Restrictions on company activities",
        )
        context = DealContext(client_side="promoter")
        findings = analyzer._rule_based_analyze(clause, context)
        rpt = next(f for f in findings if f.category == "related_party_restrictions")
        assert rpt.risk_level == RiskLevel.LOW

    def test_lock_in_investor_medium(self):
        """Lock-in duration should be MEDIUM risk for investor (constrains exit)."""
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.LOCK_IN,
            title="Lock-In Period",
            text="Lock-in period provisions",
        )
        context = DealContext(client_side="investor")
        findings = analyzer._rule_based_analyze(clause, context)
        duration = next(f for f in findings if f.category == "lock_in_duration")
        assert duration.risk_level == RiskLevel.MEDIUM

    def test_lock_in_promoter_low(self):
        """Lock-in duration should be LOW risk for promoter (protects stability)."""
        analyzer = ClauseAnalyzer()
        clause = Clause(
            contract_id="c1",
            clause_type=ClauseType.LOCK_IN,
            title="Lock-In Period",
            text="Lock-in period provisions",
        )
        context = DealContext(client_side="promoter")
        findings = analyzer._rule_based_analyze(clause, context)
        duration = next(f for f in findings if f.category == "lock_in_duration")
        assert duration.risk_level == RiskLevel.LOW

    def test_all_26_clause_types_have_patterns(self):
        """Verify all 26 ClauseType values have RISK_PATTERNS or use default."""
        from src.engine.analyzer import RISK_PATTERNS, _DEFAULT_PATTERNS
        analyzer = ClauseAnalyzer()

        for ct in ClauseType:
            clause = Clause(
                contract_id="c1",
                clause_type=ct,
                title=ct.value,
                text="test",
            )
            context = DealContext(client_side="investor")
            findings = analyzer._rule_based_analyze(clause, context)
            assert len(findings) >= 1, f"No findings for {ct.value}"
