"""Practical risk filter — 6-gate validation to eliminate false positives.

Every AI finding passes through 6 validation gates before reaching a human:
1. Financial materiality threshold
2. Indian court enforceability discount
3. Deal-context proportionality
4. Boilerplate detection
5. Feedback-calibrated confidence
6. AI Validator Agent (Claude-powered)

Each gate can downgrade or suppress a finding. Suppressed findings are saved
for audit trail but not shown to humans by default.
"""

from __future__ import annotations

import re

from src.models.contract import Clause, ClauseType
from src.models.review import AIFinding, DealContext, RiskLevel


# ---------------------------------------------------------------------------
# Gate 1: Financial Materiality Thresholds
# ---------------------------------------------------------------------------

MATERIALITY_THRESHOLDS: dict[str, float] = {
    "default": 1.0,       # 1% of deal value
    "pe_investment": 0.5,  # PE investors care about smaller exposures
    "acquisition": 2.0,    # Acquisitions have higher baseline
}


# ---------------------------------------------------------------------------
# Gate 2: Indian Court Enforceability Discounts
# ---------------------------------------------------------------------------

ENFORCEABILITY_DISCOUNTS: dict[str, dict] = {
    "non_compete_over_3_years": {
        "clause_types": [ClauseType.NON_COMPETE],
        "pattern": r"(?:5|6|7|8|9|10)\s*(?:year|yr)",
        "reason": "Indian Contract Act S.27 — restraint of trade void. Courts rarely enforce >3 years.",
        "case_law": "Pepsi Foods v. Bharat Coca Cola (2003); Wipro v. Beckman Coulter (2006)",
        "risk_discount": 0.5,
    },
    "penalty_clauses": {
        "clause_types": [ClauseType.INDEMNIFICATION, ClauseType.TERMINATION],
        "pattern": r"(?:liquidated damages|penalty|penal)",
        "reason": "Indian Contract Act S.74 — only 'reasonable compensation' enforceable.",
        "case_law": "ONGC v. Saw Pipes (2003); Kailash Nath v. DDA (2015)",
        "risk_discount": 0.4,
    },
    "exclusive_jurisdiction": {
        "clause_types": [ClauseType.GOVERNING_LAW, ClauseType.DISPUTE_RESOLUTION],
        "pattern": r"exclusive jurisdiction",
        "reason": "Indian courts override exclusive jurisdiction if cause of action arose elsewhere.",
        "case_law": "",
        "risk_discount": 0.3,
    },
    "indemnity_without_cap_related_party": {
        "clause_types": [ClauseType.INDEMNIFICATION],
        "pattern": r"(?:unlimited|no cap|no limit)",
        "reason": "Unlimited indemnity between affiliates is standard in group restructurings.",
        "case_law": "",
        "risk_discount": 0.8,
        "applies_when_deal_type": ["restructuring", "group_restructuring", "internal"],
    },
}


# ---------------------------------------------------------------------------
# Gate 3: Deal-Context Proportionality
# ---------------------------------------------------------------------------

# Small deal thresholds (in same currency as deal_value)
SMALL_DEAL_THRESHOLD = 10_00_00_000  # ₹10 Cr
SMALL_DEAL_SUPPRESS_TYPES = {
    ClauseType.ESCROW, ClauseType.EARNOUT, ClauseType.MATERIAL_ADVERSE_CHANGE,
}


# ---------------------------------------------------------------------------
# Gate 4: Boilerplate Detection
# ---------------------------------------------------------------------------

KNOWN_STANDARD_LANGUAGE: dict[ClauseType, list[str]] = {
    ClauseType.GOVERNING_LAW: [
        r"governed by.*laws of India",
        r"subject to.*jurisdiction.*courts.*(Mumbai|Delhi|Bangalore|Bengaluru)",
    ],
    ClauseType.CONFIDENTIALITY: [
        r"shall not disclose.*confidential information.*without.*prior written consent",
    ],
    ClauseType.DISPUTE_RESOLUTION: [
        r"arbitration.*under.*Arbitration and Conciliation Act.*1996",
        r"seat of arbitration.*(Mumbai|Delhi|Singapore|London)",
    ],
}


# ---------------------------------------------------------------------------
# Risk level numeric values for discounting
# ---------------------------------------------------------------------------

