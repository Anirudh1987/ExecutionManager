"""Execution pipeline — orchestrates the full contract review workflow.

Flow:
  Upload → Extract Clauses → Staged AI Analysis (critical-first) →
  Practical Risk Filter → Cross-Clause Check → Batch & Route to Humans →
  Collect Verdicts → Capture Precedents → Generate Advisory

Round-aware: If contract has previous_version_id, the pipeline diffs against
the prior version and only routes changed clauses to human review. Unchanged
clauses carry forward their previous verdicts.

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
    DealContext,
    Review,
    ReviewBatch,
    ReviewStage,
    RiskLevel,
)
from src.models.team import TeamMember
from src.engine.clause_extractor import extract_clauses
from src.engine.analyzer import ClauseAnalyzer, CRITICAL_CLAUSE_TYPES
from src.engine.router import ReviewRouter
from src.engine.cross_clause_analyzer import CrossClauseAnalyzer
from src.engine.practical_risk_filter import PracticalRiskFilter
from src.engine.time_estimator import TimeEstimator
from src.services.store import Store
from src.services.precedent_library import PrecedentEntry, PrecedentLibrary
from src.services.time_tracker import TimeTracker


# Clause types that are related and should be reviewed together
_BATCH_GROUPS: list[set[ClauseType]] = [
    {ClauseType.INDEMNIFICATION, ClauseType.REPRESENTATIONS_WARRANTIES, ClauseType.ESCROW},
    {ClauseType.TERMINATION, ClauseType.PURCHASE_PRICE},
    {ClauseType.MATERIAL_ADVERSE_CHANGE, ClauseType.CONDITIONS_PRECEDENT},
    {ClauseType.COVENANTS, ClauseType.CONDITIONS_PRECEDENT},
    {ClauseType.EARNOUT, ClauseType.COVENANTS},
    {ClauseType.NON_COMPETE, ClauseType.EMPLOYEE_MATTERS},
    {ClauseType.GOVERNING_LAW, ClauseType.DISPUTE_RESOLUTION},
    {ClauseType.INTELLECTUAL_PROPERTY, ClauseType.CONFIDENTIALITY},
    {ClauseType.TAX, ClauseType.PURCHASE_PRICE},
    # India-specific batch groups
    {ClauseType.ANTI_DILUTION, ClauseType.PURCHASE_PRICE},
    {ClauseType.TAG_ALONG_DRAG_ALONG, ClauseType.ROFR_ROFO, ClauseType.LOCK_IN},
    {ClauseType.RESERVED_MATTERS, ClauseType.NEGATIVE_COVENANTS, ClauseType.AFFIRMATIVE_COVENANTS},
]


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
        risk_filter: PracticalRiskFilter | None = None,
        time_estimator: TimeEstimator | None = None,
        ai_orchestrator=None,
        ws_manager=None,
    ):
        self._store = store
        self._analyzer = analyzer
        self._router = router
        self._cross_clause = cross_clause_analyzer or CrossClauseAnalyzer()
        self._precedents = precedent_library
        self._time_tracker = time_tracker
        self._risk_filter = risk_filter
        self._time_estimator = time_estimator or TimeEstimator()
        self._ai_orchestrator = ai_orchestrator
        self._ws_manager = ws_manager

    async def start_review(
        self,
        contract: Contract,
        deal: Deal,
        deal_context: DealContext | None = None,
    ) -> Review:
        """Kick off the full review pipeline for a contract.

        Staged approach:
        1. Extract clauses from the contract
        2. Phase 1: Analyze critical clause types first (indemnification, MAC, reps)
        3. Phase 2: Analyze remaining clauses in parallel
        4. Run cross-clause pattern detection
        5. Create review batches grouping related clauses
        6. Route batches to the appropriate team members
        """
        context = deal_context or self._build_deal_context(deal)

        # Step 1: Decompose contract into clauses
        clauses = extract_clauses(contract)
        contract.clauses = clauses
        await self._store.save_contract(contract)

        # Step 2: Create the review
        review = Review(
            contract_id=contract.id,
            deal_id=deal.id,
        )

        # Step 3: Staged AI analysis — critical types first
        critical_clauses = [c for c in clauses if c.clause_type in CRITICAL_CLAUSE_TYPES]
        other_clauses = [c for c in clauses if c.clause_type not in CRITICAL_CLAUSE_TYPES]

        # Phase 1: Critical clauses
        critical_tasks = [
            self._analyzer.analyze_clause(clause, context) for clause in critical_clauses
        ]
        critical_reviews = await asyncio.gather(*critical_tasks) if critical_tasks else []

        # Phase 2: Remaining clauses
        other_tasks = [
            self._analyzer.analyze_clause(clause, context) for clause in other_clauses
        ]
        other_reviews = await asyncio.gather(*other_tasks) if other_tasks else []

        # Combine all clause reviews
        all_clause_reviews = list(critical_reviews) + list(other_reviews)
        for cr in all_clause_reviews:
            cr.review_id = review.id

        # Step 3b: Apply practical risk filter (gates 1-5 sync, gate 6 if AI available)
        if self._risk_filter:
            for cr in all_clause_reviews:
                clause = next((c for c in clauses if c.id == cr.clause_id), None)
                if clause and cr.ai_findings:
                    cr.ai_findings = self._risk_filter.validate_findings_sync(
                        cr.ai_findings, clause, context
                    )
                    # Recalculate aggregate risk after filtering
                    if cr.ai_findings:
                        severity_order = [
                            RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM,
                            RiskLevel.LOW, RiskLevel.INFORMATIONAL,
                        ]
                        cr.ai_risk_level = RiskLevel.INFORMATIONAL
                        for level in severity_order:
                            if any(f.risk_level == level for f in cr.ai_findings):
                                cr.ai_risk_level = level
                                break
                    else:
                        cr.ai_risk_level = RiskLevel.INFORMATIONAL

        # Step 3b+: AI agent enhancement — validate findings and draft revisions
        if self._ai_orchestrator and self._ai_orchestrator.available:
            for cr in all_clause_reviews:
                clause = next((c for c in clauses if c.id == cr.clause_id), None)
                if not clause or not cr.ai_findings:
                    continue
                for i, finding in enumerate(cr.ai_findings):
                    if finding.suppressed:
                        continue
                    # Gate 6: AI validation of practical risk
                    cr.ai_findings[i] = await self._ai_orchestrator.validate_finding_practical(
                        finding, clause, context
                    )
                    # Draft suggested language for high/critical unsuppressed findings
                    if not cr.ai_findings[i].suppressed and cr.ai_findings[i].risk_level in (
                        RiskLevel.CRITICAL, RiskLevel.HIGH
                    ):
                        revision = await self._ai_orchestrator.draft_suggested_language(
                            clause, cr.ai_findings[i], context,
                            market_benchmark=cr.ai_findings[i].market_comparison,
                        )
                        if revision:
                            cr.ai_findings[i].suggested_revision = revision

        # Step 3c: Round-aware — carry forward verdicts for unchanged clauses
        changed_clause_ids: set[str] | None = None
        if contract.previous_version_id:
            changed_clause_ids = await self._carry_forward_verdicts(
                contract, review, all_clause_reviews, clauses
            )

        review.clause_reviews = all_clause_reviews

        # Step 4: Cross-clause pattern detection
        cross_patterns = self._cross_clause.analyze_patterns(
            clauses, review.clause_reviews, context
        )
        review.cross_clause_patterns = cross_patterns

        # Step 5: Create review batches
        clause_type_map = {c.id: c.clause_type for c in clauses}
        batches = self._create_review_batches(review, clause_type_map)
        review.batches = batches

        # Step 6: Route to humans
        team = await self._store.get_team_for_deal(deal.id)
        for batch in batches:
            batch_reviews = [
                cr for cr in review.clause_reviews
                if cr.id in batch.clause_review_ids and cr.needs_human_review
            ]
            if batch_reviews:
                batch_types = [
                    clause_type_map.get(cr.clause_id)
                    for cr in batch_reviews
                    if clause_type_map.get(cr.clause_id)
                ]
                assigned = self._router.assign_batch(batch_reviews, team, batch_types)
                if assigned:
                    batch.assigned_to = assigned.id
                    for cr in batch_reviews:
                        cr.assigned_to = assigned.id
                        cr.stage = ReviewStage.HUMAN_REVIEW

        # Catch any unbatched clause reviews that need human review
        batched_ids = set()
        for b in batches:
            batched_ids.update(b.clause_review_ids)
        for cr in review.clause_reviews:
            if cr.id not in batched_ids and cr.needs_human_review:
                assigned = self._router.assign_reviewer(
                    cr, team, clause_type_map.get(cr.clause_id)
                )
                if assigned:
                    cr.assigned_to = assigned.id
                    cr.stage = ReviewStage.HUMAN_REVIEW

        # Update deal status
        deal.status = DealStatus.IN_REVIEW
        if review.id not in deal.review_ids:
            deal.review_ids.append(review.id)
        await self._store.save_deal(deal)
        await self._store.save_review(review)

        # Broadcast via WebSocket
        await self._broadcast(deal.id, {
            "event": "review_started",
            "review_id": review.id,
            "contract_id": contract.id,
            "clauses": len(clauses),
            "critical_findings": review.critical_findings_count,
            "cross_clause_patterns": len(cross_patterns),
            "batches": len(batches),
        })

        return review

    def _build_deal_context(self, deal: Deal) -> DealContext:
        """Build a DealContext from Deal model fields."""
        deal_value = None
        if deal.deal_value:
            try:
                deal_value = float(deal.deal_value.replace("$", "").replace(",", ""))
            except ValueError:
                pass

        return DealContext(
            deal_value=deal_value,
            deal_type=deal.deal_type,
            client_side=deal.client_side,
            jurisdiction=deal.jurisdiction,
            industry=deal.industry,
        )

    def _create_review_batches(
        self,
        review: Review,
        clause_type_map: dict[str, ClauseType],
    ) -> list[ReviewBatch]:
        """Group related clause reviews into batches for context continuity.

        Uses predefined batch groups (e.g., indemnification + reps + escrow).
        Priority is based on the highest risk in the batch.
        """
        # Map clause_review_id -> clause_type
        cr_type_map: dict[str, ClauseType] = {}
        for cr in review.clause_reviews:
            ct = clause_type_map.get(cr.clause_id)
            if ct:
                cr_type_map[cr.id] = ct

        assigned_cr_ids: set[str] = set()
        batches: list[ReviewBatch] = []
        priority_counter = 0

        severity = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 3,
            RiskLevel.INFORMATIONAL: 4,
        }

        for group in _BATCH_GROUPS:
            batch_cr_ids = []
            for cr in review.clause_reviews:
                ct = cr_type_map.get(cr.id)
                if ct and ct in group and cr.id not in assigned_cr_ids:
                    batch_cr_ids.append(cr.id)

            if len(batch_cr_ids) >= 2:
                # Calculate priority from highest risk in batch
                max_risk = max(
                    (
                        severity.get(cr.ai_risk_level, 4)
                        for cr in review.clause_reviews
                        if cr.id in batch_cr_ids
                    ),
                    default=4,
                )
                # Lower number = higher priority (invert severity)
                batch_priority = max_risk

                types_in_batch = {
                    cr_type_map[cr_id].value
                    for cr_id in batch_cr_ids
                    if cr_id in cr_type_map
                }

                batch = ReviewBatch(
                    clause_review_ids=batch_cr_ids,
                    priority=batch_priority,
                    rationale=f"Related clause types: {', '.join(sorted(types_in_batch))}",
                )
                batches.append(batch)
                assigned_cr_ids.update(batch_cr_ids)

        # Sort batches by priority (lowest number = highest priority)
        batches.sort(key=lambda b: b.priority)

        return batches

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
        review = await self._store.get_review(review_id)
        clause_review = next(
            (cr for cr in review.clause_reviews if cr.id == clause_review_id),
            None,
        )
        if not clause_review:
            raise ValueError(f"ClauseReview {clause_review_id} not found")

        clause_review.human_annotations.append(annotation)

        if annotation.verdict.value == "escalate":
            clause_review.stage = ReviewStage.ESCALATED
            team = await self._store.get_team_for_deal(review.deal_id)
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
                contract = await self._store.get_contract(review.contract_id)
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
            contract = await self._store.get_contract(review.contract_id)
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

        await self._store.save_review(review)

        # Check if all clause reviews are complete
        if all(cr.is_complete for cr in review.clause_reviews):
            review.completed_at = datetime.utcnow()
            await self._store.save_review(review)
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

    async def get_review_dashboard(self, review_id: str) -> dict:
        """Summary view for the team — what needs attention, what's done."""
        review = await self._store.get_review(review_id)

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
            "batches": len(review.batches),
            "by_stage": by_stage,
            "by_risk": by_risk,
            "is_complete": review.completed_at is not None,
        }

    async def _carry_forward_verdicts(
        self,
        contract: Contract,
        review: Review,
        all_clause_reviews: list[ClauseReview],
        clauses: list,
    ) -> set[str]:
        """For Round 2+, carry forward verdicts for unchanged clauses.

        Compares clause titles/types between versions. If a clause is unchanged,
        copies the previous verdict so humans only review changed/new clauses.
        Returns set of clause IDs that have changes (need human review).
        """
        previous_contract = await self._store.get_contract(contract.previous_version_id)
        if not previous_contract:
            return set(c.id for c in clauses)

        # Find previous review for the prior contract
        previous_review = None
        deal = await self._store.get_deal(review.deal_id)
        if deal:
            for rid in reversed(deal.review_ids):
                r = await self._store.get_review(rid)
                if r and r.contract_id == previous_contract.id:
                    previous_review = r
                    break

        if not previous_review:
            return set(c.id for c in clauses)

        # Build a lookup of previous clause reviews by (clause_type, title)
        prev_cr_lookup: dict[tuple[str, str], ClauseReview] = {}
        prev_clause_lookup: dict[str, object] = {}
        for pc in previous_contract.clauses:
            prev_clause_lookup[pc.id] = pc
        for pcr in previous_review.clause_reviews:
            pc = prev_clause_lookup.get(pcr.clause_id)
            if pc:
                key = (pc.clause_type.value, pc.title)
                prev_cr_lookup[key] = pcr

        changed_ids: set[str] = set()
        for i, cr in enumerate(all_clause_reviews):
            clause = next((c for c in clauses if c.id == cr.clause_id), None)
            if not clause:
                changed_ids.add(cr.clause_id)
                continue

            key = (clause.clause_type.value, clause.title)
            prev_cr = prev_cr_lookup.get(key)

            if prev_cr and prev_cr.is_complete:
                # Check if clause text is substantially the same
                prev_clause = prev_clause_lookup.get(prev_cr.clause_id)
                if prev_clause and hasattr(prev_clause, 'text') and prev_clause.text == clause.text:
                    # Carry forward — clause unchanged
                    cr.stage = ReviewStage.APPROVED
                    cr.final_risk_level = prev_cr.final_risk_level
                    cr.human_annotations = prev_cr.human_annotations
                    cr.human_completed_at = prev_cr.human_completed_at
                    continue

            changed_ids.add(cr.clause_id)

        return changed_ids

    async def get_time_dashboard(self, review_id: str, deal_context: DealContext | None = None) -> dict:
        """Get time budget dashboard for a review."""
        review = await self._store.get_review(review_id)
        team = await self._store.get_team_for_deal(review.deal_id)
        context = deal_context or DealContext()

        contract = await self._store.get_contract(review.contract_id)
        clauses = contract.clauses if contract else []
        clause_lookup = {c.id: c for c in clauses}

        return self._time_estimator.get_time_dashboard(
            review.clause_reviews, clause_lookup, team, context
        )

    async def _broadcast(self, deal_id: str, event: dict) -> None:
        """Send event to all connected WebSocket clients for this deal."""
        if self._ws_manager:
            await self._ws_manager.broadcast(deal_id, event)
