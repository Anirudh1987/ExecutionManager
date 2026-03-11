"""In-memory store — simple data persistence layer.

In production, replace with a proper database (PostgreSQL, etc.).
The interface is async to match SqliteStore, allowing both backends
to be used interchangeably.
"""

from __future__ import annotations

from src.models.contract import Contract
from src.models.deal import Deal
from src.models.review import Review
from src.models.team import TeamMember


class Store:
    """Simple in-memory store for all domain objects (async interface)."""

    def __init__(self):
        self._deals: dict[str, Deal] = {}
        self._contracts: dict[str, Contract] = {}
        self._reviews: dict[str, Review] = {}
        self._team_members: dict[str, TeamMember] = {}
        self._deal_team: dict[str, list[str]] = {}  # deal_id → [member_ids]

    # --- Deals ---
    async def save_deal(self, deal: Deal) -> None:
        self._deals[deal.id] = deal

    async def get_deal(self, deal_id: str) -> Deal:
        deal = self._deals.get(deal_id)
        if not deal:
            raise KeyError(f"Deal {deal_id} not found")
        return deal

    async def list_deals(self) -> list[Deal]:
        return list(self._deals.values())

    # --- Contracts ---
    async def save_contract(self, contract: Contract) -> None:
        self._contracts[contract.id] = contract

    async def get_contract(self, contract_id: str) -> Contract:
        contract = self._contracts.get(contract_id)
        if not contract:
            raise KeyError(f"Contract {contract_id} not found")
        return contract

    async def get_contracts_for_deal(self, deal_id: str) -> list[Contract]:
        return [c for c in self._contracts.values() if c.deal_id == deal_id]

    # --- Reviews ---
    async def save_review(self, review: Review) -> None:
        self._reviews[review.id] = review

    async def get_review(self, review_id: str) -> Review:
        review = self._reviews.get(review_id)
        if not review:
            raise KeyError(f"Review {review_id} not found")
        return review

    async def get_reviews_for_deal(self, deal_id: str) -> list[Review]:
        return [r for r in self._reviews.values() if r.deal_id == deal_id]

    # --- Team ---
    async def save_team_member(self, member: TeamMember) -> None:
        self._team_members[member.id] = member

    async def get_team_member(self, member_id: str) -> TeamMember:
        member = self._team_members.get(member_id)
        if not member:
            raise KeyError(f"TeamMember {member_id} not found")
        return member

    async def assign_team_to_deal(self, deal_id: str, member_ids: list[str]) -> None:
        self._deal_team[deal_id] = member_ids

    async def get_team_for_deal(self, deal_id: str) -> list[TeamMember]:
        member_ids = self._deal_team.get(deal_id, [])
        return [
            self._team_members[mid]
            for mid in member_ids
            if mid in self._team_members
        ]

    async def list_team_members(self) -> list[TeamMember]:
        return list(self._team_members.values())
