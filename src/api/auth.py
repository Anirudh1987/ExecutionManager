"""JWT authentication for the M&A review platform.

Simple auth suitable for a 3-person law firm team:
- Password-hashed user accounts stored alongside team members
- JWT tokens for API access (HS256, manually implemented to avoid cryptography dep)
- Role-based access (strategist, analyst, coordinator)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# Configuration — override via environment variables
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-secret-change-in-production")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.environ.get("TOKEN_EXPIRE_HOURS", "12"))

security = HTTPBearer(auto_error=False)

# In-memory user store (syncs with team members)
_users: dict[str, dict] = {}


class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: str = "analyst"  # strategist, analyst, coordinator


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    name: str
    role: str


# --- Password hashing (SHA-256 + salt) ---

def hash_password(password: str, salt: str | None = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(plain: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(plain, salt), stored)


# --- JWT (HS256 manual implementation) ---

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _jwt_sign(payload_str: str) -> str:
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(payload_str.encode())
    message = f"{header}.{payload}"
    sig = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return f"{message}.{_b64url_encode(sig)}"


def _jwt_verify(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        message = f"{parts[0]}.{parts[1]}"
        expected_sig = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
        actual_sig = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(parts[1]))
        # Check expiry
        if "exp" in payload and payload["exp"] < time.time():
            return None
        return payload
    except Exception:
        return None


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = time.time() + ACCESS_TOKEN_EXPIRE_HOURS * 3600
    to_encode["exp"] = expire
    return _jwt_sign(json.dumps(to_encode))


def decode_token(token: str) -> dict:
    payload = _jwt_verify(token)
    if payload is None:
        raise ValueError("Invalid or expired token")
    return payload


# --- User management ---

def register_user(email: str, password: str, name: str, role: str, team_member_id: str = "") -> dict:
    """Register a new user. Returns user dict."""
    if email in _users:
        raise ValueError(f"User {email} already exists")
    user = {
        "email": email,
        "password_hash": hash_password(password),
        "name": name,
        "role": role,
        "team_member_id": team_member_id,
    }
    _users[email] = user
    return user


def authenticate_user(email: str, password: str) -> dict | None:
    """Verify credentials. Returns user dict or None."""
    user = _users.get(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


# --- FastAPI dependencies ---

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """FastAPI dependency — extracts and validates JWT from Authorization header.

    When AUTH_REQUIRED=0 (default for dev), returns a default user if no token provided.
    """
    auth_required = os.environ.get("AUTH_REQUIRED", "0") == "1"

    if credentials is None:
        if not auth_required:
            return {"email": "dev@local", "name": "Developer", "role": "strategist", "team_member_id": ""}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = decode_token(credentials.credentials)
        email: str = payload.get("sub", "")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = _users.get(email)
        if not user and not auth_required:
            return {"email": email, "name": email, "role": "analyst", "team_member_id": ""}
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_role(*roles: str):
    """Dependency factory — restrict endpoint to specific roles."""
    async def check_role(user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user['role']}' not authorized. Required: {', '.join(roles)}",
            )
        return user
    return check_role
