"""SQLite-backed persistence store — async, same interface as in-memory Store."""

from __future__ import annotations

import json
import aiosqlite

from src.models.contract import Contract
from src.models.deal import Deal
from src.models.review import Review
from src.models.team import TeamMember


class SqliteStore:
    """Async SQLite store. Models stored as JSON blobs for simplicity."""

    def __init__(self, db_path: str = "executionmanager.db"):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS deals (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contracts (
                id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                deal_id TEXT NOT NULL,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS team_members (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deal_team (
                deal_id TEXT NOT NULL,
                member_id TEXT NOT NULL,
                PRIMARY KEY (deal_id, member_id)
            );
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # --- Deals ---
    async def save_deal(self, deal: Deal) -> None:
        data = deal.model_dump_json()
        await self._db.execute(
            "INSERT OR REPLACE INTO deals (id, data) VALUES (?, ?)",
            (deal.id, data),
        )
        await self._db.commit()

    async def get_deal(self, deal_id: str) -> Deal:
        async with self._db.execute(
            "SELECT data FROM deals WHERE id = ?", (deal_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise KeyError(f"Deal {deal_id} not found")
        return Deal.model_validate_json(row[0])

    async def list_deals(self) -> list[Deal]:
        async with self._db.execute("SELECT data FROM deals") as cursor:
            rows = await cursor.fetchall()
        return [Deal.model_validate_json(r[0]) for r in rows]

    # --- Contracts ---
    async def save_contract(self, contract: Contract) -> None:
        data = contract.model_dump_json()
        await self._db.execute(
            "INSERT OR REPLACE INTO contracts (id, deal_id, data) VALUES (?, ?, ?)",
            (contract.id, contract.deal_id, data),
        )
        await self._db.commit()

    async def get_contract(self, contract_id: str) -> Contract:
        async with self._db.execute(
            "SELECT data FROM contracts WHERE id = ?", (contract_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise KeyError(f"Contract {contract_id} not found")
        return Contract.model_validate_json(row[0])

    async def get_contracts_for_deal(self, deal_id: str) -> list[Contract]:
        async with self._db.execute(
            "SELECT data FROM contracts WHERE deal_id = ?", (deal_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [Contract.model_validate_json(r[0]) for r in rows]

    # --- Reviews ---
    async def save_review(self, review: Review) -> None:
        data = review.model_dump_json()
        await self._db.execute(
            "INSERT OR REPLACE INTO reviews (id, deal_id, data) VALUES (?, ?, ?)",
            (review.id, review.deal_id, data),
        )
        await self._db.commit()

    async def get_review(self, review_id: str) -> Review:
        async with self._db.execute(
            "SELECT data FROM reviews WHERE id = ?", (review_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise KeyError(f"Review {review_id} not found")
        return Review.model_validate_json(row[0])

    async def get_reviews_for_deal(self, deal_id: str) -> list[Review]:
        async with self._db.execute(
            "SELECT data FROM reviews WHERE deal_id = ?", (deal_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [Review.model_validate_json(r[0]) for r in rows]

    # --- Team ---
    async def save_team_member(self, member: TeamMember) -> None:
        data = member.model_dump_json()
        await self._db.execute(
            "INSERT OR REPLACE INTO team_members (id, data) VALUES (?, ?)",
            (member.id, data),
        )
        await self._db.commit()

    async def get_team_member(self, member_id: str) -> TeamMember:
        async with self._db.execute(
            "SELECT data FROM team_members WHERE id = ?", (member_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise KeyError(f"TeamMember {member_id} not found")
        return TeamMember.model_validate_json(row[0])

    async def assign_team_to_deal(self, deal_id: str, member_ids: list[str]) -> None:
        await self._db.execute(
            "DELETE FROM deal_team WHERE deal_id = ?", (deal_id,)
        )
        for mid in member_ids:
            await self._db.execute(
                "INSERT INTO deal_team (deal_id, member_id) VALUES (?, ?)",
                (deal_id, mid),
            )
        await self._db.commit()

    async def get_team_for_deal(self, deal_id: str) -> list[TeamMember]:
        async with self._db.execute(
            "SELECT member_id FROM deal_team WHERE deal_id = ?", (deal_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        members = []
        for (mid,) in rows:
            try:
                members.append(await self.get_team_member(mid))
            except KeyError:
                pass
        return members

    async def list_team_members(self) -> list[TeamMember]:
        async with self._db.execute("SELECT data FROM team_members") as cursor:
            rows = await cursor.fetchall()
        return [TeamMember.model_validate_json(r[0]) for r in rows]
