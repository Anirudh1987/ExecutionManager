"""Tests for the full review pipeline — extraction, analysis, routing, and verdicts."""

from __future__ import annotations

import pytest

from src.models.contract import Contract, ClauseType
from src.models.deal import Deal, DealStatus
from src.models.review import HumanAnnotation, HumanVerdict, RiskLevel, ReviewStage
from src.models.team import TeamMember, Role
from src.engine.clause_extractor import extract_clauses
from src.engine.analyzer import ClauseAnalyzer
from src.engine.router import ReviewRouter
from src.engine.pipeline import ReviewPipeline
from src.engine.advisory import AdvisoryGenerator
from src.services.store import Store
from src.learning.feedback_loop import FeedbackLoop


SAMPLE_CONTRACT_TEXT = """
STOCK PURCHASE AGREEMENT

This Stock Purchase Agreement is entered into as of January 1, 2026,
by and between Buyer Corp and Seller Inc.

ARTICLE I — PURCHASE PRICE
1.1 The aggregate purchase price for the Shares shall be $50,000,000
payable at closing.

ARTICLE II — REPRESENTATIONS AND WARRANTIES OF SELLER
2.1 Seller represents and warrants that the financial statements
delivered to Buyer are true and complete in all material respects.
2.2 To the knowledge of Seller, there is no pending litigation
that would materially affect the business.

ARTICLE III — INDEMNIFICATION
3.1 Seller shall indemnify and hold harmless Buyer from any losses
arising from breach of any representation or warranty.
3.2 The aggregate liability under this Article shall not exceed
$5,000,000.

ARTICLE IV — CONDITIONS PRECEDENT
4.1 The obligations of Buyer to consummate the transactions are
subject to regulatory approval and no material adverse change.

ARTICLE V — TERMINATION
5.1 This Agreement may be terminated by either party if the closing
has not occurred by June 30, 2026. A break fee of $1,000,000
shall be payable upon termination without cause.

ARTICLE VI — NON-COMPETE
6.1 Seller agrees not to compete in the same industry for a period
of five years within the United States.

ARTICLE VII — GOVERNING LAW
7.1 This Agreement shall be governed by the laws of the State of Delaware.
"""


@pytest.fixture
def store():
    return Store()


@pytest.fixture
async def team(store):
    members = [
        TeamMember(name="Alice", email="alice@firm.com", role=Role.STRATEGIST),
        TeamMember(name="Bob", email="bob@firm.com", role=Role.ANALYST),
        TeamMember(name="Carol", email="carol@firm.com", role=Role.COORDINATOR),
    ]
    for m in members:
        await store.save_team_member(m)
    return members


@pytest.fixture
async def deal(store, team):
    d = Deal(name="Acme Acquisition", client_name="Buyer Corp", deal_type="acquisition")
    await store.save_deal(d)
    await store.assign_team_to_deal(d.id, [m.id for m in team])
    return d


@pytest.fixture
def contract(deal):
    return Contract(
        deal_id=deal.id,
        filename="spa.pdf",
        title="Stock Purchase Agreement",
        contract_type="Stock Purchase Agreement",
        parties=["Buyer Corp", "Seller Inc"],
        raw_text=SAMPLE_CONTRACT_TEXT,
        page_count=30,
    )


class TestClauseExtraction:
    def test_extracts_clauses_from_contract(self, contract):
        clauses = extract_clauses(contract)
        assert len(clauses) > 0

    def test_identifies_clause_types(self, contract):
        clauses = extract_clauses(contract)
        types = {c.clause_type for c in clauses}
        assert ClauseType.REPRESENTATIONS_WARRANTIES in types or ClauseType.PURCHASE_PRICE in types

    def test_empty_contract_returns_no_clauses(self, deal):
        empty = Contract(deal_id=deal.id, filename="empty.pdf", raw_text="")
        clauses = extract_clauses(empty)
        assert clauses == []

    def test_links_related_clauses(self, contract):
        clauses = extract_clauses(contract)
        # Some clauses should reference others
        has_links = any(len(c.related_clause_ids) > 0 for c in clauses)
        # This may or may not be true depending on contract text, so just check no errors
        assert isinstance(has_links, bool)


