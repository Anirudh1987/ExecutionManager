"""AI sub-agent orchestrator — specialized Claude agents for contract review.

Deploys specialized AI agents for tasks that need reasoning beyond pattern matching:
- Clause Analyzer: deep contextual risk analysis
- False Positive Validator: evaluates practical likelihood of each finding
- Negotiation Strategist: generates round-aware playbook
- Redline Drafter: drafts suggested language with legal reasoning
- Advisory Writer: synthesizes client-ready executive summary

Each agent uses the existing ai_client (Anthropic Claude API). The rule-based
engine runs first as a fast baseline, then AI agents refine and validate.
"""

from __future__ import annotations

import json
import re

from src.models.contract import Clause
from src.models.review import AIFinding, DealContext, RiskLevel


class AIAgentOrchestrator:
    """Manages specialized AI sub-agents for contract review tasks."""

    def __init__(self, ai_client=None):
        self._client = ai_client

    @property
    def available(self) -> bool:
        return self._client is not None

    async def validate_finding_practical(
        self,
        finding: AIFinding,
        clause: Clause,
        deal_context: DealContext,
    ) -> AIFinding:
        """AI agent that evaluates whether a finding is a real practical risk.

        This is Gate 6 of the false positive filter — catches nuanced false
        positives that rule-based gates miss.
        """
        if not self._client:
            return finding

        perspective = deal_context.client_side or "investor"
        industry = deal_context.industry or "general"
        value_str = f"₹{deal_context.deal_value:,.0f}" if deal_context.deal_value else "undisclosed"

        prompt = f"""You are a senior Indian M&A lawyer with 20 years experience.
A junior AI flagged this risk. Your job: Is this a REAL practical risk, or noise?

Deal: {perspective} perspective in {industry} sector, {value_str} deal value, {deal_context.jurisdiction or 'India'} jurisdiction.
Deal type: {deal_context.deal_type or 'unspecified'}
Clause type: {clause.clause_type.value}
Clause text (excerpt): {clause.text[:800]}

AI Finding: {finding.title} — {finding.description}
Risk level: {finding.risk_level.value}

Consider:
1. Would this risk actually materialize in practice for this specific deal?
2. Is this enforceable under Indian law?
3. Is this proportionate to the deal size?
4. Is this standard market practice that doesn't need flagging?
5. Would a senior partner spend time on this, or dismiss it?

Reply ONLY with JSON (no markdown):
{{"keep": true, "practical_likelihood": 0.8, "reasoning": "one sentence why", "senior_partner_would_flag": true}}"""

        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Parse JSON from response
            result = _parse_json_response(text)

            finding.practical_likelihood = result.get("practical_likelihood", 1.0)
            finding.ai_validation_reasoning = result.get("reasoning", "")

            if not result.get("keep", True):
                finding.suppressed = True
                finding.suppression_reason = (
                    f"AI validator: {result.get('reasoning', 'Not a practical risk')}"
                )
        except Exception:
            # If AI agent fails, don't suppress — let the finding through
            pass

        return finding

    async def draft_suggested_language(
        self,
        clause: Clause,
        finding: AIFinding,
        deal_context: DealContext,
        market_benchmark: str = "",
    ) -> str:
        """AI agent that drafts specific contract language revision."""
        if not self._client:
            return finding.suggested_revision

        perspective = deal_context.client_side or "investor"

        prompt = f"""You are a senior Indian M&A lawyer drafting contract language.

Perspective: Representing the {perspective}
Clause: {clause.clause_type.value} — {clause.title}
Current text: {clause.text[:600]}

Issue: {finding.title} — {finding.description}
Market context: {market_benchmark or finding.market_comparison or 'N/A'}

Draft a specific, precise revision that:
1. Addresses the identified risk from the {perspective}'s perspective
2. Uses standard Indian M&A drafting conventions
3. Is ready to insert into the contract
4. Cites market practice where applicable

Reply with ONLY the suggested contract language (no explanation)."""

        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            return finding.suggested_revision

    async def generate_negotiation_strategy(
        self,
        findings: list[dict],
        deal_context: DealContext,
        previous_rounds: list[dict] | None = None,
    ) -> dict:
        """AI agent that creates round-aware negotiation playbook."""
        if not self._client:
            return {}

        rounds_context = ""
        if previous_rounds:
            rounds_context = f"\nPrevious negotiation rounds: {json.dumps(previous_rounds[:3], default=str)}"

        findings_summary = json.dumps(findings[:15], default=str)

        prompt = f"""You are a senior Indian M&A negotiation strategist.

Deal: {deal_context.client_side} in {deal_context.industry}, deal value {deal_context.deal_value}
Round: {deal_context.negotiation_round}
{rounds_context}

Key findings to negotiate: {findings_summary}

For each issue, provide:
1. Opening position (ambitious but credible)
2. Fallback position (acceptable minimum)
3. Walk-away point (deal-breaker threshold)
4. Likely counterparty response
5. Concession trades (what to give up in exchange)

Group related issues into negotiation bundles for package deals.

Reply with JSON array of negotiation items."""

        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return _parse_json_response(response.content[0].text.strip())
        except Exception:
            return {}

    async def write_executive_summary(
        self,
        deal_name: str,
        client_name: str,
        deal_context: DealContext,
        risk_summary: str,
        missing_clauses: list[str],
        regulatory_issues: list[str],
    ) -> str:
        """AI agent that writes client-ready advisory language."""
        if not self._client:
            return ""

        prompt = f"""Write a professional executive summary for an M&A advisory report.

Deal: {deal_name}
Client: {client_name}
Perspective: {deal_context.client_side}
Jurisdiction: {deal_context.jurisdiction}
Industry: {deal_context.industry}

Risk summary: {risk_summary}
Missing clauses: {', '.join(missing_clauses) if missing_clauses else 'None'}
Regulatory issues: {', '.join(regulatory_issues) if regulatory_issues else 'Standard compliance'}

Write 3-4 paragraphs in professional law firm language. Be direct and actionable.
Focus on what the client needs to know and do."""

        try:
            response = await self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception:
            return ""


def _parse_json_response(text: str) -> dict:
    """Parse JSON from an AI response, handling markdown fences."""
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}
