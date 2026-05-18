"""API для управления feature flags per-tenant.

GET /api/tenant-modules — список с состоянием (все KNOWN_MODULES, видно всем
                          ролям — для рендера меню на фронте).
PUT /api/tenant-modules/{code} — включить/выключить (director-only).

Audit log пишется на каждое PUT (см. правило 10 в `agents/RULES.md`).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TenantModule
from app.services.audit import audit_log
from app.services.auth import (
    CurrentUser,
    get_current_user,
    get_db_tenant_scoped,
    require_director,
)
from app.services.feature_flags import (
    ALWAYS_ENABLED,
    KNOWN_MODULES,
    list_modules,
)

router = APIRouter(prefix="/api/tenant-modules", tags=["tenant-modules"])


@router.get("")
async def get_modules(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Список модулей с их состоянием. Доступно всем ролям — нужно фронту для
    скрытия пунктов меню. Возвращает все KNOWN_MODULES (даже без записи в БД).
    """
    modules = await list_modules(session, user.tenant_id)
    return {
        "items": [
            {
                "code": code,
                "enabled": enabled,
                "always_on": code in ALWAYS_ENABLED,
            }
            for code, enabled in sorted(modules.items())
        ]
    }


@router.put("/{module_code}", dependencies=[Depends(require_director)])
async def set_module(
    module_code: str,
    enabled: bool = Body(..., embed=True),
    notes: str | None = Body(default=None, embed=True),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict:
    """Включить/выключить модуль для текущего tenant'а. Только director.

    `ALWAYS_ENABLED` модули (core) нельзя выключать — 400.
    Неизвестный module_code (не из KNOWN_MODULES) — 404.
    """
    if module_code not in KNOWN_MODULES:
        raise HTTPException(404, f"unknown module: {module_code}")
    if module_code in ALWAYS_ENABLED and not enabled:
        raise HTTPException(
            400,
            f"module {module_code!r} is always enabled and cannot be disabled",
        )

    now = datetime.now(timezone.utc) if enabled else None
    stmt = pg_insert(TenantModule).values(
        tenant_id=user.tenant_id,
        module_code=module_code,
        enabled=enabled,
        enabled_at=now,
        notes=notes,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["tenant_id", "module_code"],
        set_={
            "enabled": stmt.excluded.enabled,
            "enabled_at": stmt.excluded.enabled_at,
            "notes": stmt.excluded.notes,
        },
    )
    await session.execute(stmt)
    await audit_log(
        session,
        "tenant_modules",
        "update",
        entity_id=module_code,
        after={"enabled": enabled, "notes": notes},
        actor=user.username,
    )
    await session.commit()

    return {"module": module_code, "enabled": enabled}
