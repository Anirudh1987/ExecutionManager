"""Execution pipeline — orchestrates the full contract review workflow.

Flow:
  Upload → Extract Clauses → Parallel AI Analysis → Cross-Clause Check →
  Route to Humans → Collect Verdicts → Capture Precedents → Generate Advisory

The pipeline is the central coordinator. It doesn't do analysis itself;
it delegates to the extractor, analyzer, router, and cross-clause analyzer.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from src.models.contract import Contract, ClauseType
from src.models.deal import Deal, DealStatus
from src.models.review import (
    ClauseReview,
    Review,
    ReviewStage,
    RiskLevel,
)
from src.models.team import TeamMember
from src.engine.clause_extractor import extract_clauses
from src.engine.analyzer import ClauseAnalyzer
from src.engine.router import ReviewRouter
from src.engine.cross_clause_analyzer import CrossClauseAnalyzer
from src.services.store import Store
from src.services.precedent_library import PrecedentEntry, PrecedentLibrary
from src.services.time_tracker import TimeTracker


class ReviewPipeline:
    """Manages the end-to-end review lifecycle for a contract."""

    def __init__(
        self,
        store: Store,
        analyzer: ClauseAnalyzer,
        router: ReviewRouter,
        cross_clause_analyzer: CrossClauseAnalyzer | None = None,
        precedent_library: PrecedentLibrary | None = None,
        time_tracker: TimeTracker | None = None,
        ws_manager=None,
    ):
        self._store = store
        self._analyzer = analyzer
        self._router = router
        self._cross_clause = cross_clause_analyzer or CrossClauseAnalyzer()
        self._precedents = precedent_library
        self._time_tracker = time_tracker
        self._ws_manager = ws_manager

    async def start_review(self, contract: Contract, deal: Deal) -> Review:
        """Kick off the full review pipeline for a contract.

        1. Extract clauses from the contract
        2. Create a Review with ClauseReviews for each clause
        3. Run AI analysis on all clauses in parallel
        4. Run cross-clause pattern detection
        5. Route findings to the appropriate team members
        """
        # Step 1: Decompose contract into clauses
        clauses = extract_clauses(contract)
        contract.clauses = clauses
        self._store.save_contract(contract)

        # Step 2: Create the review
        review = Review(
            contract_id=contract.id,
            deal_id=deal.id,
        )

        # Step 3: Parallel AI analysis
        analysis_tasks = [
            self._analyzer.analyze_clause(clause) for clause in clauses
        ]
        clause_reviews = await asyncio.gather(*analysis_tasks)

        # Attach to review
        for cr in clause_reviews:
            cr.review_id = review.id
        review.clause_reviews = list(clause_reviews)

        # Step 4: Cross-clause pattern detection
        cross_patterns = self._cross_clause.analyze_patterns(
            clauses, review.clause_reviews
        )
        review.cross_clause_patterns = cross_patterns

        # Step 5: Route to humans based on risk level
        team = self._store.get_team_for_deal(deal.id)
        for clause_review in review.clause_reviews:
            if clause_review.needs_human_review:
                assigned = self._router.assign_reviewer(clause_review, team)
                if assigned:
                    clause_review.assigned_to = assigned.id
                    clause_review.stage = ReviewStage.HUMAN_REVIEW

        # Update deal status
        deal.status = DealStatus.IN_REVIEW
        if review.id not in deal.review_ids:
            deal.review_ids.append(review.id)
        self._store.save_deal(deal)
        self._store.save_review(review)

        # Broadcast via WebSocket
        await self._broadcast(deal.id, {
            "event": "review_started",
            "review_id": review.id,
            "contract_id": contract.id,
            "clauses": len(clauses),
            "critical_findings": review.critical_findings_count,
            "cross_clause_patterns": len(cross_patterns),
        })

        return review

    async def submit_human_verdict(
        self,
        review_id: str,
        clause_review_id: str,
        annotation,
    ) -> ClauseReview:
        """Process a human reviewer's verdict on a clause.

        After receiving the verdict:
        - If ESCALATE: re-route to Strategist
        - If AGREE/MODIFY: mark clause as reviewed, update final risk
        - If DISAGREE: record disagreement for learning loop
        - If suggested_language provided: save to precedent library
        """
        review = self._store.get_review(review_id)
        clause_review = next(
            (cr for cr in review.clause_reviews if cr.id == clause_review_id),
            None,
        )
        if not clause_review:
            raise ValueError(f"ClauseReview {clause_review_id} not found")

        clause_review.human_annotations.append(annotation)

        if annotation.verdict.value == "escalate":
            clause_review.stage = ReviewStage.ESCALATED
            team = self._store.get_team_for_deal(review.deal_id)
            strategist = self._router.get_strategist(team)
            if strategist:
                clause_review.assigned_to = strategist.id
        elif annotation.verdict.value in ("agree", "modify", "disagree"):
            clause_review.final_risk_level = (
                annotation.revised_risk_level or clause_review.ai_risk_level
            )
            clause_review.human_completed_at = datetime.utcnow()
            clause_review.stage = ReviewStage.APPROVED

            # Record time tracking
            if self._time_tracker and clause_review.review_duration_minutes is not None:
                contract = self._store.get_contract(review.contract_id)
                clause = next(
                    (c for c in contract.clauses if c.id == clause_review.clause_id),
                    None,
                )
                if clause:
                    self._time_tracker.record_duration(
                        clause.clause_type,
                        clause_review.review_duration_minutes,
                    )

        # Save precedent if human provided suggested language
        if self._precedents and annotation.suggested_language:
            contract = self._store.get_contract(review.contract_id)
            clause = next(
                (c for c in contract.clauses if c.id == clause_review.clause_id),
                None,
            )
            if clause:
                finding_category = "general"
                if annotation.finding_id:
                    matching = [
                        f for f in clause_review.ai_findings
                        if f.id == annotation.finding_id
                    ]
                    if matching:
                        finding_category = matching[0].category

                self._precedents.save_precedent(PrecedentEntry(
                    clause_type=clause.clause_type,
                    finding_category=finding_category,
                    original_text=clause.text[:500],
                    revised_text=annotation.suggested_language,
                    reviewer_id=annotation.reviewer_id,
                    deal_id=review.deal_id,
                    comment=annotation.comment,
                ))

        self._store.save_review(review)

        # Check if all clause reviews are complete
        if all(cr.is_complete for cr in review.clause_reviews):
            review.completed_at = datetime.utcnow()
            self._store.save_review(review)
            await self._broadcast(review.deal_id, {
                "event": "review_completed",
                "review_id": review.id,
            })
        else:
            await self._broadcast(review.deal_id, {
                "event": "verdict_submitted",
                "review_id": review.id,
                "clause_review_id": clause_review.id,
                "stage": clause_review.stage.value,
            })

        return clause_review

    def get_review_dashboard(self, review_id: str) -> dict:
        """Summary view for the team — what needs attention, what's done."""
        review = self._store.get_review(review_id)

        by_stage: dict[str, int] = {}
        by_risk: dict[str, int] = {}
        for cr in review.clause_reviews:
            by_stage[cr.stage.value] = by_stage.get(cr.stage.value, 0) + 1
            by_risk[cr.ai_risk_level.value] = (
                by_risk.get(cr.ai_risk_level.value, 0) + 1
            )

        return {
            "review_id": review.id,
            "contract_id": review.contract_id,
            "progress": review.progress,
            "total_clauses": len(review.clause_reviews),
            "critical_findings": review.critical_findings_count,
            "pending_human_reviews": len(review.pending_human_reviews),
            "cross_clause_patterns": len(review.cross_clause_patterns),
            "by_stage": by_stage,
            "by_risk": by_risk,
            "is_complete": review.completed_at is not None,
        }

    async def _broadcast(self, deal_id: str, event: dict) -> None:
        """Send event to all connected WebSocket clients for this deal."""
        if self._ws_manager:
            await self._ws_manager.broadcast(deal_id, event)
