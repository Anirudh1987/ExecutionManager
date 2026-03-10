"""Learning feedback loop — improves AI analysis over time using human corrections.

Every time a human agrees, disagrees, or modifies an AI finding, that signal
is captured. Over time, this builds a corpus of corrections that:

1. Adjusts risk scoring thresholds per clause type
2. Identifies patterns the AI consistently gets wrong
3. Builds a precedent library from human-written revisions
4. Tracks per-reviewer tendencies (some are more conservative, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.models.review import (
    ClauseReview,
    HumanAnnotation,
    HumanVerdict,
    RiskLevel,
)
from src.models.contract import ClauseType


@dataclass
class FeedbackRecord:
    """A single learning signal from a human verdict."""

    clause_type: ClauseType
    ai_risk_level: RiskLevel
    human_verdict: HumanVerdict
    ai_finding_category: str
    ai_confidence: float
    human_revised_risk: RiskLevel | None
    reviewer_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AccuracyStats:
    """Accuracy metrics for a specific clause type or finding category."""

    total: int = 0
    agreements: int = 0
    disagreements: int = 0
    modifications: int = 0

    @property
    def agreement_rate(self) -> float:
        return self.agreements / self.total if self.total > 0 else 0.0

    @property
    def accuracy(self) -> float:
        """Agreement + modification (partial credit) rate."""
        if self.total == 0:
            return 0.0
        return (self.agreements + 0.5 * self.modifications) / self.total


class FeedbackLoop:
    """Collects and analyzes human feedback to improve future AI analysis."""

    def __init__(self):
        self._records: list[FeedbackRecord] = []

    def record_feedback(self, clause_review: ClauseReview) -> None:
        """Extract learning signals from a completed clause review."""
        for annotation in clause_review.human_annotations:
            # Find the AI finding this annotation responds to
            ai_category = "general"
            if annotation.finding_id:
                matching = [
                    f
                    for f in clause_review.ai_findings
                    if f.id == annotation.finding_id
                ]
                if matching:
                    ai_category = matching[0].category

            # We need the clause type — it's not on the review, so we
            # store the category from the AI finding as a proxy
            record = FeedbackRecord(
                clause_type=ClauseType.OTHER,  # resolved at query time
                ai_risk_level=clause_review.ai_risk_level,
                human_verdict=annotation.verdict,
                ai_finding_category=ai_category,
                ai_confidence=clause_review.ai_confidence,
                human_revised_risk=annotation.revised_risk_level,
                reviewer_id=annotation.reviewer_id,
            )
            self._records.append(record)

    def accuracy_by_category(self) -> dict[str, AccuracyStats]:
        """How accurate is the AI for each finding category?"""
        stats: dict[str, AccuracyStats] = {}

        for record in self._records:
            cat = record.ai_finding_category
            if cat not in stats:
                stats[cat] = AccuracyStats()

            stats[cat].total += 1
            if record.human_verdict == HumanVerdict.AGREE:
                stats[cat].agreements += 1
            elif record.human_verdict == HumanVerdict.DISAGREE:
                stats[cat].disagreements += 1
            elif record.human_verdict == HumanVerdict.MODIFY:
                stats[cat].modifications += 1

        return stats

    def confidence_calibration(self) -> list[dict]:
        """Are high-confidence findings actually more accurate?

        Groups findings by confidence bucket and checks agreement rate.
        Well-calibrated AI: 90% confidence → ~90% human agreement.
        """
        buckets: dict[str, AccuracyStats] = {}
        for record in self._records:
            bucket = f"{int(record.ai_confidence * 10) * 10}%"
            if bucket not in buckets:
                buckets[bucket] = AccuracyStats()
            buckets[bucket].total += 1
            if record.human_verdict == HumanVerdict.AGREE:
                buckets[bucket].agreements += 1
            elif record.human_verdict == HumanVerdict.DISAGREE:
                buckets[bucket].disagreements += 1

        return [
            {
                "confidence_bucket": bucket,
                "total": stats.total,
                "agreement_rate": stats.agreement_rate,
            }
            for bucket, stats in sorted(buckets.items())
        ]

    def risk_adjustment_suggestions(self) -> list[dict]:
        """Suggest risk level adjustments where AI consistently over/under-estimates.

        If humans frequently downgrade a risk level → AI is over-estimating.
        If humans frequently upgrade → AI is under-estimating.
        """
        suggestions = []

        for record in self._records:
            if record.human_revised_risk and record.human_revised_risk != record.ai_risk_level:
                suggestions.append({
                    "category": record.ai_finding_category,
                    "ai_level": record.ai_risk_level.value,
                    "human_level": record.human_revised_risk.value,
                    "direction": (
                        "over_estimated"
                        if _risk_severity(record.ai_risk_level)
                        > _risk_severity(record.human_revised_risk)
                        else "under_estimated"
                    ),
                })

        return suggestions

    def reviewer_patterns(self) -> dict[str, dict]:
        """Track per-reviewer tendencies for calibration awareness."""
        patterns: dict[str, dict] = {}

        for record in self._records:
            rid = record.reviewer_id
            if rid not in patterns:
                patterns[rid] = {"total": 0, "agree": 0, "disagree": 0, "modify": 0}

            patterns[rid]["total"] += 1
            if record.human_verdict == HumanVerdict.AGREE:
                patterns[rid]["agree"] += 1
            elif record.human_verdict == HumanVerdict.DISAGREE:
                patterns[rid]["disagree"] += 1
            elif record.human_verdict == HumanVerdict.MODIFY:
                patterns[rid]["modify"] += 1

        return patterns

    @property
    def total_feedback_count(self) -> int:
        return len(self._records)


def _risk_severity(risk: RiskLevel) -> int:
    """Numeric severity for comparison."""
    return {
        RiskLevel.CRITICAL: 4,
        RiskLevel.HIGH: 3,
        RiskLevel.MEDIUM: 2,
        RiskLevel.LOW: 1,
        RiskLevel.INFORMATIONAL: 0,
    }.get(risk, 0)
