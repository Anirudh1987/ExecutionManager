"""Authentication endpoints — register, login, and user info."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.auth import (
    UserCreate,
    TokenResponse,
    authenticate_user,
    create_access_token,
    get_current_user,
    register_user,
    ACCESS_TOKEN_EXPIRE_HOURS,
)
from src.models.team import TeamMember, Role

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register", response_model=TokenResponse)
async def register(req: UserCreate, request: Request):
    """Register a new team member and get an access token."""
    store = request.app.state.store

    # Map string role to enum
    role_map = {"strategist": Role.STRATEGIST, "analyst": Role.ANALYST, "coordinator": Role.COORDINATOR}
    team_role = role_map.get(req.role, Role.ANALYST)

    # Create team member
    member = TeamMember(name=req.name, email=req.email, role=team_role)
    store.save_team_member(member)

    try:
        register_user(req.email, req.password, req.name, req.role, team_member_id=member.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = create_access_token({"sub": req.email, "role": req.role, "team_member_id": member.id})

    return TokenResponse(
        access_token=token,
        expires_in=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        user_id=member.id,
        name=req.name,
        role=req.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Authenticate and get an access token."""
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({
        "sub": user["email"],
        "role": user["role"],
        "team_member_id": user.get("team_member_id", ""),
    })

    return TokenResponse(
        access_token=token,
        expires_in=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        user_id=user.get("team_member_id", ""),
        name=user["name"],
        role=user["role"],
    )


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user info from JWT token."""
    return {
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "team_member_id": user.get("team_member_id", ""),
    }
