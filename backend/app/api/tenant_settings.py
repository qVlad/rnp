"""API: per-tenant настройки. Сейчас только WB-токен (Wildberries Seller API).

GET  /api/tenant/wb-token          → статус (валиден / нет / когда проверен)
PUT  /api/tenant/wb-token          → сохранить новый токен (+ валидация)
POST /api/tenant/wb-token/validate → проверить токен без сохранения
DELETE /api/tenant/wb-token        → удалить токен (sync остановится)

Только director может менять WB-токен (это даёт доступ к финансам компании).

Все операции — над АКТИВНЫМ кабинетом (`request.state.active_tenant_id`,
fallback — легаси `user.tenant_id`): BUG-DEV-028 — раньше директор,
переключившийся в кабинет B, перезаписывал токен кабинета A.

Общая логика (ping / шифрование / авто-sync) — `services/wb_token.py`
(переиспользуется `api/tenants.py`, мульти-кабинет DEV-092).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Tenant
from app.db.session import get_db
from app.services.active_tenant import get_active_tenant_id
from app.services.audit import audit_log
from app.services.auth import CurrentUser, get_current_user, require_director
from app.services.tenant_context import set_tenant
from app.services.wb_token import (
    decode_wb_token_sid,
    ping_wb,
    store_wb_token,
    trigger_initial_sync,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


class WbTokenPayload(BaseModel):
    token: str


async def _active_tenant(
    request: Request, user: CurrentUser, session: AsyncSession
) -> Tenant:
    """Tenant АКТИВНОГО кабинета (BUG-DEV-028: не домашнего из JWT)."""
    tid = get_active_tenant_id(request) or user.tenant_id
    tenant = await session.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    return tenant


@router.get("/wb-token")
async def get_wb_token_status(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Статус WB-токена активного tenant'а. Сам токен НЕ возвращаем —
    только метаданные (есть/нет, последняя валидация, seller_id)."""
    tenant = await _active_tenant(request, user, session)
    return {
        "set": bool(tenant.wb_token),
        "seller_id": tenant.wb_token_seller_id,
        "validated_at": (
            tenant.wb_token_validated_at.isoformat()
            if tenant.wb_token_validated_at else None
        ),
    }


@router.put("/wb-token", dependencies=[Depends(require_director)])
async def set_wb_token(
    payload: WbTokenPayload,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сохранить токен. Валидирует /ping перед сохранением — если WB
    ответил 401/403, токен не сохраняется."""
    token = payload.token.strip()
    if not token or len(token) < 100:
        raise HTTPException(400, "token слишком короткий (ожидается JWT)")

    ok, err = await ping_wb(token)
    if not ok:
        raise HTTPException(400, f"токен не прошёл валидацию: {err}")

    tenant = await _active_tenant(request, user, session)
    # audit_log пишет tenant-scoped AuditLog — сессии нужен tenant
    # (иначе NOT NULL на audit_log.tenant_id; латентный баг до DEV-092).
    set_tenant(session, int(tenant.id))
    was_set = await store_wb_token(session, tenant, token, actor=user.username)
    await session.commit()

    # Авто-триггер первичного backfill за 90 дней при ПЕРВОЙ установке токена.
    # Если токен меняли (was_set=True) — не дёргаем, директор сам решит.
    auto_sync_triggered: list[str] = []
    if not was_set:
        auto_sync_triggered = trigger_initial_sync(int(tenant.id))

    return {
        "set": True,
        "seller_id": tenant.wb_token_seller_id,
        "validated_at": tenant.wb_token_validated_at.isoformat(),
        "auto_sync_triggered": auto_sync_triggered,
    }


@router.post("/wb-token/validate", dependencies=[Depends(require_director)])
async def validate_wb_token(payload: WbTokenPayload) -> dict[str, Any]:
    """Проверить токен без сохранения. Tenant-agnostic — UI использует и
    для активного кабинета, и в модалке «Добавить кабинет» (DEV-092)."""
    token = payload.token.strip()
    if not token:
        raise HTTPException(400, "token обязателен")
    ok, err = await ping_wb(token)
    return {
        "valid": ok,
        "error": err,
        "seller_id": decode_wb_token_sid(token) if ok else None,
    }


@router.delete("/wb-token", dependencies=[Depends(require_director)])
async def clear_wb_token(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Удалить токен (sync остановится после очистки)."""
    tenant = await _active_tenant(request, user, session)
    prev_seller_id = tenant.wb_token_seller_id
    had_token_before = bool(tenant.wb_token)
    tenant.wb_token = None
    tenant.wb_token_validated_at = None
    tenant.wb_token_seller_id = None
    if had_token_before:
        set_tenant(session, int(tenant.id))
        await audit_log(
            session, "tenant_wb_token", "delete",
            entity_id=str(tenant.id),
            before={"seller_id": prev_seller_id},
            actor=user.username,
        )
    await session.commit()
    return {"cleared": True}
