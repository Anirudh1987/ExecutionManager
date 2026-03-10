"""Tests for the advisory generator with decision framework."""

import pytest

from src.models.contract import Contract, Clause, ClauseType
from src.models.deal import Deal
from src.models.review import (
    AIFinding,
    ClauseReview,
    CrossClausePattern,
    DealContext,
    HumanAnnotation,
    HumanVerdict,
    Review,
    ReviewStage,
    RiskLevel,
)
from src.engine.advisory import AdvisoryGenerator


def _make_clause(clause_type, title, text, clause_id=None):
    c = Clause(
        contract_id="test-contract",
        clause_type=clause_type,
        title=title,
        text=text,
    )
    if clause_id:
        c.id = clause_id
    return c


def _make_clause_review(clause_id, risk=RiskLevel.MEDIUM, findings=None, annotations=None):
    cr = ClauseReview(
        clause_id=clause_id,
        review_id="test-review",
        ai_risk_level=risk,
        stage=ReviewStage.APPROVED,
        ai_findings=findings or [],
        human_annotations=annotations or [],
    )
    return cr


class TestDecisionFramework:
    @pytest.mark.asyncio
    async def test_recommends_proceed_when_low_risk(self):
        deal = Deal(name="Safe Deal", client_name="Client")
        clause = _make_clause(ClauseType.GOVERNING_LAW, "Gov Law", "Delaware law.", "c1")
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        cr = _make_clause_review("c1", RiskLevel.LOW)
        review = Review(contract_id=contract.id, deal_id=deal.id, clause_reviews=[cr])

        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review])

        assert result["recommendation"] == "proceed"
        assert "PROCEED" in result["executive_summary"]

    @pytest.mark.asyncio
    async def test_recommends_negotiate_on_critical(self):
        deal = Deal(name="Risky Deal", client_name="Client")
        clause = _make_clause(ClauseType.INDEMNIFICATION, "Indem", "Cap at $100. Aggregate liability shall not exceed $100.", "c1")
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        finding = AIFinding(
            category="cap_analysis",
            title="Low cap",
            description="Cap is below market",
            risk_level=RiskLevel.CRITICAL,
            confidence=0.8,
        )
        cr = _make_clause_review("c1", RiskLevel.CRITICAL, findings=[finding])
        review = Review(contract_id=contract.id, deal_id=deal.id, clause_reviews=[cr])

        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review])

        assert result["recommendation"] in ("negotiate", "walk_away")

    @pytest.mark.asyncio
    async def test_recommends_walk_away_on_deal_breakers(self):
        deal = Deal(name="Bad Deal", client_name="Client")
        clause = _make_clause(ClauseType.INDEMNIFICATION, "Indem", "Fraud excluded.", "c1")
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        finding = AIFinding(
            category="exclusion_gaps",
            title="Fraud excluded",
            description="Critical exclusion",
            risk_level=RiskLevel.CRITICAL,
            confidence=0.9,
        )
        annotation = HumanAnnotation(
            reviewer_id="r1",
            verdict=HumanVerdict.AGREE,
            comment="Confirmed",
        )
        cr = _make_clause_review("c1", RiskLevel.CRITICAL, findings=[finding], annotations=[annotation])
        review = Review(contract_id=contract.id, deal_id=deal.id, clause_reviews=[cr])

        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review])

        assert result["recommendation"] == "walk_away"
        assert len(result["deal_breakers"]) >= 1


class TestFinancialExposure:
    @pytest.mark.asyncio
    async def test_extracts_financial_exposure(self):
        deal = Deal(name="Test", client_name="Client")
        clause = _make_clause(
            ClauseType.INDEMNIFICATION,
            "Indemnification",
            "Aggregate liability shall not exceed $5,000,000.",
            "c1",
        )
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        finding = AIFinding(
            category="cap_analysis",
            title="Low cap",
            description="Cap is below market",
            risk_level=RiskLevel.HIGH,
            confidence=0.8,
        )
        cr = _make_clause_review("c1", RiskLevel.HIGH, findings=[finding])
        review = Review(contract_id=contract.id, deal_id=deal.id, clause_reviews=[cr])

        context = DealContext(deal_value=50_000_000, client_side="buyer")
        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review], context)

        assert result["financial_exposure"]["estimated_total"] > 0
        assert "exposure_percentage" in result["financial_exposure"]

    @pytest.mark.asyncio
    async def test_exposure_percentage_calculated(self):
        deal = Deal(name="Test", client_name="Client")
        clause = _make_clause(
            ClauseType.PURCHASE_PRICE,
            "Price",
            "Purchase price of $10,000,000.",
            "c1",
        )
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        finding = AIFinding(
            category="adjustment_mechanisms",
            title="Missing adjustments",
            description="No working capital adjustment",
            risk_level=RiskLevel.HIGH,
            confidence=0.7,
        )
        cr = _make_clause_review("c1", RiskLevel.HIGH, findings=[finding])
        review = Review(contract_id=contract.id, deal_id=deal.id, clause_reviews=[cr])

        context = DealContext(deal_value=10_000_000)
        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review], context)

        assert result["financial_exposure"]["exposure_percentage"] > 0


class TestNegotiationMatrix:
    @pytest.mark.asyncio
    async def test_builds_negotiation_matrix(self):
        deal = Deal(name="Test", client_name="Client")
        clause = _make_clause(ClauseType.INDEMNIFICATION, "Indem", "Cap at $1M.", "c1")
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        finding = AIFinding(
            category="cap_analysis",
            title="Low cap",
            description="Below market",
            risk_level=RiskLevel.HIGH,
            confidence=0.8,
            suggested_revision="Increase cap to 15% of purchase price",
            market_comparison="Market standard is 10-20%",
        )
        cr = _make_clause_review("c1", RiskLevel.HIGH, findings=[finding])
        review = Review(contract_id=contract.id, deal_id=deal.id, clause_reviews=[cr])

        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review])

        matrix = result["negotiation_priority_matrix"]
        assert len(matrix) >= 1
        assert matrix[0]["priority"] == "must_have"
        assert "suggested_language" in matrix[0]


class TestCrossClauseNarrative:
    @pytest.mark.asyncio
    async def test_includes_cross_clause_risks(self):
        deal = Deal(name="Test", client_name="Client")
        clause = _make_clause(ClauseType.GOVERNING_LAW, "Gov", "Delaware.", "c1")
        contract = Contract(deal_id=deal.id, filename="t.pdf", clauses=[clause])

        cr = _make_clause_review("c1", RiskLevel.LOW)
        pattern = CrossClausePattern(
            pattern_type="test_pattern",
            title="Test Cross-Clause Issue",
            description="Two clauses conflict",
            risk_level=RiskLevel.HIGH,
            interaction_score=0.7,
            recommendation="Fix it",
        )
        review = Review(
            contract_id=contract.id,
            deal_id=deal.id,
            clause_reviews=[cr],
            cross_clause_patterns=[pattern],
        )

        gen = AdvisoryGenerator()
        result = await gen.generate_advisory(deal, [contract], [review])

        assert len(result["cross_clause_risks"]) >= 1
        assert "Test Cross-Clause Issue" in result["cross_clause_risks"][0]
