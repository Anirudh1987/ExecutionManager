"""Advisory generator — synthesizes review findings into client-facing advice.

After all clauses are reviewed, this module generates:
1. Overall deal recommendation (proceed / negotiate / walk_away)
2. Executive summary with decision framework
3. Prioritized key risks with recommendations
4. Negotiation priority matrix
5. Financial exposure estimate
6. Cross-clause risk narrative
7. Timeline risks
8. Deal-breakers
"""

from __future__ import annotations

import re

from src.models.contract import Contract
from src.models.deal import Deal
from src.models.review import (
    Review,
    RiskLevel,
    ClauseReview,
    CrossClausePattern,
    DealContext,
)


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

        # Overall recommendation
        recommendation, rationale = self._determine_recommendation(
            critical, high, deal_breakers, all_clause_reviews
        )

        executive_summary = self._build_executive_summary(
            deal, all_clause_reviews, key_risks, deal_breakers, recommendation
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
            "key_risks": key_risks,
            "cross_clause_risks": cross_clause_risks,
            "timeline_risks": timeline_risks,
            "recommendations": recommendations,
            "negotiation_points": negotiation_points,
            "deal_breakers": deal_breakers,
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

        return summary

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
