"""Multi-round negotiation tracker — adjusts strategy based on counterparty patterns.

After each negotiation round, compares the new contract version against the previous
one, classifies what the counterparty accepted/rejected/modified, detects behavioral
patterns, and recommends strategy adjustments for the next round.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from src.models.contract import Contract, Clause, ClauseType
from src.models.negotiation import (
    CounterpartyPattern,
    CounterpartyResponse,
    NegotiationPosition,
    NegotiationRound,
    StrategyAdjustment,
)
from src.models.review import Review, HumanAnnotation
from src.engine.version_diff import compare_contracts


class NegotiationTracker:
    """Tracks multi-round negotiations and adjusts strategy."""

    def start_round(
        self,
        deal_id: str,
        new_contract: Contract,
        previous_contract: Contract,
        previous_review: Review | None = None,
        previous_round: NegotiationRound | None = None,
    ) -> NegotiationRound:
        """Begin a new negotiation round by diffing against the previous version."""
        round_number = (previous_round.round_number + 1) if previous_round else 2

        round_ = NegotiationRound(
            deal_id=deal_id,
            round_number=round_number,
            contract_id=new_contract.id,
            previous_contract_id=previous_contract.id,
        )

        # Collect our previous positions from human annotations
        our_positions = self._extract_our_positions(
            previous_contract, previous_review
        )
        round_.our_positions = our_positions

        # Diff the contracts
        diff = compare_contracts(previous_contract, new_contract)

        # Classify counterparty responses
        round_.counterparty_responses = self.classify_changes(
            previous_contract, new_contract, diff, our_positions
        )

        # Detect counterparty pattern (across all rounds)
        all_rounds = [round_]
        if previous_round:
            all_rounds = [previous_round, round_]
        round_.counterparty_pattern = self.detect_counterparty_pattern(all_rounds)

        # Generate strategy adjustments
        round_.strategy_adjustments = self.recommend_strategy(
            round_.counterparty_pattern, our_positions, round_.counterparty_responses
        )

        return round_

    def _extract_our_positions(
        self,
        contract: Contract,
        review: Review | None,
    ) -> list[NegotiationPosition]:
        """Extract our negotiation positions from the previous review's human annotations."""
        positions = []
        if not review:
            return positions

        for cr in review.clause_reviews:
            for annotation in cr.human_annotations:
                if annotation.suggested_language:
                    clause = next(
                        (c for c in contract.clauses if c.id == cr.clause_id), None
                    )
                    # Determine priority from risk level
                    risk = cr.final_risk_level or cr.ai_risk_level
                    priority = "must_have" if risk.value in ("critical", "high") else "nice_to_have"

                    positions.append(NegotiationPosition(
                        clause_type=clause.clause_type.value if clause else "other",
                        section_reference=clause.section_reference if clause else "",
                        issue=cr.ai_summary or "Reviewer suggested revision",
                        our_language=annotation.suggested_language,
                        priority=priority,
                        rationale=annotation.comment or "",
                    ))

        return positions

    def classify_changes(
        self,
        old_contract: Contract,
        new_contract: Contract,
        diff,
        our_positions: list[NegotiationPosition],
    ) -> list[CounterpartyResponse]:
        """Classify each change as accepted/rejected/modified/new_issue."""
        responses = []

        old_by_ref = {_clause_key(c): c for c in old_contract.clauses}
        new_by_ref = {_clause_key(c): c for c in new_contract.clauses}

        for position in our_positions:
            key = position.section_reference.strip().lower() or position.issue[:50].strip().lower()

            # Find matching clause in new contract
            matching_new = None
            for ref, clause in new_by_ref.items():
                if key and key in ref:
                    matching_new = clause
                    break

            matching_old = None
            for ref, clause in old_by_ref.items():
                if key and key in ref:
                    matching_old = clause
                    break

            if matching_new and matching_old:
                if matching_new.text.strip() == matching_old.text.strip():
                    # Unchanged — counterparty rejected our proposal
                    responses.append(CounterpartyResponse(
                        position_id=position.id,
                        response_type="rejected",
                        their_language=matching_new.text[:200],
                        our_assessment="Counterparty did not accept this change.",
                    ))
                elif _text_similarity(matching_new.text, position.our_language) > 0.8:
                    # Very similar to what we proposed — accepted
                    responses.append(CounterpartyResponse(
                        position_id=position.id,
                        response_type="accepted",
                        their_language=matching_new.text[:200],
                        our_assessment="Counterparty accepted this change.",
                    ))
                else:
                    # Changed but different from our proposal — counter-proposal
                    responses.append(CounterpartyResponse(
                        position_id=position.id,
                        response_type="modified",
                        their_language=matching_new.text[:200],
                        our_assessment="Counterparty counter-proposed with different language.",
                    ))
            else:
                # Can't match — treat as rejected
                responses.append(CounterpartyResponse(
                    position_id=position.id,
                    response_type="rejected",
                    their_language="",
                    our_assessment="Could not find matching clause in new version.",
                ))

        # Check for new clauses added by counterparty
        old_keys = set(_clause_key(c) for c in old_contract.clauses)
        for clause in new_contract.clauses:
            if _clause_key(clause) not in old_keys:
                responses.append(CounterpartyResponse(
                    position_id="",
                    response_type="new_issue",
                    their_language=clause.text[:200],
                    our_assessment=f"Counterparty added new clause: {clause.title}",
                ))

        return responses

    def detect_counterparty_pattern(
        self,
        rounds: list[NegotiationRound],
    ) -> CounterpartyPattern:
        """Analyze patterns across all negotiation rounds."""
        # Group responses by clause type category
        financial_types = {"purchase_price", "earnout", "escrow", "indemnification", "tax"}
        governance_types = {"reserved_matters", "information_rights", "affirmative_covenants", "negative_covenants"}
        exit_types = {"tag_along_drag_along", "rofr_rofo", "lock_in", "termination"}

        category_stats: dict[str, dict[str, int]] = {
            "financial": {"total": 0, "accepted": 0},
            "governance": {"total": 0, "accepted": 0},
            "exit_rights": {"total": 0, "accepted": 0},
            "other": {"total": 0, "accepted": 0},
        }

        for round_ in rounds:
            for resp in round_.counterparty_responses:
                # Find the position to get clause type
                pos = next(
                    (p for p in round_.our_positions if p.id == resp.position_id), None
                )
                ct = pos.clause_type if pos else "other"

                if ct in financial_types:
                    cat = "financial"
                elif ct in governance_types:
                    cat = "governance"
                elif ct in exit_types:
                    cat = "exit_rights"
                else:
                    cat = "other"

                category_stats[cat]["total"] += 1
                if resp.response_type == "accepted":
                    category_stats[cat]["accepted"] += 1

        flexible = []
        firm = []
        for cat, stats in category_stats.items():
            if stats["total"] == 0:
                continue
            rate = stats["accepted"] / stats["total"]
            label = f"{cat}: accepted {stats['accepted']}/{stats['total']} proposals"
            if rate >= 0.5:
                flexible.append(label)
            else:
                firm.append(label)

        # Detect new issues raised
        emerging = []
        for round_ in rounds:
            for resp in round_.counterparty_responses:
                if resp.response_type == "new_issue":
                    emerging.append(resp.our_assessment)

        # Determine negotiation style
        all_responses = []
        for round_ in rounds:
            all_responses.extend(round_.counterparty_responses)
        total = len(all_responses)
        if total == 0:
            style = "unknown"
        else:
            accepted_rate = sum(1 for r in all_responses if r.response_type == "accepted") / total
            modified_rate = sum(1 for r in all_responses if r.response_type == "modified") / total
            if accepted_rate > 0.5:
                style = "collaborative"
            elif modified_rate > 0.3:
                style = "mixed"
            else:
                style = "positional"

        leverage = ""
        if flexible and firm:
            leverage = (
                f"Counterparty is flexible on {', '.join(f.split(':')[0] for f in flexible)} "
                f"but firm on {', '.join(f.split(':')[0] for f in firm)}. "
                f"Use flexible areas as leverage for firm areas."
            )

        return CounterpartyPattern(
            flexible_areas=flexible,
            firm_areas=firm,
            emerging_concerns=emerging,
            negotiation_style=style,
            leverage_assessment=leverage,
        )

    def recommend_strategy(
        self,
        pattern: CounterpartyPattern,
        positions: list[NegotiationPosition],
        responses: list[CounterpartyResponse],
    ) -> list[StrategyAdjustment]:
        """Generate next-round strategy based on counterparty patterns."""
        adjustments = []

        # Map position_id to response
        response_map = {r.position_id: r for r in responses}

        for position in positions:
            resp = response_map.get(position.id)
            if not resp:
                continue

            if resp.response_type == "accepted":
                # No adjustment needed — they accepted
                continue
            elif resp.response_type == "rejected":
                if position.priority == "must_have":
                    adjustments.append(StrategyAdjustment(
                        clause_type=position.clause_type,
                        current_position=position.our_language[:100],
                        recommended_adjustment=(
                            "Resubmit with market data support. "
                            "Consider bundling with a concession on a related term."
                        ),
                        rationale=f"Must-have position was rejected. {pattern.leverage_assessment}",
                        trade_suggestion=_suggest_trade(position, pattern),
                    ))
                else:
                    adjustments.append(StrategyAdjustment(
                        clause_type=position.clause_type,
                        current_position=position.our_language[:100],
                        recommended_adjustment="Consider dropping or using as concession for must-have items.",
                        rationale="Nice-to-have was rejected; save negotiation capital.",
                        trade_suggestion="",
                    ))
            elif resp.response_type == "modified":
                adjustments.append(StrategyAdjustment(
                    clause_type=position.clause_type,
                    current_position=position.our_language[:100],
                    recommended_adjustment=(
                        f"Counterparty counter-proposed. Evaluate their language: "
                        f"'{resp.their_language[:100]}'. "
                        "If within acceptable range, consider accepting with minor tweaks."
                    ),
                    rationale="Counter-proposal received — assess if within walk-away range.",
                    trade_suggestion="",
                ))

        return adjustments

    def get_round_summary(self, round_: NegotiationRound) -> dict:
        """Summary for the team dashboard."""
        by_response = round_.positions_by_response
        return {
            "round_number": round_.round_number,
            "total_positions": len(round_.our_positions),
            "accepted": by_response.get("accepted", 0),
            "rejected": by_response.get("rejected", 0),
            "modified": by_response.get("modified", 0),
            "new_issues": by_response.get("new_issue", 0),
            "acceptance_rate": round_.acceptance_rate,
            "counterparty_style": round_.counterparty_pattern.negotiation_style,
            "strategy_adjustments": len(round_.strategy_adjustments),
            "flexible_areas": round_.counterparty_pattern.flexible_areas,
            "firm_areas": round_.counterparty_pattern.firm_areas,
        }


def _clause_key(clause: Clause) -> str:
    """Key for matching clauses across versions."""
    ref = clause.section_reference.strip().lower()
    title = clause.title.strip().lower()
    return ref or title


def _text_similarity(text1: str, text2: str) -> float:
    """Simple text similarity using SequenceMatcher."""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def _suggest_trade(
    position: NegotiationPosition,
    pattern: CounterpartyPattern,
) -> str:
    """Suggest a trade based on counterparty's flexible areas."""
    if not pattern.flexible_areas:
        return ""
    flexible_cat = pattern.flexible_areas[0].split(":")[0]
    return f"Consider conceding on {flexible_cat} terms in exchange."
