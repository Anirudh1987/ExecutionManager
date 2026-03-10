"""AI-powered clause analysis — risk scoring, finding generation, and market comparison."""

from __future__ import annotations

import json
from datetime import datetime

from src.models.contract import Clause, ClauseType
from src.models.review import AIFinding, ClauseReview, RiskLevel, ReviewStage


# Risk patterns the AI checks for, organized by clause type.
# In production, these would be prompts sent to Claude; here they define
# the analysis framework.
RISK_PATTERNS: dict[ClauseType, list[dict]] = {
    ClauseType.REPRESENTATIONS_WARRANTIES: [
        {
            "category": "scope_gap",
            "description": "Missing standard representations (financial statements, litigation, compliance, IP ownership)",
            "baseline_risk": RiskLevel.HIGH,
        },
        {
            "category": "qualification_weakness",
            "description": "Over-qualified representations using 'to the knowledge of' or materiality scrapes",
            "baseline_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "survival_period",
            "description": "Survival periods shorter than market standard (12-24 months general, 36-72 months fundamental)",
            "baseline_risk": RiskLevel.HIGH,
        },
    ],
    ClauseType.INDEMNIFICATION: [
        {
            "category": "cap_analysis",
            "description": "Indemnification cap below market (typically 10-20% of purchase price for general, uncapped for fundamental)",
            "baseline_risk": RiskLevel.CRITICAL,
        },
        {
            "category": "basket_type",
            "description": "Deductible basket vs. tipping basket — impacts when buyer can claim",
            "baseline_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "exclusion_gaps",
            "description": "Key exclusions from indemnification (fraud, willful breach should never be excluded)",
            "baseline_risk": RiskLevel.CRITICAL,
        },
    ],
    ClauseType.MATERIAL_ADVERSE_CHANGE: [
        {
            "category": "mac_definition",
            "description": "MAC/MAE definition breadth — carve-outs for industry-wide changes, economy, pandemic",
            "baseline_risk": RiskLevel.CRITICAL,
        },
        {
            "category": "quantitative_threshold",
            "description": "Absence of quantitative threshold makes MAC subjective and hard to invoke",
            "baseline_risk": RiskLevel.HIGH,
        },
    ],
    ClauseType.TERMINATION: [
        {
            "category": "break_fee",
            "description": "Break fee outside market range (typically 2-4% of deal value)",
            "baseline_risk": RiskLevel.HIGH,
        },
        {
            "category": "tail_provisions",
            "description": "Missing or weak tail provisions after termination",
            "baseline_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.NON_COMPETE: [
        {
            "category": "scope_breadth",
            "description": "Non-compete scope (duration, geography, activity) — enforceability risk if too broad",
            "baseline_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.EARNOUT: [
        {
            "category": "metric_ambiguity",
            "description": "Vague or manipulable earnout metrics without clear accounting methodology",
            "baseline_risk": RiskLevel.CRITICAL,
        },
        {
            "category": "operational_control",
            "description": "Insufficient protections against buyer undermining earnout achievement",
            "baseline_risk": RiskLevel.HIGH,
        },
    ],
}

# Default patterns for clause types without specific rules
_DEFAULT_PATTERNS = [
    {
        "category": "market_deviation",
        "description": "Terms that deviate significantly from market standard for this clause type",
        "baseline_risk": RiskLevel.MEDIUM,
    },
    {
        "category": "missing_protection",
        "description": "Standard protective provisions that are absent",
        "baseline_risk": RiskLevel.MEDIUM,
    },
]


class ClauseAnalyzer:
    """Analyzes individual clauses and produces risk-scored findings.

    In production, this calls Claude to perform deep analysis.
    The framework here defines the analysis structure and scoring logic.
    """

    def __init__(self, ai_client=None):
        self._ai_client = ai_client

    async def analyze_clause(self, clause: Clause) -> ClauseReview:
        """Run full analysis on a clause and return a populated ClauseReview."""
        review = ClauseReview(
            clause_id=clause.id,
            review_id="",  # set by pipeline
            stage=ReviewStage.AI_ANALYZING,
        )

        if self._ai_client:
            findings = await self._ai_analyze(clause)
        else:
            findings = self._rule_based_analyze(clause)

        review.ai_findings = findings
        review.ai_risk_level = self._aggregate_risk(findings)
        review.ai_confidence = self._calculate_confidence(clause, findings)
        review.ai_summary = self._summarize_findings(clause, findings)
        review.ai_completed_at = datetime.utcnow()
        review.stage = ReviewStage.AI_COMPLETE

        return review

    async def _ai_analyze(self, clause: Clause) -> list[AIFinding]:
        """Use Claude to deeply analyze a clause. Returns structured findings."""
        patterns = RISK_PATTERNS.get(clause.clause_type, _DEFAULT_PATTERNS)
        pattern_descriptions = "\n".join(
            f"- {p['category']}: {p['description']}" for p in patterns
        )

        prompt = f"""Analyze this M&A contract clause and identify risks, issues, and deviations from market standard.

Clause Type: {clause.clause_type.value}
Section: {clause.section_reference}
Text:
{clause.text}

Check for these specific risk patterns:
{pattern_descriptions}

Also identify any other issues not covered above.

For each finding, provide:
1. category (from the patterns above, or a new category)
2. title (short, specific)
3. description (detailed explanation of the issue)
4. risk_level: critical, high, medium, low, or informational
5. confidence (0.0 to 1.0)
6. suggested_revision (proposed contract language to fix the issue)
7. market_comparison (how this compares to standard M&A terms)

Return as JSON array of findings."""

        response = await self._ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_ai_response(response.content[0].text)

    def _rule_based_analyze(self, clause: Clause) -> list[AIFinding]:
        """Fallback rule-based analysis when AI client is unavailable."""
        patterns = RISK_PATTERNS.get(clause.clause_type, _DEFAULT_PATTERNS)
        findings = []

        for pattern in patterns:
            finding = AIFinding(
                category=pattern["category"],
                title=f"Review needed: {pattern['description'][:60]}",
                description=pattern["description"],
                risk_level=pattern["baseline_risk"],
                confidence=0.5,  # low confidence — rules only
                market_comparison="Requires AI analysis for market comparison.",
            )
            findings.append(finding)

        return findings

    def _parse_ai_response(self, response_text: str) -> list[AIFinding]:
        """Parse Claude's JSON response into AIFinding objects."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]

            items = json.loads(text)
            findings = []
            for item in items:
                finding = AIFinding(
                    category=item.get("category", "general"),
                    title=item.get("title", "Untitled finding"),
                    description=item.get("description", ""),
                    risk_level=RiskLevel(item.get("risk_level", "medium")),
                    confidence=float(item.get("confidence", 0.7)),
                    suggested_revision=item.get("suggested_revision", ""),
                    market_comparison=item.get("market_comparison", ""),
                )
                findings.append(finding)
            return findings
        except (json.JSONDecodeError, ValueError, KeyError):
            # If parsing fails, return a single finding noting the issue
            return [
                AIFinding(
                    category="parse_error",
                    title="AI analysis requires manual review",
                    description="AI response could not be parsed. Manual review needed.",
                    risk_level=RiskLevel.MEDIUM,
                    confidence=0.0,
                )
            ]

    def _aggregate_risk(self, findings: list[AIFinding]) -> RiskLevel:
        """The overall risk is the highest risk among all findings."""
        if not findings:
            return RiskLevel.INFORMATIONAL

        severity_order = [
            RiskLevel.CRITICAL,
            RiskLevel.HIGH,
            RiskLevel.MEDIUM,
            RiskLevel.LOW,
            RiskLevel.INFORMATIONAL,
        ]

        for level in severity_order:
            if any(f.risk_level == level for f in findings):
                return level

        return RiskLevel.INFORMATIONAL

    def _calculate_confidence(
        self, clause: Clause, findings: list[AIFinding]
    ) -> float:
        """Overall confidence in the analysis, considering clause complexity."""
        if not findings:
            return 0.5

        avg_confidence = sum(f.confidence for f in findings) / len(findings)

        # Reduce confidence for very long or very short clauses
        text_len = len(clause.text)
        if text_len < 50:
            avg_confidence *= 0.7  # too short to be sure
        elif text_len > 5000:
            avg_confidence *= 0.85  # complex clause, more uncertainty

        return round(min(1.0, max(0.0, avg_confidence)), 2)

    def _summarize_findings(
        self, clause: Clause, findings: list[AIFinding]
    ) -> str:
        """Generate a human-readable summary of the analysis."""
        if not findings:
            return f"No issues identified in {clause.title}."

        critical = [f for f in findings if f.risk_level == RiskLevel.CRITICAL]
        high = [f for f in findings if f.risk_level == RiskLevel.HIGH]

        parts = [f"Analyzed '{clause.title}': {len(findings)} finding(s)."]

        if critical:
            parts.append(
                f"CRITICAL ({len(critical)}): "
                + "; ".join(f.title for f in critical)
            )
        if high:
            parts.append(
                f"HIGH ({len(high)}): " + "; ".join(f.title for f in high)
            )

        return " ".join(parts)
