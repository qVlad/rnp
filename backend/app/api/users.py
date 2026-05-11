"""User management — director-only CRUD."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services.auth import (
    CurrentUser,
    ROLES,
    hash_password,
    require_director,
)

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_director)],
)


class UserCreatePayload(BaseModel):
    username: str
    password: str
    role: str = "manager"
    full_name: str | None = None
    is_active: bool = True


class UserUpdatePayload(BaseModel):
    role: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    password: str | None = None  # None = don't change


def _row(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "full_name": u.full_name,
        "is_active": u.is_active,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@router.get("")
async def list_users(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    rows = (
        await session.execute(select(User).order_by(User.username))
    ).scalars().all()
    return {"items": [_row(u) for u in rows]}


@router.post("")
async def create_user(
    payload: UserCreatePayload, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> dict[str, Any]:
    username = payload.username.strip().lower()
    if not username or len(username) < 3:
        raise HTTPException(400, "username too short")
    if payload.role not in ROLES:
        raise HTTPException(400, f"unknown role; allowed: {list(ROLES)}")
    if len(payload.password) < 8:
        raise HTTPException(400, "password must be >= 8 chars")
    existing = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "username already exists")
    try:
        pwd_hash = hash_password(payload.password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    user = User(
        username=username,
        password_hash=pwd_hash,
        role=payload.role,
        full_name=payload.full_name,
        is_active=payload.is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _row(user)


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdatePayload,
    actor: CurrentUser = Depends(require_director),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "user not found")
    # Don't let a director demote/disable themselves — locks them out
    if user.id == actor.id and (
        (payload.role and payload.role != "director")
        or payload.is_active is False
    ):
        raise HTTPException(
            400, "you cannot demote or disable your own account"
        )
    if payload.role is not None:
        if payload.role not in ROLES:
            raise HTTPException(400, f"unknown role; allowed: {list(ROLES)}")
        user.role = payload.role
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        if len(payload.password) < 8:
            raise HTTPException(400, "password must be >= 8 chars")
        try:
            user.password_hash = hash_password(payload.password)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    await session.commit()
    await session.refresh(user)
    return _row(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    actor: CurrentUser = Depends(require_director),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, str]:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "user not found")
    if user.id == actor.id:
        raise HTTPException(400, "cannot delete your own account")
    await session.delete(user)
    await session.commit()
    return {"status": "deleted"}
