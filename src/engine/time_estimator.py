"""Time estimation and budget allocation for the 7-9 hour review constraint.

Estimates how long each clause review will take a human reviewer at 160 wpm,
allocates time budget across team members by role, and tracks real-time usage.
"""

from __future__ import annotations

from src.models.review import ClauseReview, DealContext, RiskLevel
from src.models.contract import Clause
from src.models.team import Role, TeamMember


READING_SPEED_WPM = 160
DECISION_TIME_MINUTES = 0.5  # per finding
MODIFICATION_TIME_MINUTES = 2.0  # if reviewer needs to write suggested language
DEFAULT_TIME_BUDGET = 540.0  # 9 hours in minutes


def word_count(text: str) -> int:
    """Count words in a string."""
    return len(text.split()) if text else 0


class TimeEstimator:
    """Estimates human review time per clause to stay within budget."""

    def estimate_review_time(
        self,
        clause_review: ClauseReview,
        clause: Clause | None = None,
    ) -> float:
        """Estimate minutes for a human to review this clause.

        Components:
        - Summary reading: word_count(ai_summary) / 160
        - Finding reading: sum of (description + suggested_revision) / 160
        - Decision time: 0.5 min per finding
        - Modification time: +2 min if risk >= HIGH (likely needs written feedback)
        """
        minutes = 0.0

        # Read AI summary
        summary_words = word_count(clause_review.ai_summary)
        minutes += summary_words / READING_SPEED_WPM

        # Read each finding
        for finding in clause_review.ai_findings:
            if finding.suppressed:
                continue
            finding_words = word_count(finding.description)
            finding_words += word_count(finding.suggested_revision)
            finding_words += word_count(finding.market_comparison)
            minutes += finding_words / READING_SPEED_WPM
            minutes += DECISION_TIME_MINUTES

        # If high risk, reviewer likely writes comments
        if clause_review.ai_risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
            minutes += MODIFICATION_TIME_MINUTES

        # Minimum 1 minute per clause
        return max(1.0, round(minutes, 1))

    def allocate_budget(
        self,
        clause_reviews: list[ClauseReview],
        team: list[TeamMember],
        deal_context: DealContext | None = None,
    ) -> dict[str, list[tuple[str, float]]]:
        """Allocate time budget across team members by role.

        Returns: {reviewer_id: [(clause_review_id, estimated_minutes), ...]}
        """
        budget = deal_context.time_budget_minutes if deal_context else DEFAULT_TIME_BUDGET
        allocation: dict[str, list[tuple[str, float]]] = {}

        for member in team:
            allocation[member.id] = []

        # Group reviews by target role
        role_map = {
            RiskLevel.CRITICAL: Role.STRATEGIST,
            RiskLevel.HIGH: Role.STRATEGIST,
            RiskLevel.MEDIUM: Role.ANALYST,
            RiskLevel.LOW: Role.COORDINATOR,
            RiskLevel.INFORMATIONAL: Role.COORDINATOR,
        }

        for cr in clause_reviews:
            if not cr.needs_human_review:
                continue

            target_role = role_map.get(cr.ai_risk_level, Role.ANALYST)
            est_time = self.estimate_review_time(cr)

            # Find team member with target role who has budget remaining
            assigned = False
            for member in team:
                if member.role == target_role and member.is_active:
                    current_total = sum(t for _, t in allocation[member.id])
                    if current_total + est_time <= budget:
                        allocation[member.id].append((cr.id, est_time))
                        assigned = True
                        break

            # Fallback: any member with budget
            if not assigned:
                for member in team:
                    if member.is_active:
                        current_total = sum(t for _, t in allocation[member.id])
                        if current_total + est_time <= budget:
                            allocation[member.id].append((cr.id, est_time))
                            break

        return allocation

    def get_time_dashboard(
        self,
        team: list[TeamMember],
        clause_reviews: list[ClauseReview],
        deal_context: DealContext | None = None,
    ) -> dict:
        """Real-time time tracking dashboard."""
        budget = deal_context.time_budget_minutes if deal_context else DEFAULT_TIME_BUDGET
        round_num = deal_context.negotiation_round if deal_context else 1

        team_data = []
        total_used = 0.0
        total_remaining_items = 0

        for member in team:
            # Items assigned to this member
            my_items = [
                cr for cr in clause_reviews
                if cr.assigned_to == member.id and not cr.is_complete
            ]
            completed = [
                cr for cr in clause_reviews
                if cr.assigned_to == member.id and cr.is_complete
            ]

            # Estimate time used from completed reviews
            used = sum(
                (cr.review_duration_minutes or 2.0) for cr in completed
            )
            # Estimate remaining
            est_remaining = sum(
                self.estimate_review_time(cr) for cr in my_items
            )

            total_used += used
            total_remaining_items += len(my_items)

            team_data.append({
                "name": member.name,
                "role": member.role.value,
                "budget_min": budget,
                "used_min": round(used, 1),
                "items_remaining": len(my_items),
                "est_remaining_min": round(est_remaining, 1),
                "on_track": (used + est_remaining) <= budget,
            })

        total_items = len(clause_reviews)
        completed_items = sum(1 for cr in clause_reviews if cr.is_complete)
        progress = completed_items / total_items if total_items else 0.0

        warnings = []
        for td in team_data:
            if not td["on_track"]:
                warnings.append(
                    f"{td['name']} ({td['role']}) may exceed time budget: "
                    f"{td['used_min'] + td['est_remaining_min']:.0f}min estimated vs {budget:.0f}min budget"
                )

        return {
            "round": round_num,
            "team": team_data,
            "overall_progress": round(progress, 2),
            "on_track": all(td["on_track"] for td in team_data),
            "warnings": warnings,
        }
