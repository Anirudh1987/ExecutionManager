"""Review workflow models — the core of the human-in-the-loop system."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk severity assigned by AI analysis, determines routing priority."""

    CRITICAL = "critical"  # Must be reviewed by Strategist
    HIGH = "high"  # Strategist or Analyst
    MEDIUM = "medium"  # Analyst review
    LOW = "low"  # Auto-approved unless Coordinator flags
    INFORMATIONAL = "informational"  # No action needed, logged for completeness


class ReviewStage(str, Enum):
    """Pipeline stages a clause review moves through."""

    QUEUED = "queued"  # Waiting for AI analysis
    AI_ANALYZING = "ai_analyzing"  # AI is processing
    AI_COMPLETE = "ai_complete"  # AI done, awaiting human routing
    HUMAN_REVIEW = "human_review"  # Assigned to a team member
    NEEDS_DISCUSSION = "needs_discussion"  # Flagged for team discussion
    APPROVED = "approved"  # Human signed off
    REVISION_REQUESTED = "revision_requested"  # Issue found, needs contract revision
    ESCALATED = "escalated"  # Escalated to Strategist


class AIFinding(BaseModel):
    """A specific issue or observation the AI found in a clause."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: str  # e.g. "missing_protection", "unusual_term", "market_deviation"
    title: str
    description: str
    risk_level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_revision: str = ""
    market_comparison: str = ""  # how this compares to standard M&A terms
    precedent_notes: str = ""  # relevant precedent from past deals


class HumanVerdict(str, Enum):
    """The human reviewer's decision on an AI finding."""

    AGREE = "agree"  # AI was right, accept finding
    DISAGREE = "disagree"  # AI was wrong, dismiss finding
    MODIFY = "modify"  # Partially right, human refined the finding
    ESCALATE = "escalate"  # Needs senior/team review
    DEFER = "defer"  # Will decide later


class HumanAnnotation(BaseModel):
    """A human reviewer's response to an AI finding or independent observation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    finding_id: str | None = None  # links to AIFinding if responding to one
    reviewer_id: str
    verdict: HumanVerdict
    comment: str = ""
    revised_risk_level: RiskLevel | None = None
    suggested_language: str = ""  # proposed contract language
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ClauseReview(BaseModel):
    """The complete review record for a single clause — AI + human layers."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    clause_id: str
    review_id: str  # parent Review
    stage: ReviewStage = ReviewStage.QUEUED

    # AI layer
    ai_findings: list[AIFinding] = Field(default_factory=list)
    ai_risk_level: RiskLevel = RiskLevel.INFORMATIONAL
    ai_summary: str = ""
    ai_confidence: float = 0.0
    ai_completed_at: datetime | None = None

    # Human layer
    assigned_to: str | None = None
    human_annotations: list[HumanAnnotation] = Field(default_factory=list)
    final_risk_level: RiskLevel | None = None
    human_started_at: datetime | None = None  # when reviewer first opened
    human_completed_at: datetime | None = None

    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def needs_human_review(self) -> bool:
        """Clauses with risk >= MEDIUM or low AI confidence need human eyes."""
        return (
            self.ai_risk_level
            in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM)
            or self.ai_confidence < 0.7
        )

    @property
    def review_duration_minutes(self) -> float | None:
        """Time from reviewer opening the clause to submitting verdict."""
        if self.human_started_at and self.human_completed_at:
            delta = self.human_completed_at - self.human_started_at
            return round(delta.total_seconds() / 60, 1)
        return None

    @property
    def is_complete(self) -> bool:
        if self.stage in (ReviewStage.APPROVED, ReviewStage.REVISION_REQUESTED):
            return True
        if self.stage == ReviewStage.AI_COMPLETE and not self.needs_human_review:
            return True
        return False


class CrossClausePattern(BaseModel):
    """A pattern detected across multiple clauses that creates risk."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pattern_type: str  # e.g. "indemnification_vs_reps", "mac_vs_conditions"
    title: str
    description: str
    clauses_involved: list[str] = Field(default_factory=list)  # clause IDs
    risk_level: RiskLevel = RiskLevel.MEDIUM
    interaction_score: float = 0.0  # 0=no issue, 1=severe mismatch
    evidence: list[str] = Field(default_factory=list)  # supporting text excerpts
    recommendation: str = ""


class ReviewBatch(BaseModel):
    """A group of related clause reviews assigned together for context continuity."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    clause_review_ids: list[str] = Field(default_factory=list)
    priority: int = 0  # lower = higher priority
    rationale: str = ""
    assigned_to: str | None = None


class DealContext(BaseModel):
    """Business context that influences risk assessment."""

    deal_value: float | None = None
    deal_type: str = ""  # acquisition, merger, asset purchase, etc.
    client_side: str = "buyer"  # buyer or seller
    jurisdiction: str = ""
    industry: str = ""


class Review(BaseModel):
    """Top-level review for an entire contract, containing clause-level reviews."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contract_id: str
    deal_id: str
    clause_reviews: list[ClauseReview] = Field(default_factory=list)
    cross_clause_patterns: list[CrossClausePattern] = Field(default_factory=list)
    batches: list[ReviewBatch] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def progress(self) -> float:
        if not self.clause_reviews:
            return 0.0
        done = sum(1 for cr in self.clause_reviews if cr.is_complete)
        return done / len(self.clause_reviews)

    @property
    def critical_findings_count(self) -> int:
        return sum(
            1
            for cr in self.clause_reviews
            if cr.ai_risk_level == RiskLevel.CRITICAL
        )

    @property
    def pending_human_reviews(self) -> list[ClauseReview]:
        return [
            cr
            for cr in self.clause_reviews
            if cr.needs_human_review
            and cr.stage
            not in (ReviewStage.APPROVED, ReviewStage.REVISION_REQUESTED)
        ]
