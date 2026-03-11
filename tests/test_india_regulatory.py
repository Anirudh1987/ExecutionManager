"""Tests for India regulatory checks and approval sequencing."""

import pytest

from src.models.contract import ClauseType
from src.models.review import DealContext
from src.engine.india_regulatory import (
    INDIA_REGULATORY_CHECKS,
    APPROVAL_SEQUENCE,
    INDIA_INDUSTRY_RISKS,
    get_applicable_regulatory_checks,
    get_approval_sequence,
    get_industry_risks,
)


class TestRegulatoryChecks:
    def test_checks_have_required_fields(self):
        for check_id, check in INDIA_REGULATORY_CHECKS.items():
            assert "description" in check, f"Missing description in {check_id}"
            assert "legal_citation" in check, f"Missing legal_citation in {check_id}"
            assert "applies_to" in check, f"Missing applies_to in {check_id}"
            assert "investor_risk" in check, f"Missing investor_risk in {check_id}"
            assert "promoter_risk" in check, f"Missing promoter_risk in {check_id}"

    def test_applicable_checks_india_only(self):
        context = DealContext(jurisdiction="United States")
        checks = get_applicable_regulatory_checks(ClauseType.PURCHASE_PRICE, context)
        assert len(checks) == 0

    def test_applicable_checks_india(self):
        context = DealContext(jurisdiction="India", client_side="investor")
        checks = get_applicable_regulatory_checks(ClauseType.PURCHASE_PRICE, context)
        assert len(checks) > 0

    def test_investor_vs_promoter_risk(self):
        context_inv = DealContext(jurisdiction="India", client_side="investor")
        context_prom = DealContext(jurisdiction="India", client_side="promoter")
        checks_inv = get_applicable_regulatory_checks(ClauseType.PURCHASE_PRICE, context_inv)
        checks_prom = get_applicable_regulatory_checks(ClauseType.PURCHASE_PRICE, context_prom)
        # Both should return checks but with different risk levels
        assert len(checks_inv) > 0
        assert len(checks_prom) > 0


class TestApprovalSequence:
    def test_pe_investment_sequence(self):
        seq = get_approval_sequence("pe_investment")
        assert len(seq) > 0
        steps = [s["step"] for s in seq]
        assert any("Board" in s for s in steps)
        assert any("FEMA" in s or "FC-GPR" in s for s in steps)

    def test_acquisition_sequence(self):
        seq = get_approval_sequence("acquisition")
        assert len(seq) > 0

    def test_unknown_deal_type_uses_default(self):
        seq = get_approval_sequence("unknown_type")
        # Falls back to pe_investment sequence as default
        assert len(seq) > 0

    def test_sequence_has_timeline(self):
        seq = get_approval_sequence("pe_investment")
        for step in seq:
            assert "timeline" in step
            assert "step" in step


class TestIndustryRisks:
    def test_banking_risks(self):
        risks = get_industry_risks("banking")
        assert risks is not None
        assert "regulators" in risks
        assert "RBI" in risks["regulators"]

    def test_fintech_risks(self):
        risks = get_industry_risks("fintech")
        assert risks is not None
        assert "regulators" in risks

    def test_unknown_industry(self):
        risks = get_industry_risks("unknown_industry")
        assert risks is None

    def test_all_industries_have_fields(self):
        for industry, data in INDIA_INDUSTRY_RISKS.items():
            assert "regulators" in data, f"Missing regulators in {industry}"
            assert "key_risks" in data, f"Missing key_risks in {industry}"
            assert "fdi_limit" in data, f"Missing fdi_limit in {industry}"
