"""User view presets — CRUD сохранённых конфигураций страниц.

Один user может иметь несколько пресетов на каждый scope (страницу).
Один из них может быть отмечен `is_default=true` — он будет применён
автоматически при открытии страницы.

Используется на Dashboard (scope='dashboard') в первую очередь, но
endpoint generic — можно подключить к /units, /pnl и т.д.

Все mutations требуют залогиненного пользователя. Изоляция по
tenant_id (multi-tenant) и user_id (один user не видит пресеты другого).
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserViewPreset
from app.services.auth import CurrentUser, get_current_user, get_db_tenant_scoped

router = APIRouter(prefix="/api/view-presets", tags=["view-presets"])


def _to_dict(p: UserViewPreset) -> dict[str, Any]:
    return {
        "id": p.id,
        "scope": p.scope,
        "name": p.name,
        "state": p.state,
        "is_default": bool(p.is_default),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("")
async def list_presets(
    scope: Annotated[str, Query()],
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Все пресеты текущего юзера в указанном scope (например 'dashboard')."""
    stmt = (
        select(UserViewPreset)
        .where(UserViewPreset.user_id == user.id)
        .where(UserViewPreset.scope == scope)
        .order_by(UserViewPreset.is_default.desc(), UserViewPreset.name)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {"items": [_to_dict(p) for p in rows]}


@router.post("")
async def create_preset(
    scope: str = Body(..., embed=True),
    name: str = Body(..., embed=True),
    state: dict = Body(..., embed=True),
    is_default: bool = Body(default=False, embed=True),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Создать новый пресет. Имя должно быть уникальным в рамках scope.

    Если `is_default=true` — снимаем default-флаг с других пресетов того
    же scope этого юзера (только один default).
    """
    if not name.strip():
        raise HTTPException(400, "name не может быть пустым")
    name = name.strip()[:64]
    # Проверка уникальности
    existing = (
        await session.execute(
            select(UserViewPreset)
            .where(UserViewPreset.user_id == user.id)
            .where(UserViewPreset.scope == scope)
            .where(UserViewPreset.name == name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"Пресет «{name}» уже существует")

    if is_default:
        await _clear_other_defaults(session, user.id, scope, exclude_id=None)

    preset = UserViewPreset(
        tenant_id=user.tenant_id,
        user_id=user.id,
        scope=scope,
        name=name,
        state=state,
        is_default=is_default,
    )
    session.add(preset)
    await session.commit()
    await session.refresh(preset)
    return _to_dict(preset)


@router.put("/{preset_id}")
async def update_preset(
    preset_id: int,
    name: str | None = Body(default=None, embed=True),
    state: dict | None = Body(default=None, embed=True),
    is_default: bool | None = Body(default=None, embed=True),
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Обновить пресет (state / name / is_default). Только свои."""
    preset = await session.get(UserViewPreset, preset_id)
    if preset is None or preset.user_id != user.id:
        raise HTTPException(404, "Не найдено")
    if name is not None:
        name = name.strip()[:64]
        if not name:
            raise HTTPException(400, "name не может быть пустым")
        preset.name = name
    if state is not None:
        preset.state = state
    if is_default is True:
        await _clear_other_defaults(session, user.id, preset.scope, exclude_id=preset.id)
        preset.is_default = True
    elif is_default is False:
        preset.is_default = False
    preset.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(preset)
    return _to_dict(preset)


@router.delete("/{preset_id}")
async def delete_preset(
    preset_id: int,
    session: AsyncSession = Depends(get_db_tenant_scoped),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    preset = await session.get(UserViewPreset, preset_id)
    if preset is None or preset.user_id != user.id:
        raise HTTPException(404, "Не найдено")
    await session.delete(preset)
    await session.commit()
    return {"status": "ok"}


async def _clear_other_defaults(
    session: AsyncSession,
    user_id: int,
    scope: str,
    exclude_id: int | None,
) -> None:
    stmt = (
        select(UserViewPreset)
        .where(UserViewPreset.user_id == user_id)
        .where(UserViewPreset.scope == scope)
        .where(UserViewPreset.is_default.is_(True))
    )
    if exclude_id is not None:
        stmt = stmt.where(UserViewPreset.id != exclude_id)
    rows = (await session.execute(stmt)).scalars().all()
    for r in rows:
        r.is_default = False