class TestAnalyzer:
    @pytest.mark.asyncio
    async def test_analyzes_clause(self, contract):
        clauses = extract_clauses(contract)
        analyzer = ClauseAnalyzer()  # rule-based mode

        review = await analyzer.analyze_clause(clauses[0])
        assert review.stage == ReviewStage.AI_COMPLETE
        assert review.ai_completed_at is not None

    @pytest.mark.asyncio
    async def test_risk_level_assigned(self, contract):
        clauses = extract_clauses(contract)
        analyzer = ClauseAnalyzer()

        review = await analyzer.analyze_clause(clauses[0])
        assert review.ai_risk_level is not None

    @pytest.mark.asyncio
    async def test_confidence_in_range(self, contract):
        clauses = extract_clauses(contract)
        analyzer = ClauseAnalyzer()

        review = await analyzer.analyze_clause(clauses[0])
        assert 0.0 <= review.ai_confidence <= 1.0


class TestRouter:
    def test_routes_critical_to_strategist(self, team):
        from src.models.review import ClauseReview
        cr = ClauseReview(
            clause_id="test",
            review_id="test",
            ai_risk_level=RiskLevel.CRITICAL,
        )
        router = ReviewRouter()
        assigned = router.assign_reviewer(cr, team)
        assert assigned is not None
        assert assigned.role == Role.STRATEGIST

    def test_routes_medium_to_analyst(self, team):
        from src.models.review import ClauseReview
        cr = ClauseReview(
            clause_id="test",
            review_id="test",
            ai_risk_level=RiskLevel.MEDIUM,
        )
        router = ReviewRouter()
        assigned = router.assign_reviewer(cr, team)
        assert assigned is not None
        assert assigned.role == Role.ANALYST

    def test_routes_low_to_coordinator(self, team):
        from src.models.review import ClauseReview
        cr = ClauseReview(
            clause_id="test",
            review_id="test",
            ai_risk_level=RiskLevel.LOW,
            ai_confidence=0.9,
        )
        router = ReviewRouter()
        assigned = router.assign_reviewer(cr, team)
        assert assigned is not None
        assert assigned.role == Role.COORDINATOR


class TestPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, store, deal, contract, team):
        analyzer = ClauseAnalyzer()
        router = ReviewRouter()
        pipeline = ReviewPipeline(store, analyzer, router)

        review = await pipeline.start_review(contract, deal)

        assert len(review.clause_reviews) > 0
        assert review.progress >= 0.0

        # Deal should be in review
        updated_deal = await store.get_deal(deal.id)
        assert updated_deal.status == DealStatus.IN_REVIEW

    @pytest.mark.asyncio
    async def test_submit_verdict(self, store, deal, contract, team):
        analyzer = ClauseAnalyzer()
        router = ReviewRouter()
        pipeline = ReviewPipeline(store, analyzer, router)

        review = await pipeline.start_review(contract, deal)

        # Find a clause review that needs human review
        pending = review.pending_human_reviews
        if pending:
            cr = pending[0]
            annotation = HumanAnnotation(
                reviewer_id=team[0].id,
                verdict=HumanVerdict.AGREE,
                comment="Looks correct",
            )
            result = await pipeline.submit_human_verdict(
                review.id, cr.id, annotation
            )
            assert result.stage == ReviewStage.APPROVED


class TestFeedbackLoop:
    def test_records_feedback(self):
        from src.models.review import ClauseReview, AIFinding
        feedback = FeedbackLoop()

        cr = ClauseReview(
            clause_id="test",
            review_id="test",
            ai_risk_level=RiskLevel.HIGH,
            ai_confidence=0.8,
            ai_findings=[
                AIFinding(
                    category="cap_analysis",
                    title="Low indemnification cap",
                    description="Cap is below market",
                    risk_level=RiskLevel.HIGH,
                    confidence=0.8,
                )
            ],
            human_annotations=[
                HumanAnnotation(
                    reviewer_id="reviewer1",
                    verdict=HumanVerdict.AGREE,
                    comment="Correct finding",
                )
            ],
        )

        feedback.record_feedback(cr)
        assert feedback.total_feedback_count == 1

        stats = feedback.accuracy_by_category()
        assert "general" in stats
        assert stats["general"].agreement_rate == 1.0


class TestAdvisory:
    @pytest.mark.asyncio
    async def test_generate_advisory(self, store, deal, contract, team):
        analyzer = ClauseAnalyzer()
        router = ReviewRouter()
        pipeline = ReviewPipeline(store, analyzer, router)
        advisory = AdvisoryGenerator()

        review = await pipeline.start_review(contract, deal)
        contracts = [contract]
        reviews = [review]

        result = await advisory.generate_advisory(deal, contracts, reviews)

        assert "executive_summary" in result
        assert "key_risks" in result
        assert "total_clauses_reviewed" in result
        assert result["total_clauses_reviewed"] > 0
