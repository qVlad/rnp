"""API: per-tenant настройки. Сейчас только WB-токен (Wildberries Seller API).

GET  /api/tenant/wb-token          → статус (валиден / нет / когда проверен)
PUT  /api/tenant/wb-token          → сохранить новый токен (+ валидация)
POST /api/tenant/wb-token/validate → проверить токен без сохранения

Только director может менять WB-токен (это даёт доступ к финансам компании).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Tenant
from app.db.session import get_db
from app.integrations.wb.client import WbApiClient, WbApiError
from app.services.audit import audit_log
from app.services.auth import CurrentUser, get_current_user, require_director
from app.services.secrets_crypto import encrypt

log = get_logger(__name__)

router = APIRouter(prefix="/api/tenant", tags=["tenant"])


class WbTokenPayload(BaseModel):
    token: str


def _decode_wb_token_sid(token: str) -> str | None:
    """Извлекает `sid` (seller ID) из WB JWT без проверки подписи."""
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return str(payload.get("sid") or "") or None
    except Exception:
        return None


async def _ping_wb(token: str) -> tuple[bool, str | None]:
    """Делает один запрос к WB common-api/ping чтобы убедиться что токен живой.

    Возвращает (ok, error_msg).
    """
    try:
        async with WbApiClient(token=token) as wb:
            # /ping есть на каждом хосте; common даёт самый низкий лимит.
            await wb.get("/ping", category="common")
        return True, None
    except WbApiError as e:
        return False, f"WB ответил {e.status}: {e.message}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


@router.get("/wb-token")
async def get_wb_token_status(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Статус WB-токена текущего tenant'а. Сам токен НЕ возвращаем —
    только метаданные (есть/нет, последняя валидация, seller_id)."""
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
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
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Сохранить токен. Валидирует /ping перед сохранением — если WB
    ответил 401/403, токен не сохраняется."""
    token = payload.token.strip()
    if not token or len(token) < 100:
        raise HTTPException(400, "token слишком короткий (ожидается JWT)")

    ok, err = await _ping_wb(token)
    if not ok:
        raise HTTPException(400, f"токен не прошёл валидацию: {err}")

    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    had_token_before = bool(tenant.wb_token)
    prev_seller_id = tenant.wb_token_seller_id
    # Шифруем перед сохранением (Fernet) — если ключ настроен; иначе
    # plaintext + warning в логах.
    was_set = bool(tenant.wb_token)
    tenant.wb_token = encrypt(token)
    tenant.wb_token_validated_at = datetime.now(timezone.utc)
    tenant.wb_token_seller_id = _decode_wb_token_sid(token)
    # Не пишем сам токен в audit — даже у director'а не должно быть
    # plain-доступа к чужим JWT через UI лога. Фиксируем только seller_id
    # и факт замены.
    await audit_log(
        session, "tenant_wb_token", "update" if had_token_before else "create",
        entity_id=str(tenant.id),
        before={"seller_id": prev_seller_id} if had_token_before else None,
        after={"seller_id": tenant.wb_token_seller_id},
        actor=user.username,
    )
    await session.commit()

    # Авто-триггер первичного backfill за 90 дней при ПЕРВОЙ установке токена.
    # Если токен меняли (was_set=True) — не дёргаем, директор сам решит.
    # Backfill за 90 дней — компромисс: достаточно для текущей аналитики
    # (P&L, units), не слишком долго (~5 мин на все таски).
    auto_sync_triggered: list[str] = []
    if not was_set:
        try:
            from app.sync.tasks import (
                sync_ad_campaigns_for_tenant,
                sync_offset_acts_for_tenant,
                sync_orders_for_tenant,
                sync_paid_storage_for_tenant,
                sync_redeem_notifications_for_tenant,
                sync_report_detail_for_tenant,
                sync_sales_for_tenant,
                sync_stocks_for_tenant,
            )
            sync_orders_for_tenant.delay(user.tenant_id)
            auto_sync_triggered.append("orders")
            sync_sales_for_tenant.delay(user.tenant_id)
            auto_sync_triggered.append("sales")
            sync_stocks_for_tenant.delay(user.tenant_id)
            auto_sync_triggered.append("stocks")
            sync_report_detail_for_tenant.delay(user.tenant_id, 90)
            auto_sync_triggered.append("report_detail")
            sync_paid_storage_for_tenant.delay(user.tenant_id)
            auto_sync_triggered.append("paid_storage")
            sync_redeem_notifications_for_tenant.delay(user.tenant_id, 90)
            auto_sync_triggered.append("redeem_notifications")
            sync_offset_acts_for_tenant.delay(user.tenant_id, 90)
            auto_sync_triggered.append("offset_acts")
            sync_ad_campaigns_for_tenant.delay(user.tenant_id)
            auto_sync_triggered.append("ad_campaigns")
        except Exception as e:
            # Sync — best-effort: токен уже сохранён, директор может вручную
            # пнуть sync через UI кнопками если авто-триггер не сработал.
            log.warning("auto-sync trigger failed for tenant %s: %s", user.tenant_id, e)

    return {
        "set": True,
        "seller_id": tenant.wb_token_seller_id,
        "validated_at": tenant.wb_token_validated_at.isoformat(),
        "auto_sync_triggered": auto_sync_triggered,
    }


@router.post("/wb-token/validate", dependencies=[Depends(require_director)])
async def validate_wb_token(payload: WbTokenPayload) -> dict[str, Any]:
    """Проверить токен без сохранения. Полезно перед PUT — UI делает
    проверку при потере фокуса на поле."""
    token = payload.token.strip()
    if not token:
        raise HTTPException(400, "token обязателен")
    ok, err = await _ping_wb(token)
    return {
        "valid": ok,
        "error": err,
        "seller_id": _decode_wb_token_sid(token) if ok else None,
    }


@router.delete("/wb-token", dependencies=[Depends(require_director)])
async def clear_wb_token(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    """Удалить токен (sync остановится после очистки)."""
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(404, "tenant not found")
    prev_seller_id = tenant.wb_token_seller_id
    had_token_before = bool(tenant.wb_token)
    tenant.wb_token = None
    tenant.wb_token_validated_at = None
    tenant.wb_token_seller_id = None
    if had_token_before:
        await audit_log(
            session, "tenant_wb_token", "delete",
            entity_id=str(tenant.id),
            before={"seller_id": prev_seller_id},
            actor=user.username,
        )
    await session.commit()
    return {"cleared": True}
