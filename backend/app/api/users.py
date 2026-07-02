"""User management — director-only CRUD."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserTenantAccess
from app.db.session import get_db
from app.services.audit import audit_log, snapshot
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

# password_hash is excluded — audit log goes into JSONB and is readable by
# anyone with director access, which would defeat bcrypt.
_AUDIT_FIELDS = ["id", "username", "role", "full_name", "is_active", "boss_id"]

_MAX_BOSS_CHAIN_DEPTH = 5


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
        "boss_id": u.boss_id,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


class UserBossPayload(BaseModel):
    boss_id: int | None = None


async def _detect_boss_cycle(
    session: AsyncSession, user_id: int, boss_id: int
) -> bool:
    """True если назначение `user_id.boss_id = boss_id` создаст цикл.

    Идём вверх по цепочке boss→boss→… до глубины _MAX_BOSS_CHAIN_DEPTH.
    Если встретим user_id — цикл. Если упёрлись в NULL или глубину —
    OK. Глубина 5 — компромисс: реальные иерархии в малом бизнесе ≤ 3
    (manager → ROP → director), запас на 2 уровня.
    """
    if user_id == boss_id:
        return True
    current = boss_id
    for _ in range(_MAX_BOSS_CHAIN_DEPTH):
        next_boss = (
            await session.execute(
                select(User.boss_id).where(User.id == current)
            )
        ).scalar_one_or_none()
        if next_boss is None:
            return False
        if next_boss == user_id:
            return True
        current = next_boss
    # Дошли до глубины — конкретно цикла не нашли, но дальше не идём.
    # Считаем OK; если цикл глубже 5 — это уже патология, не наш случай.
    return False


@router.get("")
async def list_users(session: AsyncSession = Depends(get_db_tenant_scoped)) -> dict[str, Any]:
    rows = (
        await session.execute(select(User).order_by(User.username))
    ).scalars().all()
    return {"items": [_row(u) for u in rows]}


@router.post("")
async def create_user(
    payload: UserCreatePayload,
    actor: CurrentUser = Depends(require_director),
    session: AsyncSession = Depends(get_db_tenant_scoped),
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
    await session.flush()
    # BUG-DEV-029: без записи в user_tenant_access middleware active_tenant
    # возвращает новому юзеру 403 на всё. Tenant берём тот же, что before_flush
    # проставил юзеру (активный кабинет director'а).
    session.add(
        UserTenantAccess(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role,
            granted_by=actor.id,
        )
    )
    await audit_log(
        session, "users", "create",
        entity_id=str(user.id),
        after=snapshot(user, _AUDIT_FIELDS),
        actor=actor.username,
    )
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
    before = snapshot(user, _AUDIT_FIELDS)
    password_changed = False
    if payload.role is not None:
        if payload.role not in ROLES:
            raise HTTPException(400, f"unknown role; allowed: {list(ROLES)}")
        user.role = payload.role
        # Per-tenant роль (user_tenant_access) этого кабинета — синхронно,
        # иначе effective_role (BUG-DEV-030) останется старой.
        uta = (
            await session.execute(
                select(UserTenantAccess).where(
                    UserTenantAccess.user_id == user.id,
                    UserTenantAccess.tenant_id == user.tenant_id,
                )
            )
        ).scalar_one_or_none()
        if uta is not None:
            uta.role = payload.role
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password is not None:
        if len(payload.password) < 8:
            raise HTTPException(400, "password must be >= 8 chars")
        try:
            user.password_hash = hash_password(payload.password)
            password_changed = True
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    await audit_log(
        session, "users", "update",
        entity_id=str(user.id),
        before=before,
        after=snapshot(user, _AUDIT_FIELDS),
        actor=actor.username,
        comment="password changed" if password_changed else None,
    )
    await session.commit()
    await session.refresh(user)
    return _row(user)


@router.put("/{user_id}/boss")
async def set_user_boss(
    user_id: int,
    payload: UserBossPayload,
    actor: CurrentUser = Depends(require_director),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, Any]:
    """Назначить/снять boss'а у user'а (HYP-007).

    Boss используется в TG-share /weekly-report: при `recipient=self`
    отчёт менеджера летит boss'у вместо самого менеджера.

    Validations:
      - Cross-tenant boss запрещён (session уже tenant-scoped, но FK
        users.id может указать на чужой tenant если кто-то знает ID).
      - Cycle detection (A → B → A или глубже до 5 уровней).
      - Self-boss запрещён.
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "user not found")

    before = snapshot(user, _AUDIT_FIELDS)
    new_boss_id = payload.boss_id

    if new_boss_id is None:
        # Снимаем boss'а
        user.boss_id = None
    else:
        if new_boss_id == user_id:
            raise HTTPException(400, "user cannot be their own boss")
        boss = await session.get(User, new_boss_id)
        if not boss:
            raise HTTPException(404, "boss user not found")
        # Cross-tenant check (session уже фильтрует по tenant'у через
        # TenantScopedMixin → если boss из другого tenant'а, session.get
        # вернёт None и мы попали бы в 404. Но проверка явная для
        # robustness — на случай если в будущем сменим session-фильтр).
        if boss.tenant_id != user.tenant_id:
            raise HTTPException(400, "cannot assign boss from another tenant")
        if not boss.is_active:
            raise HTTPException(400, "boss user is inactive")
        if await _detect_boss_cycle(session, user_id, new_boss_id):
            raise HTTPException(
                400, "circular boss chain detected (depth ≤ 5)"
            )
        user.boss_id = new_boss_id

    await audit_log(
        session,
        "users",
        "update",
        entity_id=str(user.id),
        before=before,
        after=snapshot(user, _AUDIT_FIELDS),
        actor=actor.username,
        comment=f"boss_id set to {user.boss_id}",
    )
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
    before = snapshot(user, _AUDIT_FIELDS)
    await session.delete(user)
    await audit_log(
        session, "users", "delete",
        entity_id=str(user_id),
        before=before,
        actor=actor.username,
    )
    await session.commit()
    return {"status": "deleted"}
