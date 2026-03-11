"""Negotiation round tracking models for multi-round M&A negotiations."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NegotiationPosition(BaseModel):
    """A position we took in a negotiation round."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    clause_type: str
    section_reference: str = ""
    issue: str
    our_language: str = ""  # what we proposed
    priority: str = "nice_to_have"  # must_have, nice_to_have, concession
    rationale: str = ""


class CounterpartyResponse(BaseModel):
    """How the counterparty responded to one of our positions."""

    position_id: str  # links to NegotiationPosition
    response_type: str  # "accepted", "rejected", "modified", "new_issue"
    their_language: str = ""  # their counter-proposal (if modified)
    our_assessment: str = ""  # AI analysis of their response


class CounterpartyPattern(BaseModel):
    """AI-detected patterns in counterparty's negotiation behavior."""

    flexible_areas: list[str] = Field(default_factory=list)
    firm_areas: list[str] = Field(default_factory=list)
    emerging_concerns: list[str] = Field(default_factory=list)
    negotiation_style: str = "unknown"  # collaborative, positional, mixed
    leverage_assessment: str = ""


class StrategyAdjustment(BaseModel):
    """AI-recommended strategy changes based on counterparty pattern."""

    clause_type: str
    current_position: str = ""
    recommended_adjustment: str = ""
    rationale: str = ""
    trade_suggestion: str = ""  # e.g. "Bundle with reserved matters"


class NegotiationRound(BaseModel):
    """Tracks a single round of contract exchange and review."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    deal_id: str
    round_number: int = 1
    contract_id: str = ""  # this round's contract version
    previous_contract_id: str | None = None

    our_positions: list[NegotiationPosition] = Field(default_factory=list)
    counterparty_responses: list[CounterpartyResponse] = Field(default_factory=list)
    counterparty_pattern: CounterpartyPattern = Field(
        default_factory=CounterpartyPattern
    )
    strategy_adjustments: list[StrategyAdjustment] = Field(default_factory=list)

    # Time tracking per reviewer
    time_budget_used: dict[str, float] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    @property
    def acceptance_rate(self) -> float:
        """What fraction of our positions did the counterparty accept?"""
        if not self.counterparty_responses:
            return 0.0
        accepted = sum(
            1 for r in self.counterparty_responses if r.response_type == "accepted"
        )
        return accepted / len(self.counterparty_responses)

    @property
    def positions_by_response(self) -> dict[str, int]:
        """Count of positions by counterparty response type."""
        counts: dict[str, int] = {}
        for r in self.counterparty_responses:
            counts[r.response_type] = counts.get(r.response_type, 0) + 1
        return counts
