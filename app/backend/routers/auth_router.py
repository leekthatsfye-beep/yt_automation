"""
Auth router — login, user info, and admin user management.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.backend.auth import (
    authenticate,
    create_token,
    create_user,
    delete_user,
    list_users,
    change_password,
)
from app.backend.deps import get_current_user, require_admin, UserContext

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Shared limiter — same instance as main.py via app.state
_limiter = Limiter(key_func=get_remote_address)


# ── models ──────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_clean(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or len(v) > 64:
            raise ValueError("Invalid username")
        return v

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v or len(v) > 256:
            raise ValueError("Invalid password")
        return v


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        import re
        v = v.strip().lower()
        if not re.match(r'^[a-z0-9_]{3,32}$', v):
            raise ValueError("Username must be 3-32 chars, letters/numbers/underscores only")
        return v

    @field_validator("password")
    @classmethod
    def password_strong(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 256:
            raise ValueError("Password too long")
        return v

    @field_validator("display_name")
    @classmethod
    def display_name_clean(cls, v: str) -> str:
        return v.strip()[:64]


class ChangePasswordRequest(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def password_strong(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 256:
            raise ValueError("Password too long")
        return v


# ── endpoints ───────────────────────────────────────────────────────────


@router.post("/login")
@_limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest):
    """Authenticate and return JWT token. Rate-limited to 10 attempts/minute per IP."""
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_token(user["username"], user["role"])
    return {
        "token": token,
        "user": user,
    }


@router.get("/me")
async def get_me(user: UserContext = Depends(get_current_user)):
    """Return current user info (validates token)."""
    return {
        "username": user.username,
        "role": user.role,
    }


@router.get("/users")
async def get_users(user: UserContext = Depends(require_admin)):
    """List all users (admin only)."""
    return {"users": list_users()}


@router.post("/users")
async def create_producer(
    req: CreateUserRequest,
    user: UserContext = Depends(require_admin),
):
    """Create a new producer account (admin only)."""
    try:
        new_user = create_user(
            username=req.username,
            password=req.password,
            role="producer",
            display_name=req.display_name,
        )
        return new_user
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{username}")
async def remove_user(
    username: str,
    user: UserContext = Depends(require_admin),
):
    """Delete a producer account (admin only). Does not delete their files."""
    try:
        deleted = delete_user(username)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")
        return {"deleted": username}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/users/{username}/password")
async def update_password(
    username: str,
    req: ChangePasswordRequest,
    user: UserContext = Depends(require_admin),
):
    """Change a user's password (admin only)."""
    ok = change_password(username, req.password)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"updated": username}
