"""Tests for the 6-gate practical risk filter."""

import pytest

from src.models.contract import Clause, ClauseType
from src.models.review import AIFinding, DealContext, RiskLevel
from src.engine.practical_risk_filter import (
    PracticalRiskFilter,
    _extract_amounts,
    _downgrade_risk,
    MATERIALITY_THRESHOLDS,
)


def _make_clause(clause_type=ClauseType.INDEMNIFICATION, text=""):
    return Clause(
        contract_id="c1",
        clause_type=clause_type,
        title="Test Clause",
        text=text,
    )


def _make_finding(risk_level=RiskLevel.HIGH, category="test"):
    return AIFinding(
        category=category,
        title="Test Finding",
        description="Test description",
        risk_level=risk_level,
        confidence=0.8,
    )


class TestExtractAmounts:
    def test_rupee_crore(self):
        amounts = _extract_amounts("The cap is ₹50Cr")
        assert len(amounts) == 1
        assert amounts[0] == 50_00_00_000

    def test_rupee_lakh(self):
        amounts = _extract_amounts("The amount is ₹25L")
        assert len(amounts) == 1
        assert amounts[0] == 25_00_000

    def test_dollar_million(self):
        amounts = _extract_amounts("Valued at $10M")
        assert len(amounts) == 1
        assert amounts[0] == 10_000_000

    def test_dollar_billion(self):
        amounts = _extract_amounts("Total $2.5B")
        assert len(amounts) == 1
        assert amounts[0] == 2_500_000_000

    def test_no_amounts(self):
        assert _extract_amounts("No monetary values here") == []


class TestDowngradeRisk:
    def test_downgrade_critical(self):
        assert _downgrade_risk(RiskLevel.CRITICAL, 1) == RiskLevel.HIGH

    def test_downgrade_by_two(self):
        assert _downgrade_risk(RiskLevel.CRITICAL, 2) == RiskLevel.MEDIUM

    def test_downgrade_floors_at_informational(self):
        assert _downgrade_risk(RiskLevel.LOW, 3) == RiskLevel.INFORMATIONAL


class TestGate1Materiality:
    def test_suppresses_below_threshold(self):
        """Findings below materiality threshold should be suppressed."""
        filt = PracticalRiskFilter()
        clause = _make_clause(text="The penalty is ₹20L")
        context = DealContext(deal_value=100_00_00_000, deal_type="default")  # ₹100Cr
        finding = _make_finding()

        result = filt.validate_findings_sync([finding], clause, context)
        # ₹20L = 0.2% of ₹100Cr, threshold is 1% → suppressed
        assert len(result) == 0

    def test_keeps_above_threshold(self):
        """Findings above materiality threshold should be kept."""
        filt = PracticalRiskFilter()
        clause = _make_clause(text="The penalty is ₹5Cr")
        context = DealContext(deal_value=100_00_00_000, deal_type="default")
        finding = _make_finding()

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 1

    def test_no_deal_value_skips_gate(self):
        """If no deal value, gate 1 should be skipped."""
        filt = PracticalRiskFilter()
        clause = _make_clause(text="₹5L penalty")
        context = DealContext()
        finding = _make_finding()

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 1


class TestGate2Enforceability:
    def test_discounts_long_noncompete(self):
        """Non-compete >3 years in India gets risk downgraded."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.NON_COMPETE,
            text="The non-compete shall last for 5 years",
        )
        context = DealContext(jurisdiction="India")
        finding = _make_finding(risk_level=RiskLevel.CRITICAL)

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 1
        # Should be downgraded by 2 levels (discount 0.5)
        assert result[0].risk_level == RiskLevel.MEDIUM
        assert result[0].enforceability_note

    def test_skips_non_india(self):
        """Enforceability discounts only apply to India jurisdiction."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.NON_COMPETE,
            text="5 year non-compete",
        )
        context = DealContext(jurisdiction="United States")
        finding = _make_finding(risk_level=RiskLevel.CRITICAL)

        result = filt.validate_findings_sync([finding], clause, context)
        assert result[0].risk_level == RiskLevel.CRITICAL

    def test_suppresses_uncapped_indemnity_restructuring(self):
        """Uncapped indemnity in group restructuring should be suppressed."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.INDEMNIFICATION,
            text="unlimited indemnity with no cap",
        )
        context = DealContext(jurisdiction="India", deal_type="restructuring")
        finding = _make_finding()

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 0


class TestGate3Proportionality:
    def test_suppresses_escrow_small_deal(self):
        """Escrow findings on small deals (<₹10Cr) should be suppressed."""
        filt = PracticalRiskFilter()
        clause = _make_clause(clause_type=ClauseType.ESCROW, text="escrow provisions")
        context = DealContext(deal_value=5_00_00_000)  # ₹5Cr
        finding = _make_finding(risk_level=RiskLevel.MEDIUM)

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 0

    def test_keeps_escrow_large_deal(self):
        """Escrow findings on large deals should be kept."""
        filt = PracticalRiskFilter()
        clause = _make_clause(clause_type=ClauseType.ESCROW, text="escrow")
        context = DealContext(deal_value=500_00_00_000)  # ₹500Cr
        finding = _make_finding(risk_level=RiskLevel.MEDIUM)

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 1


class TestGate4Boilerplate:
    def test_suppresses_standard_governing_law(self):
        """Standard governing law boilerplate should be suppressed."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.GOVERNING_LAW,
            text="This agreement shall be governed by the laws of India",
        )
        context = DealContext()
        finding = _make_finding(risk_level=RiskLevel.LOW)

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 0

    def test_keeps_non_standard_language(self):
        """Non-standard language should not be suppressed."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.GOVERNING_LAW,
            text="This agreement is governed by the laws of Cayman Islands",
        )
        context = DealContext()
        finding = _make_finding(risk_level=RiskLevel.LOW)

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 1

    def test_keeps_critical_even_if_boilerplate(self):
        """CRITICAL findings should not be suppressed by boilerplate gate."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.GOVERNING_LAW,
            text="governed by laws of India",
        )
        context = DealContext()
        finding = _make_finding(risk_level=RiskLevel.CRITICAL)

        result = filt.validate_findings_sync([finding], clause, context)
        assert len(result) == 1


class TestSyncValidation:
    def test_multiple_findings_filtered(self):
        """Multiple findings should be independently filtered."""
        filt = PracticalRiskFilter()
        clause = _make_clause(
            clause_type=ClauseType.GOVERNING_LAW,
            text="governed by laws of India",
        )
        context = DealContext()
        f1 = _make_finding(risk_level=RiskLevel.LOW)
        f2 = _make_finding(risk_level=RiskLevel.CRITICAL)

        result = filt.validate_findings_sync([f1, f2], clause, context)
        # f1 suppressed by boilerplate (LOW), f2 kept (CRITICAL)
        assert len(result) == 1
        assert result[0].risk_level == RiskLevel.CRITICAL
