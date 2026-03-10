"""Tests for SQLite persistence store."""

import pytest

from src.models.contract import Contract
from src.models.deal import Deal
from src.models.review import Review
from src.models.team import TeamMember, Role
from src.services.sqlite_store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    s = SqliteStore(db_path=db_path)
    await s.init_db()
    yield s
    await s.close()


class TestSqliteStore:
    @pytest.mark.asyncio
    async def test_deal_crud(self, store):
        deal = Deal(name="Test Deal", client_name="Client A")
        await store.save_deal(deal)

        retrieved = await store.get_deal(deal.id)
        assert retrieved.name == "Test Deal"
        assert retrieved.client_name == "Client A"

        deals = await store.list_deals()
        assert len(deals) == 1

    @pytest.mark.asyncio
    async def test_contract_crud(self, store):
        contract = Contract(
            deal_id="deal-1",
            filename="test.pdf",
            title="Test SPA",
            raw_text="Sample contract text",
        )
        await store.save_contract(contract)

        retrieved = await store.get_contract(contract.id)
        assert retrieved.title == "Test SPA"

        by_deal = await store.get_contracts_for_deal("deal-1")
        assert len(by_deal) == 1

    @pytest.mark.asyncio
    async def test_review_crud(self, store):
        review = Review(contract_id="c-1", deal_id="d-1")
        await store.save_review(review)

        retrieved = await store.get_review(review.id)
        assert retrieved.contract_id == "c-1"

        by_deal = await store.get_reviews_for_deal("d-1")
        assert len(by_deal) == 1

    @pytest.mark.asyncio
    async def test_team_crud(self, store):
        member = TeamMember(name="Alice", email="a@b.com", role=Role.STRATEGIST)
        await store.save_team_member(member)

        retrieved = await store.get_team_member(member.id)
        assert retrieved.name == "Alice"

        members = await store.list_team_members()
        assert len(members) == 1

    @pytest.mark.asyncio
    async def test_team_assignment(self, store):
        m1 = TeamMember(name="A", email="a@b.com", role=Role.STRATEGIST)
        m2 = TeamMember(name="B", email="b@b.com", role=Role.ANALYST)
        await store.save_team_member(m1)
        await store.save_team_member(m2)

        await store.assign_team_to_deal("deal-1", [m1.id, m2.id])

        team = await store.get_team_for_deal("deal-1")
        assert len(team) == 2

    @pytest.mark.asyncio
    async def test_not_found_raises(self, store):
        with pytest.raises(KeyError):
            await store.get_deal("nonexistent")
