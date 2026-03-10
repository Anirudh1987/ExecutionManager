"""Advisory generator — synthesizes review findings into client-facing advice.

After all clauses are reviewed, this module generates:
1. Executive summary of the deal's risk profile
2. Prioritized list of key risks with recommendations
3. Suggested negotiation points
4. Red flags that could be deal-breakers
"""

from __future__ import annotations

from src.models.contract import Contract
from src.models.deal import Deal
from src.models.review import Review, RiskLevel, ClauseReview


class AdvisoryGenerator:
    """Generates client advisory output from completed reviews."""

    def __init__(self, ai_client=None):
        self._ai_client = ai_client

    async def generate_advisory(
        self,
        deal: Deal,
        contracts: list[Contract],
        reviews: list[Review],
    ) -> dict:
        """Produce a structured advisory for the client."""
        all_clause_reviews = []
        for review in reviews:
            all_clause_reviews.extend(review.clause_reviews)

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

        executive_summary = self._build_executive_summary(
            deal, all_clause_reviews, key_risks, deal_breakers
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
            "executive_summary": executive_summary,
            "key_risks": key_risks,
            "recommendations": recommendations,
            "negotiation_points": negotiation_points,
            "deal_breakers": deal_breakers,
            "risk_distribution": self._risk_distribution(all_clause_reviews),
            "total_clauses_reviewed": len(all_clause_reviews),
            "human_override_rate": self._human_override_rate(all_clause_reviews),
        }

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

    def _build_executive_summary(
        self,
        deal: Deal,
        all_reviews: list[ClauseReview],
        key_risks: list[str],
        deal_breakers: list[str],
    ) -> str:
        total = len(all_reviews)
        critical_count = sum(
            1 for cr in all_reviews if cr.ai_risk_level == RiskLevel.CRITICAL
        )
        high_count = sum(
            1 for cr in all_reviews if cr.ai_risk_level == RiskLevel.HIGH
        )

        summary = (
            f"M&A Contract Review — {deal.name}\n"
            f"Client: {deal.client_name}\n\n"
            f"Reviewed {total} clauses across {len(deal.contract_ids)} contract(s).\n"
            f"Identified {critical_count} critical and {high_count} high-risk findings.\n"
        )

        if deal_breakers:
            summary += f"\nPotential deal-breakers ({len(deal_breakers)}):\n"
            for db in deal_breakers:
                summary += f"  • {db}\n"

        if key_risks:
            summary += f"\nTop risks requiring attention ({len(key_risks)}):\n"
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
