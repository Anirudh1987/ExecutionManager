"""Team management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.models.team import Role, TeamMember

router = APIRouter()


class CreateMemberRequest(BaseModel):
    name: str
    email: str
    role: Role


@router.post("/", response_model=dict)
async def create_team_member(req: CreateMemberRequest, request: Request):
    store = request.app.state.store
    member = TeamMember(name=req.name, email=req.email, role=req.role)
    await store.save_team_member(member)
    return {"id": member.id, "name": member.name, "role": member.role.value}


@router.get("/")
async def list_team(request: Request):
    store = request.app.state.store
    members = await store.list_team_members()
    return [
        {
            "id": m.id,
            "name": m.name,
            "email": m.email,
            "role": m.role.value,
            "active_reviews": m.active_reviews,
            "completed_reviews": m.completed_reviews,
        }
        for m in members
    ]
