"""Advisory generator — synthesizes review findings into client-facing advice.

After all clauses are reviewed, this module generates:
1. Overall deal recommendation (proceed / negotiate / walk_away)
2. Executive summary with decision framework
3. Prioritized key risks with recommendations
4. Negotiation playbook (opening/fallback/walk-away per issue)
5. Financial exposure estimate
6. Cross-clause risk narrative
7. Timeline risks + regulatory approval sequencing
8. Deal-breakers
9. Missing clause detection
10. Perspective-aware language (investor vs promoter)
"""

from __future__ import annotations

import re

from src.models.contract import ClauseType, Contract
from src.models.deal import Deal
from src.models.review import (
    Review,
    RiskLevel,
    ClauseReview,
    CrossClausePattern,
    DealContext,
)
from src.engine.market_benchmarks import detect_missing_clauses, INDIA_MARKET_BENCHMARKS
from src.engine.india_regulatory import (
    get_applicable_regulatory_checks,
    get_approval_sequence,
    get_industry_risks,
)

# Perspective-aware language templates
_PERSPECTIVE_LANGUAGE = {
    "investor": {
        "indemnity_cap_low": "This cap limits your downside recovery to {pct}% of invested capital",
        "non_compete_broad": "Broad non-compete protects your investment in the target company",
        "reserved_matters_narrow": "Insufficient reserved matters may leave you without veto over critical decisions",
        "anti_dilution_weak": "Weak anti-dilution protection exposes your stake to dilution in future down rounds",
        "information_rights_narrow": "Limited information rights reduce your visibility into portfolio company performance",
        "exit_concern": "This provision may limit your exit options and liquidity timeline",
    },
    "promoter": {
        "indemnity_cap_low": "Low indemnity cap limits your post-closing exposure — favorable",
        "non_compete_broad": "Broad non-compete restricts your ability to pursue other business opportunities",
        "reserved_matters_broad": "Expansive reserved matters effectively transfer day-to-day control to the investor",
        "drag_along_low": "Low drag-along threshold allows a minority investor to force a sale against your interest",
        "lock_in_long": "Long lock-in period restricts your ability to monetize your stake",
        "control_concern": "This provision may dilute your operational control over the company",
    },
}


