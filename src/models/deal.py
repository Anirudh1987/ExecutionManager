"""Deal model — the top-level container for an M&A transaction."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DealStatus(str, Enum):
    INTAKE = "intake"  # Documents being uploaded
    IN_REVIEW = "in_review"  # Active AI + human review
    PENDING_DISCUSSION = "pending_discussion"  # Team needs to align
    ADVISORY_DRAFTING = "advisory_drafting"  # Writing client advice
    DELIVERED = "delivered"  # Advice sent to client
    CLOSED = "closed"


class Deal(BaseModel):
    """An M&A deal — groups contracts and tracks overall review progress."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    client_name: str
    deal_type: str = ""  # "acquisition", "merger", "divestiture", etc.
    deal_value: str = ""
    client_side: str = "buyer"  # "buyer" or "seller" — changes risk perspective
    industry: str = ""
    jurisdiction: str = ""
    description: str = ""
    status: DealStatus = DealStatus.INTAKE
    contract_ids: list[str] = Field(default_factory=list)
    review_ids: list[str] = Field(default_factory=list)
    team_member_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    target_completion: datetime | None = None

    # Client advisory output
    executive_summary: str = ""
    key_risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
