"""AI-powered clause analysis — risk scoring, finding generation, and market comparison.

Covers all 18 M&A clause types with specific risk patterns.
Supports DealContext for buyer/seller-aware risk assessment.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from src.models.contract import Clause, ClauseType
from src.models.review import AIFinding, ClauseReview, DealContext, RiskLevel, ReviewStage


# Risk patterns the AI checks for, organized by clause type.
# Each pattern has a buyer_risk and seller_risk to adjust by perspective.
RISK_PATTERNS: dict[ClauseType, list[dict]] = {
    ClauseType.REPRESENTATIONS_WARRANTIES: [
        {
            "category": "scope_gap",
            "description": "Missing standard representations (financial statements, litigation, compliance, IP ownership)",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "qualification_weakness",
            "description": "Over-qualified representations using 'to the knowledge of' or materiality scrapes",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.INFORMATIONAL,
        },
        {
            "category": "survival_period",
            "description": "Survival periods shorter than market standard (12-24 months general, 36-72 months fundamental)",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
    ],
    ClauseType.INDEMNIFICATION: [
        {
            "category": "cap_analysis",
            "description": "Indemnification cap below market (typically 10-20% of purchase price for general, uncapped for fundamental)",
            "buyer_risk": RiskLevel.CRITICAL,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "basket_type",
            "description": "Deductible basket vs. tipping basket — impacts when buyer can claim",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "exclusion_gaps",
            "description": "Key exclusions from indemnification (fraud, willful breach should never be excluded)",
            "buyer_risk": RiskLevel.CRITICAL,
            "seller_risk": RiskLevel.CRITICAL,
        },
    ],
    ClauseType.MATERIAL_ADVERSE_CHANGE: [
        {
            "category": "mac_definition",
            "description": "MAC/MAE definition breadth — carve-outs for industry-wide changes, economy, pandemic",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.CRITICAL,
        },
        {
            "category": "quantitative_threshold",
            "description": "Absence of quantitative threshold makes MAC subjective and hard to invoke",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.TERMINATION: [
        {
            "category": "break_fee",
            "description": "Break fee outside market range (typically 2-4% of deal value)",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "tail_provisions",
            "description": "Missing or weak tail provisions after termination",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.NON_COMPETE: [
        {
            "category": "scope_breadth",
            "description": "Non-compete scope (duration, geography, activity) — enforceability risk if too broad",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "carve_outs",
            "description": "Missing carve-outs for passive investments or pre-existing activities",
            "buyer_risk": RiskLevel.LOW,
            "seller_risk": RiskLevel.HIGH,
        },
    ],
    ClauseType.EARNOUT: [
        {
            "category": "metric_ambiguity",
            "description": "Vague or manipulable earnout metrics without clear accounting methodology",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.CRITICAL,
        },
        {
            "category": "operational_control",
            "description": "Insufficient protections against buyer undermining earnout achievement",
            "buyer_risk": RiskLevel.LOW,
            "seller_risk": RiskLevel.CRITICAL,
        },
    ],
    ClauseType.CONDITIONS_PRECEDENT: [
        {
            "category": "regulatory_gap",
            "description": "Missing regulatory approval condition (antitrust, foreign investment, sector-specific)",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "no_litigation_condition",
            "description": "No condition regarding absence of material litigation or proceedings",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "overly_broad_conditions",
            "description": "Conditions so broad they give one party effective walk-away right",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.CRITICAL,
        },
    ],
    ClauseType.COVENANTS: [
        {
            "category": "ordinary_course",
            "description": "Missing or vague ordinary course of business covenant between signing and closing",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "commercially_reasonable",
            "description": "Vague 'commercially reasonable efforts' without specific performance benchmarks",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "no_shop",
            "description": "Missing or weak no-shop provision — target free to solicit competing bids",
            "buyer_risk": RiskLevel.CRITICAL,
            "seller_risk": RiskLevel.LOW,
        },
    ],
    ClauseType.CLOSING_MECHANICS: [
        {
            "category": "working_capital",
            "description": "Missing working capital adjustment or unclear true-up mechanism",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "bring_down",
            "description": "No bring-down of representations at closing",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "payment_mechanics",
            "description": "Unclear payment instructions or missing escrow/holdback at closing",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.CONFIDENTIALITY: [
        {
            "category": "overbroad_exceptions",
            "description": "Confidentiality exceptions too broad (e.g., 'as required by law' without specifics)",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "duration",
            "description": "Confidentiality period insufficient (standard: 2-3 years post-closing)",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "legal_proceedings_carveout",
            "description": "No carve-out permitting disclosure in legal proceedings with notice",
            "buyer_risk": RiskLevel.LOW,
            "seller_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.INTELLECTUAL_PROPERTY: [
        {
            "category": "ip_assignment",
            "description": "Missing or incomplete IP assignment — key assets may not transfer",
            "buyer_risk": RiskLevel.CRITICAL,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "license_scope",
            "description": "Inadequate license scope — retained licenses too narrow or too broad",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "open_source",
            "description": "No open-source audit or copyleft contamination review",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
    ],
    ClauseType.EMPLOYEE_MATTERS: [
        {
            "category": "key_employee_retention",
            "description": "Missing key employee retention provisions or change-of-control protections",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "benefit_continuation",
            "description": "Inadequate employee benefit continuation or transition provisions",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "severance_exposure",
            "description": "Unclear severance obligations triggered by the transaction",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.HIGH,
        },
    ],
    ClauseType.TAX: [
        {
            "category": "tax_indemnification",
            "description": "Missing pre-closing tax indemnification — buyer inherits unknown tax liabilities",
            "buyer_risk": RiskLevel.CRITICAL,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "transfer_tax",
            "description": "Unclear transfer tax allocation between buyer and seller",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "tax_rep_survival",
            "description": "Tax representations do not survive closing or have insufficient survival period",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
    ],
    ClauseType.GOVERNING_LAW: [
        {
            "category": "unfavorable_jurisdiction",
            "description": "Governing law jurisdiction unfavorable to client's position",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "service_of_process",
            "description": "Missing service of process provisions for cross-border transactions",
            "buyer_risk": RiskLevel.LOW,
            "seller_risk": RiskLevel.LOW,
        },
    ],
    ClauseType.DISPUTE_RESOLUTION: [
        {
            "category": "escalation_procedure",
            "description": "Missing escalation procedure before formal dispute resolution",
            "buyer_risk": RiskLevel.LOW,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "interim_relief",
            "description": "No provision for interim or injunctive relief pending dispute resolution",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
        {
            "category": "arbitration_seat",
            "description": "Unclear or unfavorable seat of arbitration",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.ESCROW: [
        {
            "category": "insufficient_amount",
            "description": "Escrow amount insufficient relative to indemnification exposure",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
        {
            "category": "release_conditions",
            "description": "Unclear or one-sided escrow release conditions",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "joint_instructions",
            "description": "Missing requirement for joint instructions to escrow agent",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.MEDIUM,
        },
    ],
    ClauseType.PURCHASE_PRICE: [
        {
            "category": "adjustment_mechanisms",
            "description": "Missing price adjustment mechanisms (working capital, net debt, net cash)",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "payment_timing",
            "description": "Unclear payment timing or conditions for deferred consideration",
            "buyer_risk": RiskLevel.MEDIUM,
            "seller_risk": RiskLevel.HIGH,
        },
        {
            "category": "locked_box",
            "description": "Locked-box mechanism without adequate leakage protections",
            "buyer_risk": RiskLevel.HIGH,
            "seller_risk": RiskLevel.LOW,
        },
    ],
}

# Default patterns for clause types without specific rules
_DEFAULT_PATTERNS = [
    {
        "category": "market_deviation",
        "description": "Terms that deviate significantly from market standard for this clause type",
        "buyer_risk": RiskLevel.MEDIUM,
        "seller_risk": RiskLevel.MEDIUM,
    },
    {
        "category": "missing_protection",
        "description": "Standard protective provisions that are absent",
        "buyer_risk": RiskLevel.MEDIUM,
        "seller_risk": RiskLevel.MEDIUM,
    },
]

# Clause types that are highest-priority for M&A review
CRITICAL_CLAUSE_TYPES = {
    ClauseType.INDEMNIFICATION,
    ClauseType.REPRESENTATIONS_WARRANTIES,
    ClauseType.MATERIAL_ADVERSE_CHANGE,
    ClauseType.PURCHASE_PRICE,
    ClauseType.CONDITIONS_PRECEDENT,
}

# Average clause lengths by type (for confidence scoring)
_AVG_CLAUSE_LENGTHS: dict[ClauseType, int] = {
    ClauseType.REPRESENTATIONS_WARRANTIES: 3000,
    ClauseType.INDEMNIFICATION: 2000,
    ClauseType.MATERIAL_ADVERSE_CHANGE: 1500,
    ClauseType.TERMINATION: 1000,
    ClauseType.CONDITIONS_PRECEDENT: 1500,
    ClauseType.COVENANTS: 2000,
    ClauseType.PURCHASE_PRICE: 800,
}


class ClauseAnalyzer:
    """Analyzes individual clauses and produces risk-scored findings.

    Supports DealContext for buyer/seller-aware risk assessment.
    In production, this calls Claude to perform deep analysis.
    """

    def __init__(self, ai_client=None, precedent_library=None):
        self._ai_client = ai_client
        self._precedent_library = precedent_library

    async def analyze_clause(
        self, clause: Clause, deal_context: DealContext | None = None
    ) -> ClauseReview:
        """Run full analysis on a clause and return a populated ClauseReview."""
        review = ClauseReview(
            clause_id=clause.id,
            review_id="",  # set by pipeline
            stage=ReviewStage.AI_ANALYZING,
        )

        context = deal_context or DealContext()

        if self._ai_client:
            findings = await self._ai_analyze(clause, context)
        else:
            findings = self._rule_based_analyze(clause, context)

        # Enrich findings with precedent notes
        if self._precedent_library:
            precedents = self._precedent_library.find_precedents(
                clause.clause_type,
                keywords=clause.key_terms or [clause.title],
            )
            if precedents:
                precedent_text = "; ".join(
                    f"[{p.finding_category}] {p.revised_text[:100]}"
                    for p in precedents[:3]
                )
                for finding in findings:
                    if not finding.precedent_notes:
                        finding.precedent_notes = f"Related precedents: {precedent_text}"

        review.ai_findings = findings
        review.ai_risk_level = self._aggregate_risk(findings)
        review.ai_confidence = self._calculate_confidence(clause, findings, context)
        review.ai_summary = self._summarize_findings(clause, findings)
        review.ai_completed_at = datetime.utcnow()
        review.stage = ReviewStage.AI_COMPLETE

        return review

    async def _ai_analyze(
        self, clause: Clause, context: DealContext
    ) -> list[AIFinding]:
        """Use Claude to deeply analyze a clause. Returns structured findings."""
        patterns = RISK_PATTERNS.get(clause.clause_type, _DEFAULT_PATTERNS)
        pattern_descriptions = "\n".join(
            f"- {p['category']}: {p['description']}" for p in patterns
        )

        perspective = (
            f"Analyze from the {context.client_side}'s perspective."
            if context.client_side
            else ""
        )
        deal_info = ""
        if context.deal_value:
            deal_info += f"\nDeal value: ${context.deal_value:,.0f}"
        if context.deal_type:
            deal_info += f"\nDeal type: {context.deal_type}"
        if context.industry:
            deal_info += f"\nIndustry: {context.industry}"
        if context.jurisdiction:
            deal_info += f"\nJurisdiction: {context.jurisdiction}"

        prompt = f"""Analyze this M&A contract clause and identify risks, issues, and deviations from market standard.
{perspective}{deal_info}

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

    def _rule_based_analyze(
        self, clause: Clause, context: DealContext
    ) -> list[AIFinding]:
        """Fallback rule-based analysis when AI client is unavailable.

        Uses DealContext.client_side to pick buyer_risk or seller_risk.
        """
        patterns = RISK_PATTERNS.get(clause.clause_type, _DEFAULT_PATTERNS)
        findings = []
        risk_key = "seller_risk" if context.client_side == "seller" else "buyer_risk"

        for pattern in patterns:
            risk_level = pattern.get(risk_key, pattern.get("buyer_risk", RiskLevel.MEDIUM))

            finding = AIFinding(
                category=pattern["category"],
                title=f"Review needed: {pattern['description'][:60]}",
                description=pattern["description"],
                risk_level=risk_level,
                confidence=0.5,  # low confidence — rules only
                market_comparison="Requires AI analysis for market comparison.",
            )
            findings.append(finding)

        return findings

    def _parse_ai_response(self, response_text: str) -> list[AIFinding]:
        """Parse Claude's JSON response into AIFinding objects."""
        try:
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
        self, clause: Clause, findings: list[AIFinding], context: DealContext
    ) -> float:
        """Multi-factor confidence scoring.

        Factors:
        1. Average finding confidence
        2. Clause length relative to type average
        3. Monetary value extraction (specific amounts -> higher confidence)
        4. Precedent library match strength
        """
        if not findings:
            return 0.5

        # Factor 1: Average finding confidence
        avg_confidence = sum(f.confidence for f in findings) / len(findings)

        # Factor 2: Clause length relative to type average
        text_len = len(clause.text)
        avg_len = _AVG_CLAUSE_LENGTHS.get(clause.clause_type, 1000)
        if text_len < 50:
            length_factor = 0.7
        elif text_len > avg_len * 3:
            length_factor = 0.85
        else:
            length_factor = 1.0

        # Factor 3: Monetary values found -> higher specificity
        has_amounts = bool(re.search(r'\$[\d,]+', clause.text))
        specificity_factor = 1.05 if has_amounts else 0.95

        # Factor 4: Precedent match
        precedent_factor = 1.0
        if self._precedent_library:
            precedents = self._precedent_library.find_precedents(
                clause.clause_type,
                keywords=clause.key_terms or [clause.title],
            )
            if precedents:
                precedent_factor = 1.1

        score = avg_confidence * length_factor * specificity_factor * precedent_factor
        return round(min(1.0, max(0.0, score)), 2)

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