class AdvisoryGenerator:
    """Generates client advisory output from completed reviews."""

    def __init__(self, ai_client=None):
        self._ai_client = ai_client

    async def generate_advisory(
        self,
        deal: Deal,
        contracts: list[Contract],
        reviews: list[Review],
        deal_context: DealContext | None = None,
    ) -> dict:
        """Produce a structured advisory with decision framework."""
        all_clause_reviews = []
        all_cross_patterns = []
        for review in reviews:
            all_clause_reviews.extend(review.clause_reviews)
            all_cross_patterns.extend(review.cross_clause_patterns)

        critical = [
            cr for cr in all_clause_reviews
            if (cr.final_risk_level or cr.ai_risk_level) == RiskLevel.CRITICAL
        ]
        high = [
            cr for cr in all_clause_reviews
            if (cr.final_risk_level or cr.ai_risk_level) == RiskLevel.HIGH
        ]

        # Build clause lookup for context
        clause_lookup = {}
        for contract in contracts:
            for clause in contract.clauses:
                clause_lookup[clause.id] = clause

        key_risks = self._extract_key_risks(critical + high, clause_lookup)
        recommendations = self._build_recommendations(critical + high, clause_lookup)
        negotiation_points = self._build_negotiation_points(all_clause_reviews, clause_lookup)
        deal_breakers = self._identify_deal_breakers(critical, clause_lookup)
        cross_clause_risks = self._build_cross_clause_narrative(all_cross_patterns)
        financial_exposure = self._estimate_financial_exposure(
            all_clause_reviews, clause_lookup, deal_context
        )
        timeline_risks = self._identify_timeline_risks(all_clause_reviews, clause_lookup)
        negotiation_matrix = self._build_negotiation_matrix(
            all_clause_reviews, clause_lookup, deal_context
        )

        # New: Missing clause detection
        clause_types_present = set()
        for contract in contracts:
            for clause in contract.clauses:
                clause_types_present.add(clause.clause_type)
        missing_clauses = self._detect_missing_clauses(
            clause_types_present, deal_context
        )

        # New: Regulatory checks and approval sequence
        regulatory_info = self._build_regulatory_section(deal_context)

        # New: Negotiation playbook with opening/fallback/walk-away
        negotiation_playbook = self._build_negotiation_playbook(
            all_clause_reviews, clause_lookup, deal_context
        )

        # Overall recommendation
        recommendation, rationale = self._determine_recommendation(
            critical, high, deal_breakers, all_clause_reviews
        )

        executive_summary = self._build_executive_summary(
            deal, all_clause_reviews, key_risks, deal_breakers, recommendation,
            deal_context, missing_clauses,
        )

        # Update deal with advisory content
        deal.executive_summary = executive_summary
        deal.key_risks = key_risks
        deal.recommendations = recommendations

        if self._ai_client:
            executive_summary = await self._ai_refine_advisory(
                deal, executive_summary, key_risks, recommendations
            )
            deal.executive_summary = executive_summary

        return {
            "recommendation": recommendation,
            "recommendation_rationale": rationale,
            "executive_summary": executive_summary,
            "financial_exposure": financial_exposure,
            "negotiation_priority_matrix": negotiation_matrix,
            "negotiation_playbook": negotiation_playbook,
            "key_risks": key_risks,
            "cross_clause_risks": cross_clause_risks,
            "timeline_risks": timeline_risks,
            "recommendations": recommendations,
            "negotiation_points": negotiation_points,
            "deal_breakers": deal_breakers,
            "missing_clauses": missing_clauses,
            "regulatory": regulatory_info,
            "risk_distribution": self._risk_distribution(all_clause_reviews),
            "total_clauses_reviewed": len(all_clause_reviews),
            "human_override_rate": self._human_override_rate(all_clause_reviews),
        }

    def _determine_recommendation(
        self,
        critical: list[ClauseReview],
        high: list[ClauseReview],
        deal_breakers: list[str],
        all_reviews: list[ClauseReview],
    ) -> tuple[str, str]:
        """Determine overall deal recommendation: proceed / negotiate / walk_away."""
        if deal_breakers:
            return (
                "walk_away",
                f"{len(deal_breakers)} confirmed deal-breaker(s) identified. "
                "These issues pose unacceptable risk that cannot be adequately mitigated through negotiation.",
            )

        critical_count = len(critical)
        high_count = len(high)

        if critical_count >= 3:
            return (
                "walk_away",
                f"{critical_count} critical risks identified across the contract. "
                "The volume of critical issues suggests fundamental problems with deal structure.",
            )

        if critical_count > 0 or high_count >= 3:
            return (
                "negotiate",
                f"{critical_count} critical and {high_count} high-risk issues require resolution. "
                "The deal is viable but significant terms need renegotiation before proceeding.",
            )

        if high_count > 0:
            return (
                "negotiate",
                f"{high_count} high-risk issue(s) should be addressed in negotiations. "
                "These are manageable and standard for M&A transactions.",
            )

        return (
            "proceed",
            "Contract terms are within market norms. Standard due diligence items addressed.",
        )

    def _extract_key_risks(
        self, high_risk_reviews: list[ClauseReview], clause_lookup: dict
    ) -> list[str]:
        risks = []
        for cr in high_risk_reviews:
            clause = clause_lookup.get(cr.clause_id)
            clause_ref = clause.section_reference if clause else cr.clause_id
            for finding in cr.ai_findings:
                if finding.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                    risks.append(f"[{clause_ref}] {finding.title}: {finding.description}")
        return risks

    def _build_recommendations(
        self, high_risk_reviews: list[ClauseReview], clause_lookup: dict
    ) -> list[str]:
        recs = []
        for cr in high_risk_reviews:
            clause = clause_lookup.get(cr.clause_id)
            clause_ref = clause.section_reference if clause else cr.clause_id
            for finding in cr.ai_findings:
                if finding.suggested_revision:
                    recs.append(
                        f"[{clause_ref}] {finding.title} — Suggested: {finding.suggested_revision}"
                    )
            for annotation in cr.human_annotations:
                if annotation.suggested_language:
                    recs.append(
                        f"[{clause_ref}] Human recommendation: {annotation.suggested_language}"
                    )
        return recs

    def _build_negotiation_points(
        self, all_reviews: list[ClauseReview], clause_lookup: dict
    ) -> list[str]:
        """Identify clauses where suggested revisions exist — these are negotiable."""
        points = []
        for cr in all_reviews:
            clause = clause_lookup.get(cr.clause_id)
            clause_ref = clause.section_reference if clause else cr.clause_id
            revisions = [
                f for f in cr.ai_findings if f.suggested_revision and f.market_comparison
            ]
            for rev in revisions:
                points.append(
                    f"[{clause_ref}] {rev.title}: {rev.market_comparison}"
                )
        return points

    def _identify_deal_breakers(
        self, critical_reviews: list[ClauseReview], clause_lookup: dict
    ) -> list[str]:
        """Critical findings where human also agreed — these are real red flags."""
        breakers = []
        for cr in critical_reviews:
            has_human_agreement = any(
                a.verdict.value == "agree" for a in cr.human_annotations
            )
            if has_human_agreement:
                clause = clause_lookup.get(cr.clause_id)
                clause_ref = clause.section_reference if clause else cr.clause_id
                for finding in cr.ai_findings:
                    if finding.risk_level == RiskLevel.CRITICAL:
                        breakers.append(f"[{clause_ref}] {finding.title}")
        return breakers

    def _build_cross_clause_narrative(
        self, patterns: list[CrossClausePattern]
    ) -> list[str]:
        """Build narrative descriptions of cross-clause risk interactions."""
        narratives = []
        # Sort by interaction score (highest first)
        sorted_patterns = sorted(
            patterns, key=lambda p: p.interaction_score, reverse=True
        )
        for pattern in sorted_patterns:
            severity = "CRITICAL" if pattern.risk_level == RiskLevel.CRITICAL else (
                "HIGH" if pattern.risk_level == RiskLevel.HIGH else "MODERATE"
            )
            narrative = (
                f"[{severity}] {pattern.title}: {pattern.description} "
                f"(interaction score: {pattern.interaction_score:.1f}/1.0)"
            )
            if pattern.recommendation:
                narrative += f" — Recommendation: {pattern.recommendation}"
            narratives.append(narrative)
        return narratives

    def _estimate_financial_exposure(
        self,
        all_reviews: list[ClauseReview],
        clause_lookup: dict,
        context: DealContext | None,
    ) -> dict:
        """Estimate aggregate financial exposure from identified risks."""
        deal_value = context.deal_value if context else None
        breakdown = []
        total = 0.0

        for cr in all_reviews:
            if cr.ai_risk_level not in (RiskLevel.CRITICAL, RiskLevel.HIGH):
                continue
            clause = clause_lookup.get(cr.clause_id)
            if not clause:
                continue

            # Extract dollar amounts from clause text
            amounts = []
            for match in re.finditer(r'\$[\d,]+(?:\.\d+)?', clause.text):
                try:
                    amt = float(match.group().replace('$', '').replace(',', ''))
                    amounts.append(amt)
                except ValueError:
                    pass

            if amounts:
                max_amount = max(amounts)
                breakdown.append({
                    "clause": clause.section_reference,
                    "risk_level": cr.ai_risk_level.value,
                    "amount": max_amount,
                    "description": cr.ai_summary[:100] if cr.ai_summary else "",
                })
                total += max_amount

        result: dict = {
            "estimated_total": total,
            "breakdown": breakdown,
        }
        if deal_value and deal_value > 0:
            result["exposure_percentage"] = round(total / deal_value * 100, 1)

        return result

    def _identify_timeline_risks(
        self, all_reviews: list[ClauseReview], clause_lookup: dict
    ) -> list[str]:
        """Identify conditions or requirements that could delay closing."""
        timeline_keywords = [
            "regulatory approval", "antitrust", "waiting period",
            "government", "consent", "third party", "shareholder",
            "filing", "days", "months",
        ]
        risks = []
        for cr in all_reviews:
            clause = clause_lookup.get(cr.clause_id)
            if not clause:
                continue
            text_lower = clause.text.lower()
            for keyword in timeline_keywords:
                if keyword in text_lower:
                    clause_ref = clause.section_reference
                    risks.append(
                        f"[{clause_ref}] Potential timeline risk: "
                        f"'{keyword}' referenced in {clause.clause_type.value}"
                    )
                    break  # one per clause
        return risks

    def _build_negotiation_matrix(
        self,
        all_reviews: list[ClauseReview],
        clause_lookup: dict,
        context: DealContext | None,
    ) -> list[dict]:
        """Build a prioritized negotiation matrix.

        Each item has: issue, priority (must_have/nice_to_have/concession),
        leverage (strong/moderate/weak), and rationale.
        """
        matrix = []
        for cr in all_reviews:
            clause = clause_lookup.get(cr.clause_id)
            if not clause:
                continue

            for finding in cr.ai_findings:
                if not finding.suggested_revision:
                    continue

                # Determine priority
                if finding.risk_level == RiskLevel.CRITICAL:
                    priority = "must_have"
                    leverage = "strong"
                elif finding.risk_level == RiskLevel.HIGH:
                    priority = "must_have"
                    leverage = "moderate"
                elif finding.risk_level == RiskLevel.MEDIUM:
                    priority = "nice_to_have"
                    leverage = "moderate"
                else:
                    priority = "concession"
                    leverage = "weak"

                # Adjust leverage based on market comparison
                if finding.market_comparison and "below market" in finding.market_comparison.lower():
                    leverage = "strong"

                matrix.append({
                    "issue": f"[{clause.section_reference}] {finding.title}",
                    "priority": priority,
                    "leverage": leverage,
                    "rationale": finding.market_comparison or finding.description[:100],
                    "suggested_language": finding.suggested_revision[:200] if finding.suggested_revision else "",
                })

        # Sort: must_have first, then nice_to_have, then concession
        priority_order = {"must_have": 0, "nice_to_have": 1, "concession": 2}
        matrix.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return matrix

    def _build_executive_summary(
        self,
        deal: Deal,
        all_reviews: list[ClauseReview],
        key_risks: list[str],
        deal_breakers: list[str],
        recommendation: str,
        deal_context: DealContext | None = None,
        missing_clauses: list[dict] | None = None,
    ) -> str:
        total = len(all_reviews)
        critical_count = sum(
            1 for cr in all_reviews if cr.ai_risk_level == RiskLevel.CRITICAL
        )
        high_count = sum(
            1 for cr in all_reviews if cr.ai_risk_level == RiskLevel.HIGH
        )

        rec_label = {
            "proceed": "PROCEED",
            "negotiate": "PROCEED WITH NEGOTIATIONS",
            "walk_away": "WALK AWAY / SIGNIFICANT RENEGOTIATION REQUIRED",
        }

        summary = (
            f"M&A Contract Review — {deal.name}\n"
            f"Client: {deal.client_name}\n"
            f"Recommendation: {rec_label.get(recommendation, recommendation.upper())}\n\n"
            f"Reviewed {total} clauses across {len(deal.contract_ids) or 1} contract(s).\n"
            f"Identified {critical_count} critical and {high_count} high-risk findings.\n"
        )

        if deal_breakers:
            summary += f"\nDeal-Breakers ({len(deal_breakers)}):\n"
            for db in deal_breakers:
                summary += f"  • {db}\n"

        if key_risks:
            summary += f"\nTop Risks ({min(5, len(key_risks))}):\n"
            for risk in key_risks[:5]:
                summary += f"  • {risk}\n"

        # Add perspective context
        if deal_context and deal_context.client_side:
            perspective = deal_context.client_side
            summary += f"\nPerspective: {perspective.upper()}\n"
            if perspective == "investor":
                summary += "Focus: downside protection, information rights, exit optionality, anti-dilution.\n"
            elif perspective == "promoter":
                summary += "Focus: operational control preservation, lock-in flexibility, drag-along protection.\n"

        # Add missing clauses warning
        if missing_clauses:
            critical_missing = [m for m in missing_clauses if m.get("severity") == "must_have"]
            if critical_missing:
                summary += f"\nMISSING CLAUSES ({len(critical_missing)} critical gaps):\n"
                for m in critical_missing:
                    summary += f"  • {m['clause_type']}: {m['rationale']}\n"

        return summary

    def _detect_missing_clauses(
        self,
        clause_types_present: set[ClauseType],
        deal_context: DealContext | None,
    ) -> list[dict]:
        """Detect clauses that should be present but are missing, based on deal type."""
        if not deal_context or not deal_context.deal_type:
            return []

        missing = detect_missing_clauses(clause_types_present, deal_context.deal_type)
        return missing

    def _build_regulatory_section(
        self, deal_context: DealContext | None
    ) -> dict:
        """Build regulatory checks and approval sequence for the advisory."""
        if not deal_context:
            return {"checks": [], "approval_sequence": [], "industry_risks": []}

        # Gather regulatory checks across all relevant clause types
        all_checks = []
        seen = set()
        for ct in ClauseType:
            for check in get_applicable_regulatory_checks(ct, deal_context):
                check_id = check.get("check_id", check.get("title", ""))
                if check_id not in seen:
                    seen.add(check_id)
                    all_checks.append(check)

        approval_seq = get_approval_sequence(deal_context.deal_type)
        raw_industry = get_industry_risks(deal_context.industry)

        # Normalize industry risks into a list of dicts for consistent output
        industry_risks = []
        if raw_industry:
            regulators = raw_industry.get("regulators", [])
            for risk_desc in raw_industry.get("key_risks", []):
                industry_risks.append({
                    "regulator": ", ".join(regulators),
                    "description": risk_desc,
                })

        return {
            "checks": all_checks,
            "approval_sequence": approval_seq,
            "industry_risks": industry_risks,
        }

    def _build_negotiation_playbook(
        self,
        all_reviews: list[ClauseReview],
        clause_lookup: dict,
        deal_context: DealContext | None,
    ) -> list[dict]:
        """Build negotiation playbook with opening/fallback/walk-away per issue.

        Each item includes strategic positions and potential trade-offs.
        """
        playbook = []
        context = deal_context or DealContext()
        perspective = context.client_side or "buyer"

        for cr in all_reviews:
            clause = clause_lookup.get(cr.clause_id)
            if not clause:
                continue

            for finding in cr.ai_findings:
                if finding.risk_level not in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM):
                    continue
                if not finding.suggested_revision:
                    continue

                # Determine positions based on risk level
                item: dict = {
                    "issue": f"[{clause.section_reference}] {finding.title}",
                    "clause_type": clause.clause_type.value,
                    "risk_level": finding.risk_level.value,
                    "priority": "must_have" if finding.risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH) else "nice_to_have",
                    "opening_position": finding.suggested_revision,
                    "fallback_position": "",
                    "walk_away_point": "",
                    "market_context": finding.market_comparison or "",
                    "concession_trade": "",
                }

                # Generate fallback and walk-away based on clause type and benchmarks
                benchmark = INDIA_MARKET_BENCHMARKS.get(clause.clause_type.value)
                if benchmark:
                    item["fallback_position"] = (
                        f"Accept market median: {benchmark.get('metric', '')} at "
                        f"{benchmark.get('median', 'N/A')}"
                    )
                    item["walk_away_point"] = (
                        f"Below p25: {benchmark.get('metric', '')} at "
                        f"{benchmark.get('p25', 'N/A')}"
                    )

                # Generate trade suggestions based on perspective
                item["concession_trade"] = self._suggest_trade(
                    clause.clause_type, finding.risk_level, perspective
                )

                # Add perspective-specific framing
                perspective_note = self._get_perspective_note(
                    clause.clause_type, perspective, finding
                )
                if perspective_note:
                    item["perspective_note"] = perspective_note

                playbook.append(item)

        # Sort by priority
        priority_order = {"must_have": 0, "nice_to_have": 1, "concession": 2}
        playbook.sort(key=lambda x: priority_order.get(x["priority"], 3))

        return playbook

    def _suggest_trade(
        self, clause_type: ClauseType, risk_level: RiskLevel, perspective: str
    ) -> str:
        """Suggest what to trade/concede in exchange for this position."""
        # Trade suggestion matrix based on clause type relationships
        trade_map = {
            ClauseType.INDEMNIFICATION: "Concede on non-compete duration in exchange for higher indemnity cap",
            ClauseType.NON_COMPETE: "Concede non-compete scope in exchange for stronger indemnification",
            ClauseType.RESERVED_MATTERS: "Bundle with information rights — concede reporting frequency for reserved matter control",
            ClauseType.ANTI_DILUTION: "Trade anti-dilution formula for more favorable lock-in terms",
            ClauseType.TAG_ALONG_DRAG_ALONG: "Link drag-along threshold to minimum pricing guarantee",
            ClauseType.LOCK_IN: "Concede lock-in duration for IPO/exit event carve-outs",
            ClauseType.EARNOUT: "Trade earnout metric precision for longer measurement period",
            ClauseType.PURCHASE_PRICE: "Link price adjustment to escrow mechanism",
        }
        return trade_map.get(clause_type, "")

    def _get_perspective_note(
        self, clause_type: ClauseType, perspective: str, finding
    ) -> str:
        """Get perspective-specific framing for a finding."""
        templates = _PERSPECTIVE_LANGUAGE.get(perspective, {})

        # Map clause type + finding to the appropriate template key
        key_map = {
            ClauseType.INDEMNIFICATION: "indemnity_cap_low",
            ClauseType.NON_COMPETE: "non_compete_broad",
            ClauseType.RESERVED_MATTERS: "reserved_matters_broad" if perspective == "promoter" else "reserved_matters_narrow",
            ClauseType.ANTI_DILUTION: "anti_dilution_weak",
            ClauseType.INFORMATION_RIGHTS: "information_rights_narrow",
            ClauseType.TAG_ALONG_DRAG_ALONG: "drag_along_low" if perspective == "promoter" else "exit_concern",
            ClauseType.LOCK_IN: "lock_in_long" if perspective == "promoter" else "exit_concern",
        }

        template_key = key_map.get(clause_type)
        if template_key and template_key in templates:
            return templates[template_key]
        return ""

    def _risk_distribution(self, reviews: list[ClauseReview]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for cr in reviews:
            level = (cr.final_risk_level or cr.ai_risk_level).value
            dist[level] = dist.get(level, 0) + 1
        return dist

    def _human_override_rate(self, reviews: list[ClauseReview]) -> float:
        """What percentage of AI findings did humans disagree with?"""
        total_verdicts = 0
        disagreements = 0
        for cr in reviews:
            for a in cr.human_annotations:
                total_verdicts += 1
                if a.verdict.value == "disagree":
                    disagreements += 1
        if total_verdicts == 0:
            return 0.0
        return round(disagreements / total_verdicts, 2)

    async def _ai_refine_advisory(
        self, deal: Deal, summary: str, risks: list[str], recs: list[str]
    ) -> str:
        """Use Claude to polish the executive summary into client-ready language."""
        prompt = f"""Refine this M&A advisory executive summary for a client.
Make it professional, clear, and actionable. Keep the same facts but improve the language.

Draft summary:
{summary}

Key risks: {risks[:10]}
Recommendations: {recs[:10]}

Return only the refined summary text."""

        response = await self._ai_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
