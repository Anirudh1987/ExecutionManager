"""Team model — the 3-person review team with distinct roles."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Three roles optimized for M&A review throughput and quality.

    Strategist: Senior lawyer focused on deal-critical risks and client advisory.
        Only sees CRITICAL/HIGH items and cross-clause patterns.

    Analyst: Reviews AI findings clause-by-clause, validates accuracy,
        catches what AI missed. Handles MEDIUM risk and uncertain items.

    Coordinator: Manages pipeline flow, tracks completeness, handles
        LOW risk auto-approvals, prepares client deliverables.
    """

    STRATEGIST = "strategist"
    ANALYST = "analyst"
    COORDINATOR = "coordinator"


# What risk levels each role handles by default
ROLE_RISK_ROUTING: dict[Role, list[str]] = {
    Role.STRATEGIST: ["critical", "high"],
    Role.ANALYST: ["medium"],
    Role.COORDINATOR: ["low", "informational"],
}


class TeamMember(BaseModel):
    """A member of the 3-person review team."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: str
    role: Role
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Workload tracking
    active_reviews: int = 0
    completed_reviews: int = 0
    average_review_minutes: float = 0.0

    @property
    def capacity_score(self) -> float:
        """Lower is better — used for load balancing assignments."""
        if not self.is_active:
            return float("inf")
        return self.active_reviews * (1 + self.average_review_minutes / 60)