_RISK_ORDER = [
    RiskLevel.INFORMATIONAL,
    RiskLevel.LOW,
    RiskLevel.MEDIUM,
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
]


def _downgrade_risk(current: RiskLevel, levels: int = 1) -> RiskLevel:
    """Downgrade a risk level by the specified number of levels."""
    idx = _RISK_ORDER.index(current)
    new_idx = max(0, idx - levels)
    return _RISK_ORDER[new_idx]


class PracticalRiskFilter:
    """Filters AI findings through 6 validation gates (5 rule-based + 1 AI agent)."""

    def __init__(self, feedback_loop=None, ai_client=None):
        self._feedback = feedback_loop
        self._ai_client = ai_client

    async def validate_findings(
        self,
        findings: list[AIFinding],
        clause: Clause,
        deal_context: DealContext,
    ) -> list[AIFinding]:
        """Run each finding through all 6 validation gates."""
        validated = []
        suppressed = []

        for finding in findings:
            finding = self._apply_materiality(finding, clause, deal_context)
            finding = self._apply_enforceability(finding, clause, deal_context)
            finding = self._apply_proportionality(finding, clause, deal_context)
            finding = self._apply_boilerplate_check(finding, clause)
            if self._feedback:
                finding = self._apply_feedback_calibration(finding)

            # Gate 6: AI Validator (for HIGH+ findings surviving gates 1-5)
            if not finding.suppressed and self._ai_client:
                if finding.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM):
                    finding = await self._ai_validate(finding, clause, deal_context)

            if finding.suppressed:
                suppressed.append(finding)
            else:
                validated.append(finding)

        return validated

    def validate_findings_sync(
        self,
        findings: list[AIFinding],
        clause: Clause,
        deal_context: DealContext,
    ) -> list[AIFinding]:
        """Synchronous version (gates 1-5 only, no AI agent)."""
        validated = []

        for finding in findings:
            finding = self._apply_materiality(finding, clause, deal_context)
            finding = self._apply_enforceability(finding, clause, deal_context)
            finding = self._apply_proportionality(finding, clause, deal_context)
            finding = self._apply_boilerplate_check(finding, clause)
            if self._feedback:
                finding = self._apply_feedback_calibration(finding)

            if not finding.suppressed:
                validated.append(finding)

        return validated

    # --- Gate 1: Financial Materiality ---

    def _apply_materiality(
        self, finding: AIFinding, clause: Clause, context: DealContext
    ) -> AIFinding:
        """Suppress findings below financial materiality threshold."""
        if not context.deal_value or context.deal_value <= 0:
            return finding

        threshold_pct = MATERIALITY_THRESHOLDS.get(
            context.deal_type, MATERIALITY_THRESHOLDS["default"]
        )
        threshold_amount = context.deal_value * threshold_pct / 100

        # Extract monetary values from the finding/clause
        amounts = _extract_amounts(clause.text)
        if amounts:
            max_amount = max(amounts)
            if max_amount < threshold_amount:
                pct = max_amount / context.deal_value * 100
                finding.suppressed = True
                finding.suppression_reason = (
                    f"Below materiality threshold: {pct:.1f}% of deal value "
                    f"(threshold: {threshold_pct}%)"
                )

        return finding

    # --- Gate 2: Indian Court Enforceability ---

    def _apply_enforceability(
        self, finding: AIFinding, clause: Clause, context: DealContext
    ) -> AIFinding:
        """Discount risk for provisions Indian courts don't fully enforce."""
        if finding.suppressed:
            return finding

        if not context.jurisdiction or "india" not in context.jurisdiction.lower():
            return finding

        for discount_id, discount in ENFORCEABILITY_DISCOUNTS.items():
            if clause.clause_type not in discount["clause_types"]:
                continue

            # Check deal type restriction
            if "applies_when_deal_type" in discount:
                if context.deal_type not in discount["applies_when_deal_type"]:
                    continue

            pattern = discount["pattern"]
            if re.search(pattern, clause.text, re.IGNORECASE):
                risk_discount = discount["risk_discount"]
                if risk_discount >= 0.7:
                    finding.suppressed = True
                    finding.suppression_reason = (
                        f"Low enforceability: {discount['reason']}"
                    )
                else:
                    # Downgrade risk level proportionally
                    if risk_discount >= 0.5:
                        finding.risk_level = _downgrade_risk(finding.risk_level, 2)
                    else:
                        finding.risk_level = _downgrade_risk(finding.risk_level, 1)

                finding.enforceability_note = discount["reason"]
                if discount.get("case_law"):
                    finding.enforceability_note += f" [{discount['case_law']}]"
                break

        return finding

    # --- Gate 3: Deal-Context Proportionality ---

    def _apply_proportionality(
        self, finding: AIFinding, clause: Clause, context: DealContext
    ) -> AIFinding:
        """Suppress findings that are disproportionate to the deal."""
        if finding.suppressed:
            return finding

        # Small deals don't need heavy protections
        if context.deal_value and context.deal_value < SMALL_DEAL_THRESHOLD:
            if clause.clause_type in SMALL_DEAL_SUPPRESS_TYPES:
                if finding.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                    finding.suppressed = True
                    finding.suppression_reason = (
                        f"Disproportionate for deal size (< ₹10Cr): "
                        f"{clause.clause_type.value} protections are unnecessary"
                    )

        return finding

    # --- Gate 4: Boilerplate Detection ---

    def _apply_boilerplate_check(
        self, finding: AIFinding, clause: Clause
    ) -> AIFinding:
        """Suppress findings on standard boilerplate language."""
        if finding.suppressed:
            return finding

        patterns = KNOWN_STANDARD_LANGUAGE.get(clause.clause_type)
        if not patterns:
            return finding

        for pattern in patterns:
            if re.search(pattern, clause.text, re.IGNORECASE):
                if finding.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
                    finding.suppressed = True
                    finding.suppression_reason = (
                        "Standard boilerplate language — universally accepted"
                    )
                    break

        return finding

    # --- Gate 5: Feedback-Calibrated Confidence ---

    def _apply_feedback_calibration(self, finding: AIFinding) -> AIFinding:
        """Adjust confidence based on historical human accuracy data."""
        if finding.suppressed or not self._feedback:
            return finding

        stats = self._feedback.accuracy_by_category().get(finding.category)
        if stats and stats.total >= 5:
            if stats.agreement_rate < 0.3:
                # Humans disagree >70% — unreliable pattern
                finding.confidence *= 0.5
                finding.practical_likelihood *= 0.5
                if finding.practical_likelihood < 0.3:
                    finding.suppressed = True
                    finding.suppression_reason = (
                        f"Low historical accuracy: {stats.agreement_rate:.0%} agreement rate "
                        f"for '{finding.category}' pattern"
                    )
            elif stats.agreement_rate > 0.8:
                finding.confidence = min(1.0, finding.confidence * 1.1)

        return finding

    # --- Gate 6: AI Validator Agent ---

    async def _ai_validate(
        self, finding: AIFinding, clause: Clause, context: DealContext
    ) -> AIFinding:
        """Use AI sub-agent to evaluate practical relevance."""
        if not self._ai_client:
            return finding

        from src.engine.ai_agents import AIAgentOrchestrator
        orchestrator = AIAgentOrchestrator(self._ai_client)
        return await orchestrator.validate_finding_practical(finding, clause, context)


def _extract_amounts(text: str) -> list[float]:
    """Extract monetary amounts from text (₹ and $ formats)."""
    amounts = []
    # Match ₹ amounts: ₹50L, ₹100Cr, ₹50,00,000
    for match in re.finditer(r'₹\s*([\d,.]+)\s*(Cr|cr|L|lakh|crore)?', text):
        try:
            val = float(match.group(1).replace(',', ''))
            unit = (match.group(2) or "").lower()
            if unit in ("cr", "crore"):
                val *= 1_00_00_000
            elif unit in ("l", "lakh"):
                val *= 1_00_000
            amounts.append(val)
        except ValueError:
            pass

    # Match $ amounts
    for match in re.finditer(r'\$\s*([\d,.]+)\s*(M|m|B|b)?', text):
        try:
            val = float(match.group(1).replace(',', ''))
            unit = (match.group(2) or "").lower()
            if unit == "m":
                val *= 1_000_000
            elif unit == "b":
                val *= 1_000_000_000
            amounts.append(val)
        except ValueError:
            pass

    return amounts
