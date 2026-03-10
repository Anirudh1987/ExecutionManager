"""Smart routing — assigns clause reviews to the right team member.

Routing logic (in priority order):
  1. Specialist match: reviewer who specializes in this clause type
  2. Risk-based role: CRITICAL/HIGH → Strategist, MEDIUM → Analyst, LOW → Coordinator
  3. Workload cap: never exceed max_active_reviews
  4. Load balancing: within candidates, prefer lowest capacity_score

Batch-aware routing prefers assigning related clauses to the same reviewer
for context continuity.
"""

from __future__ import annotations

from src.models.contract import ClauseType
from src.models.review import ClauseReview, RiskLevel
from src.models.team import Role, TeamMember, ROLE_RISK_ROUTING


class ReviewRouter:
    """Routes clause reviews to team members based on specialization, risk, and workload."""

    def assign_reviewer(
        self,
        clause_review: ClauseReview,
        team: list[TeamMember],
        clause_type: ClauseType | None = None,
    ) -> TeamMember | None:
        """Pick the best team member for this clause review.

        Priority:
        1. Specialist with capacity (if clause_type provided)
        2. Target role with capacity (risk-based routing)
        3. Any active member with capacity (fallback)
        """
        target_role = self._determine_role(clause_review)

        # Filter to members with capacity
        available = [
            m for m in team
            if m.is_active and m.active_reviews < m.max_active_reviews
        ]

        if not available:
            # All at capacity — fall back to any active member
            available = [m for m in team if m.is_active]
            if not available:
                return None

        # Priority 1: Specialist with capacity in the target role
        if clause_type:
            specialists = [
                m for m in available
                if clause_type.value in m.specializations and m.role == target_role
            ]
            if specialists:
                return self._pick_best(specialists)

            # Specialist in any role (cross-role specialization)
            specialists = [
                m for m in available
                if clause_type.value in m.specializations
            ]
            if specialists:
                return self._pick_best(specialists)

        # Priority 2: Target role
        role_match = [m for m in available if m.role == target_role]
        if role_match:
            return self._pick_best(role_match)

        # Priority 3: Any available
        return self._pick_best(available)

    def assign_batch(
        self,
        clause_reviews: list[ClauseReview],
        team: list[TeamMember],
        clause_types: list[ClauseType] | None = None,
    ) -> TeamMember | None:
        """Assign a batch of related clause reviews to a single reviewer.

        Picks the best reviewer for the highest-risk item in the batch,
        then assigns all items to that reviewer for context continuity.
        """
        if not clause_reviews:
            return None

        # Find highest-risk review in batch
        severity = {
            RiskLevel.CRITICAL: 0,
            RiskLevel.HIGH: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.LOW: 3,
            RiskLevel.INFORMATIONAL: 4,
        }
        highest = min(clause_reviews, key=lambda cr: severity.get(cr.ai_risk_level, 4))

        # Determine most common clause type for specialization matching
        primary_type = None
        if clause_types:
            type_counts: dict[ClauseType, int] = {}
            for ct in clause_types:
                type_counts[ct] = type_counts.get(ct, 0) + 1
            primary_type = max(type_counts, key=type_counts.get)

        assigned = self.assign_reviewer(highest, team, primary_type)

        if assigned:
            # Count all items in the batch toward workload
            assigned.active_reviews += len(clause_reviews) - 1  # -1 because assign_reviewer already added 1

        return assigned

    def _pick_best(self, candidates: list[TeamMember]) -> TeamMember:
        """Pick the member with the most capacity (lowest capacity_score)."""
        candidates.sort(key=lambda m: m.capacity_score)
        chosen = candidates[0]
        chosen.active_reviews += 1
        return chosen

    def _determine_role(self, clause_review: ClauseReview) -> Role:
        """Map risk level to the appropriate role."""
        risk = clause_review.ai_risk_level

        if risk in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            return Role.STRATEGIST
        elif risk == RiskLevel.MEDIUM or clause_review.ai_confidence < 0.7:
            return Role.ANALYST
        else:
            return Role.COORDINATOR

    def get_strategist(self, team: list[TeamMember]) -> TeamMember | None:
        """Find the active Strategist for escalations."""
        for member in team:
            if member.role == Role.STRATEGIST and member.is_active:
                return member
        return None
