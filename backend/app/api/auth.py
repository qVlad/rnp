"""Authentication endpoints: login, logout, me, bootstrap (first-run admin)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db
from app.services.auth import (
    CurrentUser,
    ROLES,
    clear_session_cookie,
    create_session_token,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str
    password: str


class BootstrapPayload(BaseModel):
    username: str
    password: str
    full_name: str | None = None


# ─── Bootstrap (first-run; disabled once any user exists) ─────────────────


async def _users_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(User.id)))).scalar() or 0)


@router.get("/needs-bootstrap")
async def needs_bootstrap(session: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Returns true iff zero users exist — UI uses it to redirect first-run
    visitors to a setup screen instead of plain /login."""
    return {"needs_bootstrap": await _users_count(session) == 0}


@router.post("/bootstrap")
async def bootstrap(
    payload: BootstrapPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create the first director account. Refused after first user exists."""
    if await _users_count(session) > 0:
        raise HTTPException(409, "bootstrap already done — at least one user exists")

    username = payload.username.strip().lower()
    if not username or not payload.password:
        raise HTTPException(400, "username and password required")
    if len(username) < 3 or len(username) > 64:
        raise HTTPException(400, "username must be 3-64 chars")
    if len(payload.password) < 8:
        raise HTTPException(400, "password must be >= 8 chars")

    try:
        pwd_hash = hash_password(payload.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    user = User(
        username=username,
        password_hash=pwd_hash,
        role="director",
        full_name=payload.full_name,
        is_active=True,
        last_login_at=datetime.now(timezone.utc),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = create_session_token(user)
    set_session_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
    }


# ─── Login / logout / me ──────────────────────────────────────────────────


@router.post("/login")
async def login(
    payload: LoginPayload,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    username = payload.username.strip().lower()
    user = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    # Same error for "user not found" and "wrong password" — don't leak which
    # usernames exist.
    if not user or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(401, "invalid username or password")

    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()

    token = create_session_token(user)
    set_session_cookie(response, token)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
    }


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_session_cookie(response)
    return {"status": "logged out"}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name,
    }


@router.get("/roles")
async def list_roles() -> dict[str, list[str]]:
    return {"roles": list(ROLES)}
