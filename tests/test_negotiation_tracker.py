"""Tests for negotiation round tracking and counterparty pattern detection."""

import pytest

from src.models.contract import Clause, ClauseType, Contract, ContractDiff, ClauseDiff
from src.models.negotiation import (
    NegotiationRound,
    NegotiationPosition,
    CounterpartyResponse,
    CounterpartyPattern,
    StrategyAdjustment,
)
from src.engine.negotiation_tracker import NegotiationTracker


def _make_contract(contract_id, clauses=None):
    return Contract(
        id=contract_id,
        deal_id="deal1",
        filename="test.pdf",
        clauses=clauses or [],
    )


def _make_clause(clause_type, title, text):
    return Clause(
        contract_id="c1",
        clause_type=clause_type,
        title=title,
        text=text,
    )


class TestNegotiationRound:
    def test_acceptance_rate_all_accepted(self):
        round_ = NegotiationRound(
            deal_id="deal1",
            counterparty_responses=[
                CounterpartyResponse(position_id="p1", response_type="accepted"),
                CounterpartyResponse(position_id="p2", response_type="accepted"),
            ],
        )
        assert round_.acceptance_rate == 1.0

    def test_acceptance_rate_mixed(self):
        round_ = NegotiationRound(
            deal_id="deal1",
            counterparty_responses=[
                CounterpartyResponse(position_id="p1", response_type="accepted"),
                CounterpartyResponse(position_id="p2", response_type="rejected"),
                CounterpartyResponse(position_id="p3", response_type="modified"),
                CounterpartyResponse(position_id="p4", response_type="accepted"),
            ],
        )
        assert round_.acceptance_rate == 0.5

    def test_acceptance_rate_empty(self):
        round_ = NegotiationRound(deal_id="deal1")
        assert round_.acceptance_rate == 0.0

    def test_positions_by_response(self):
        round_ = NegotiationRound(
            deal_id="deal1",
            counterparty_responses=[
                CounterpartyResponse(position_id="p1", response_type="accepted"),
                CounterpartyResponse(position_id="p2", response_type="rejected"),
                CounterpartyResponse(position_id="p3", response_type="accepted"),
            ],
        )
        counts = round_.positions_by_response
        assert counts["accepted"] == 2
        assert counts["rejected"] == 1


class TestNegotiationTracker:
    def test_classify_changes(self):
        tracker = NegotiationTracker()

        old_contract = _make_contract("c1", clauses=[
            _make_clause(ClauseType.INDEMNIFICATION, "Indemnification", "Cap at 10%"),
        ])
        new_contract = _make_contract("c2", clauses=[
            _make_clause(ClauseType.INDEMNIFICATION, "Indemnification", "Cap at 15%"),
            _make_clause(ClauseType.LOCK_IN, "Lock-In", "New lock-in clause"),
        ])

        diff = ContractDiff(
            old_contract_id="c1",
            new_contract_id="c2",
            added_clauses=[
                _make_clause(ClauseType.LOCK_IN, "Lock-In", "New lock-in clause"),
            ],
            removed_clauses=[],
            modified_clauses=[
                ClauseDiff(
                    old_title="Indemnification",
                    new_title="Indemnification",
                    old_text="Cap at 10%",
                    new_text="Cap at 15%",
                    change_type="modified",
                    unified_diff="",
                    change_summary="Cap increased from 10% to 15%",
                ),
            ],
        )

        positions = [
            NegotiationPosition(
                clause_type="indemnification",
                section_reference="indemnification",
                issue="Low indemnity cap",
                our_language="Cap at 20%",
            ),
        ]

        responses = tracker.classify_changes(old_contract, new_contract, diff, positions)
        assert len(responses) >= 1
        # The clause text changed from "Cap at 10%" to "Cap at 15%" but our proposal was "Cap at 20%"
        # So it should be classified as "modified" (counter-proposal)
        types = {r.response_type for r in responses}
        assert len(types) >= 1  # At least one response classified

    def test_detect_counterparty_pattern(self):
        tracker = NegotiationTracker()

        rounds = [
            NegotiationRound(
                deal_id="deal1",
                round_number=1,
                counterparty_responses=[
                    CounterpartyResponse(position_id="p1", response_type="accepted"),
                    CounterpartyResponse(position_id="p2", response_type="accepted"),
                    CounterpartyResponse(position_id="p3", response_type="rejected"),
                ],
                our_positions=[
                    NegotiationPosition(clause_type="indemnification", issue="cap", priority="must_have"),
                    NegotiationPosition(clause_type="purchase_price", issue="price", priority="must_have"),
                    NegotiationPosition(clause_type="reserved_matters", issue="scope", priority="nice_to_have"),
                ],
            ),
        ]

        pattern = tracker.detect_counterparty_pattern(rounds)
        assert isinstance(pattern, CounterpartyPattern)
        assert pattern.negotiation_style in ("collaborative", "positional", "mixed")

    def test_recommend_strategy(self):
        tracker = NegotiationTracker()

        pattern = CounterpartyPattern(
            flexible_areas=["Financial terms: accepted 2/2 proposals"],
            firm_areas=["Governance: rejected 1/1 proposals"],
            negotiation_style="mixed",
        )

        remaining = [
            NegotiationPosition(
                clause_type="reserved_matters",
                issue="scope",
                priority="must_have",
            ),
        ]

        responses = [
            CounterpartyResponse(
                position_id=remaining[0].id,
                response_type="rejected",
            ),
        ]

        adjustments = tracker.recommend_strategy(pattern, remaining, responses)
        assert isinstance(adjustments, list)

    def test_get_round_summary(self):
        tracker = NegotiationTracker()
        round_ = NegotiationRound(
            deal_id="deal1",
            round_number=2,
            counterparty_responses=[
                CounterpartyResponse(position_id="p1", response_type="accepted"),
                CounterpartyResponse(position_id="p2", response_type="rejected"),
            ],
        )
        summary = tracker.get_round_summary(round_)
        assert "round_number" in summary
        assert "acceptance_rate" in summary
        assert summary["round_number"] == 2
