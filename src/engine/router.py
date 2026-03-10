"""Smart routing — assigns clause reviews to the right team member.

Routing logic:
  CRITICAL/HIGH risk → Strategist (senior lawyer, deal-critical decisions)
  MEDIUM risk or low AI confidence → Analyst (validates AI findings)
  LOW/INFORMATIONAL → Coordinator (auto-approve or quick check)

Load balancing: within a role, prefer the team member with the lowest
capacity_score (fewest active reviews adjusted by avg review time).
"""

from __future__ import annotations

from src.models.review import ClauseReview, RiskLevel
from src.models.team import Role, TeamMember, ROLE_RISK_ROUTING


class ReviewRouter:
    """Routes clause reviews to team members based on risk and workload."""

    def assign_reviewer(
        self,
        clause_review: ClauseReview,
        team: list[TeamMember],
    ) -> TeamMember | None:
        """Pick the best team member for this clause review."""
        target_role = self._determine_role(clause_review)
        candidates = [m for m in team if m.role == target_role and m.is_active]

        if not candidates:
            # Fallback: any active team member
            candidates = [m for m in team if m.is_active]

        if not candidates:
            return None

        # Load-balance: pick the member with the most capacity
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
